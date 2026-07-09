"""Safe local daily-run wrapper around the existing pipeline service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from app.config import Settings
from app.db.connection import Database
from app.domain.enums import JobSource
from app.services.analysis_rules import AnalysisRules
from app.services.normalization import CompanyAliases
from app.services.pipeline import PipelineRunRequest, PipelineService, RankingScope


class DailyRunConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DailySearch:
    name: str
    profile_id: str
    query: str = "Data Analyst"
    location: str = "Deutschland"
    sources: tuple[JobSource, ...] = (JobSource.ARBEITSAGENTUR,)
    max_pages: int = 1
    page_size: int = 10
    top_n: int = 10
    live_collect: bool = False
    preview_notification: bool = False
    include_prefilter_only: bool = False
    max_detail_requests: int | None = None
    ranking_scope: RankingScope = RankingScope.CURRENT_RUN

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> "DailySearch":
        if not isinstance(value, dict):
            raise DailyRunConfigError("Each daily search must be a JSON object")
        name = str(value.get("name") or "").strip()
        profile_id = str(value.get("profile_id") or "").strip()
        if not name:
            raise DailyRunConfigError("Daily search is missing required field: name")
        if not profile_id:
            raise DailyRunConfigError(
                f"Daily search {name!r} is missing required field: profile_id"
            )
        return cls(
            name=name,
            profile_id=profile_id,
            query=str(value.get("query") or "Data Analyst"),
            location=str(value.get("location") or "Deutschland"),
            sources=_sources(value.get("source", value.get("sources", "arbeitsagentur"))),
            max_pages=_int(value.get("max_pages", 1), "max_pages", minimum=1),
            page_size=_int(value.get("page_size", 10), "page_size", minimum=1),
            top_n=_int(value.get("top_n", 10), "top_n", minimum=1),
            live_collect=bool(value.get("live_collect", False)),
            preview_notification=bool(value.get("preview_notification", False)),
            include_prefilter_only=bool(value.get("include_prefilter_only", False)),
            max_detail_requests=_optional_int(
                value.get("max_detail_requests"),
                "max_detail_requests",
                minimum=0,
            ),
            ranking_scope=_ranking_scope(
                value.get("ranking_scope", RankingScope.CURRENT_RUN.value)
            ),
        )


PipelineFactory = Callable[[], PipelineService]


class DailyRunService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        rules: AnalysisRules,
        *,
        aliases: CompanyAliases | None = None,
        pipeline_factory: PipelineFactory | None = None,
        now: Callable[[], datetime] | None = None,
        output_dir: Path | None = None,
        lock_path: Path | None = None,
    ):
        self.database = database
        self.settings = settings
        self.rules = rules
        self.aliases = aliases
        self.pipeline_factory = pipeline_factory or self._pipeline
        self.now = now or (lambda: datetime.now(UTC))
        self.output_dir = output_dir or settings.repo_root / "data" / "daily_runs"
        self.lock_path = lock_path or settings.repo_root / "data" / "locks" / "daily_run.lock"

    def run_one(self, search: DailySearch) -> dict[str, object]:
        return self.run_many((search,))

    def run_config_file(self, path: Path) -> dict[str, object]:
        return self.run_many(load_searches(path))

    def run_many(self, searches: tuple[DailySearch, ...]) -> dict[str, object]:
        if not searches:
            raise DailyRunConfigError("Daily run requires at least one search")
        run_id = str(uuid4())
        started_at = self.now()
        lock = _DailyRunLock(self.lock_path, run_id, started_at)
        if not lock.acquire():
            return {
                "run_id": run_id,
                "started_at": started_at.isoformat(),
                "finished_at": self.now().isoformat(),
                "status": "locked",
                "message": (
                    "Daily run lock already exists. Another run may be active; "
                    f"remove {self.lock_path} only after verifying it is stale."
                ),
                "total_searches": len(searches),
                "successful_searches": 0,
                "failed_searches": 0,
                "searches": [],
                "errors": [],
                "output_path": None,
            }
        try:
            rows: list[dict[str, object]] = []
            errors: list[dict[str, object]] = []
            for search in searches:
                rows.append(self._run_search(search, errors))
            failed = sum(1 for row in rows if row["status"] == "failed")
            finished_at = self.now()
            summary: dict[str, object] = {
                "run_id": run_id,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "status": (
                    "completed"
                    if failed == 0
                    else "failed" if failed == len(rows)
                    else "completed_with_errors"
                ),
                "total_searches": len(rows),
                "successful_searches": len(rows) - failed,
                "failed_searches": failed,
                "searches": rows,
                "errors": errors,
            }
            output_path = self._write_summary(summary, started_at, run_id)
            return summary
        finally:
            lock.release()

    def _run_search(
        self,
        search: DailySearch,
        errors: list[dict[str, object]],
    ) -> dict[str, object]:
        try:
            summary = self.pipeline_factory().run(
                PipelineRunRequest(
                    profile_id=search.profile_id,
                    query=search.query,
                    location=search.location,
                    sources=search.sources,
                    max_pages=search.max_pages,
                    page_size=search.page_size,
                    top_n=search.top_n,
                    live_collect=search.live_collect,
                    preview_notification=search.preview_notification,
                    include_prefilter_only=search.include_prefilter_only,
                    max_detail_requests=search.max_detail_requests,
                    ranking_scope=search.ranking_scope,
                    dashboard_hint=True,
                )
            )
            collected = _jobs_collected(summary)
            return {
                "name": search.name,
                "status": "completed",
                "jobs_collected": collected,
                "top_jobs_count": len(summary.get("top_jobs", [])),
                "pipeline_summary": summary,
                "output_path": summary.get("output_path"),
            }
        except Exception as error:
            safe_error = {
                "name": search.name,
                "error_type": type(error).__name__,
                "message": str(error),
            }
            errors.append(safe_error)
            return {
                "name": search.name,
                "status": "failed",
                "jobs_collected": 0,
                "top_jobs_count": 0,
                "pipeline_summary": None,
                "output_path": None,
                "error": safe_error,
            }

    def _pipeline(self) -> PipelineService:
        return PipelineService(
            self.database,
            self.settings,
            self.rules,
            aliases=self.aliases,
        )

    def _write_summary(
        self,
        summary: dict[str, object],
        started_at: datetime,
        run_id: str,
    ) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"daily_{started_at.strftime('%Y%m%dT%H%M%SZ')}_{run_id}.json"
        summary["output_path"] = str(path)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path


def load_searches(path: Path) -> tuple[DailySearch, ...]:
    resolved = path.expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise DailyRunConfigError(f"Daily search config not found: {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DailyRunConfigError(f"Daily search config is not valid JSON: {resolved}") from error
    if not isinstance(payload, list):
        raise DailyRunConfigError("Daily search config must be a JSON list")
    return tuple(DailySearch.from_mapping(item) for item in payload)


class _DailyRunLock:
    def __init__(self, path: Path, run_id: str, started_at: datetime):
        self.path = path
        self.run_id = run_id
        self.started_at = started_at
        self.acquired = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "pid": os.getpid(),
        }, ensure_ascii=False)
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            return False
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        self.acquired = True
        return True

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


def _sources(value: object) -> tuple[JobSource, ...]:
    if isinstance(value, str):
        raw = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        raw = [str(item).strip() for item in value]
    else:
        raise DailyRunConfigError("source must be a string or list")
    sources: list[JobSource] = []
    for item in raw:
        if not item:
            continue
        try:
            source = JobSource(item.casefold())
        except ValueError as error:
            raise DailyRunConfigError(f"Unsupported daily search source: {item}") from error
        if source not in {JobSource.ARBEITSAGENTUR, JobSource.ENGLISHJOBS}:
            raise DailyRunConfigError(f"Unsupported daily search source: {item}")
        if source not in sources:
            sources.append(source)
    if not sources:
        raise DailyRunConfigError("At least one daily search source is required")
    return tuple(sources)


def _int(value: object, field: str, *, minimum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise DailyRunConfigError(f"{field} must be an integer") from error
    if parsed < minimum:
        raise DailyRunConfigError(f"{field} must be >= {minimum}")
    return parsed


def _optional_int(value: object, field: str, *, minimum: int) -> int | None:
    if value is None:
        return None
    return _int(value, field, minimum=minimum)


def _ranking_scope(value: object) -> RankingScope:
    normalized = str(value or "").strip().replace("_", "-")
    try:
        return RankingScope(normalized)
    except ValueError as error:
        raise DailyRunConfigError(
            "ranking_scope must be 'global' or 'current-run'"
        ) from error


def _jobs_collected(summary: dict[str, object]) -> int:
    collection = summary.get("collection", {})
    if not isinstance(collection, dict):
        return 0
    total = 0
    for item in collection.values():
        if isinstance(item, dict):
            total += int(item.get("jobs_collected", 0) or 0)
    return total
