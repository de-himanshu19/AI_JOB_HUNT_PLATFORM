"""Safe one-command orchestration for the local job-hunt workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import UUID

from app.config import Settings
from app.db.connection import Database
from app.db.repositories import ApplicationRepository, CandidateProfileRepository, JobRepository
from app.domain.analysis import AnalysisAuthority
from app.domain.enums import JobSource
from app.services.analysis_rules import AnalysisRules
from app.services.collection import CollectionService
from app.services.deduplication import DEDUPLICATION_VERSION, DeduplicationService
from app.services.normalization import CompanyAliases
from app.services.notifications import NotificationFormatter, NotificationService
from app.services.ranking import RankedVacancy, RankingService
from app.sources.arbeitsagentur.adapter import ArbeitsagenturAdapter
from app.sources.arbeitsagentur.client import ArbeitsagenturClient
from app.sources.base import CollectionRequest, JobSourceAdapter, SourceRunStatus
from app.sources.englishjobs.adapter import EnglishJobsAdapter
from app.sources.englishjobs.client import EnglishJobsClient


CollectorFactory = Callable[[JobSource], JobSourceAdapter]


@dataclass(frozen=True)
class PipelineRunRequest:
    profile_id: UUID | str
    query: str = "Data Analyst"
    location: str = "Deutschland"
    sources: tuple[JobSource, ...] = (JobSource.ARBEITSAGENTUR,)
    max_pages: int = 1
    page_size: int = 10
    top_n: int = 10
    live_collect: bool = False
    preview_notification: bool = False
    include_prefilter_only: bool = False
    output_path: Path | None = None
    dashboard_hint: bool = True


class PipelineService:
    """Coordinate existing services without adding new business rules."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        rules: AnalysisRules,
        *,
        aliases: CompanyAliases | None = None,
        collector_factory: CollectorFactory | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.database = database
        self.settings = settings
        self.rules = rules
        self.aliases = aliases
        self.collector_factory = collector_factory or self._live_collector
        self.now = now or (lambda: datetime.now(UTC))

    def run(self, request: PipelineRunRequest) -> dict[str, object]:
        self._validate_profile(request.profile_id)
        self._validate_sources(request.sources)
        if not request.live_collect and not self._stored_jobs_count():
            raise ValueError(
                "No stored jobs available. Re-run with --live-collect or import jobs first."
            )

        collection = self._collect(request)
        deduplication = self._deduplicate()
        ranked = RankingService(self.database, self.rules).rank(
            request.profile_id,
            DEDUPLICATION_VERSION,
            as_of=self.now(),
            include_prefilter_only=request.include_prefilter_only,
        )
        analysis_summary = self._analysis_summary(request.profile_id)
        ranking_summary = self._ranking_summary(ranked)
        preview_summary = self._notification_preview(request, ranked)
        top_jobs = self._top_jobs(ranked, request.top_n, request.profile_id)

        summary: dict[str, object] = {
            "profile_id": str(request.profile_id),
            "query": request.query,
            "location": request.location,
            "sources_requested": [source.value for source in request.sources],
            "live_collect": request.live_collect,
            "collection": collection,
            "deduplication": deduplication,
            "analysis": analysis_summary,
            "ranking": ranking_summary,
            "notification_preview": preview_summary,
            "top_jobs": top_jobs,
            "next_actions": self._next_actions(request, top_jobs),
        }
        output_path = self._write_summary(summary, request.output_path)
        summary["output_path"] = str(output_path)
        return summary

    def _collect(self, request: PipelineRunRequest) -> dict[str, object]:
        if not request.live_collect:
            return {
                source.value: {
                    "status": "skipped",
                    "reason": "live collection was not requested",
                    "network_requested": False,
                    "database_modified": False,
                }
                for source in request.sources
            }

        result: dict[str, object] = {}
        for source in request.sources:
            try:
                report = CollectionService(self.database).execute(
                    self.collector_factory(source),
                    CollectionRequest(
                        queries=(request.query,),
                        location=request.location,
                        max_pages=request.max_pages,
                        page_size=request.page_size,
                    ),
                    source=source,
                    dry_run=False,
                )
                counts = self._description_counts(report.source_result)
                result[source.value] = {
                    "status": report.source_result.status.value,
                    "inserted": report.jobs_inserted,
                    "updated": report.jobs_updated,
                    "description_versions_inserted": report.description_versions_inserted,
                    "full_descriptions": counts["full"],
                    "snippet_descriptions": counts["snippet"],
                    "missing_descriptions": counts["missing"],
                    "jobs_collected": len(report.source_result.jobs),
                    "errors": [
                        error.model_dump(mode="json")
                        for error in report.source_result.errors
                    ],
                    "network_requested": True,
                    "database_modified": True,
                }
                if report.source_result.status is SourceRunStatus.FAILED:
                    result[source.value]["status"] = "failed"
            except Exception as error:
                result[source.value] = {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "network_requested": True,
                    "database_modified": False,
                }
        if all(value.get("status") == "failed" for value in result.values()):
            raise RuntimeError("All requested source collections failed")
        return result

    def _deduplicate(self) -> dict[str, object]:
        aliases = self.aliases or CompanyAliases.from_json(
            self.settings.company_aliases_path
        )
        report = DeduplicationService(self.database, aliases=aliases).backfill(
            algorithm_version=DEDUPLICATION_VERSION
        )
        return {
            "status": "completed",
            "algorithm_version": report.algorithm_version,
            "jobs_normalized": report.jobs_normalized,
            "descriptions_normalized": report.descriptions_normalized,
            "logical_vacancies": report.clusters_created,
            "links": report.links_created,
            "review_candidates": report.review_candidates_created,
        }

    def _notification_preview(
        self,
        request: PipelineRunRequest,
        ranked: list[RankedVacancy],
    ) -> dict[str, object]:
        if not request.preview_notification:
            return {
                "created": False,
                "selected_count": 0,
                "network_requested": False,
                "database_modified": False,
            }
        preview = NotificationService(
            self.database,
            formatter=NotificationFormatter(self.settings.telegram_message_max_chars),
        ).preview(
            profile_id=request.profile_id,
            ranking_version=self.rules.ranking_version,
            duplicate_algorithm_version=DEDUPLICATION_VERSION,
            top_n=min(request.top_n, len(ranked) or request.top_n),
            min_rank_score=self.settings.telegram_min_rank_score,
        )
        return {
            "created": True,
            "selected_count": preview.selected_count,
            "chunks": [
                {"index": chunk.index, "characters": len(chunk.text)}
                for chunk in preview.chunks
            ],
            "network_requested": False,
            "database_modified": False,
        }

    def _analysis_summary(self, profile_id: UUID | str) -> dict[str, object]:
        with self.database.read_connection() as connection:
            rows = connection.execute(
                """SELECT authority, COUNT(*) AS count
                FROM job_analyses
                WHERE profile_id = ?
                  AND analyzer_version = ?
                  AND rules_version = ?
                  AND ranking_version = ?
                GROUP BY authority""",
                (
                    str(profile_id),
                    self.rules.analyzer_version,
                    self.rules.rules_version,
                    self.rules.ranking_version,
                ),
            ).fetchall()
        counts = {row["authority"]: int(row["count"]) for row in rows}
        return {
            "status": "completed",
            "authoritative": counts.get(AnalysisAuthority.AUTHORITATIVE.value, 0),
            "prefilter_only": counts.get(AnalysisAuthority.PREFILTER_ONLY.value, 0),
        }

    @staticmethod
    def _ranking_summary(ranked: list[RankedVacancy]) -> dict[str, object]:
        counts = {
            AnalysisAuthority.AUTHORITATIVE.value: 0,
            AnalysisAuthority.PREFILTER_ONLY.value: 0,
        }
        for item in ranked:
            counts[item.ranking.authority.value] += 1
        return {
            "status": "completed",
            "authoritative": counts[AnalysisAuthority.AUTHORITATIVE.value],
            "prefilter_only": counts[AnalysisAuthority.PREFILTER_ONLY.value],
        }

    def _top_jobs(
        self, ranked: list[RankedVacancy], top_n: int, profile_id: UUID | str
    ) -> list[dict[str, object]]:
        tracked = self._application_statuses(profile_id)
        rows = []
        for position, item in enumerate(ranked[:top_n], 1):
            job = item.job
            location = job.location_raw or ", ".join(
                value for value in (job.city, job.region, job.country) if value
            )
            rows.append({
                "rank": position,
                "job_id": str(job.id),
                "cluster_id": str(item.ranking.cluster_id),
                "title": job.title_raw,
                "company": job.company_raw,
                "location": location,
                "rank_score": item.ranking.rank_score,
                "fit_score": item.fit_score,
                "authority": item.ranking.authority.value,
                "application_status": (
                    tracked.get(str(item.ranking.cluster_id))
                    or tracked.get(str(job.id))
                ),
            })
        return rows

    def _application_statuses(self, profile_id: UUID | str) -> dict[str, str]:
        with self.database.read_connection() as connection:
            applications = ApplicationRepository(connection).list(
                profile_id=profile_id
            )
        statuses: dict[str, str] = {}
        for application in applications:
            statuses[str(application.job_id)] = application.status.value
            if application.logical_cluster_id:
                statuses[str(application.logical_cluster_id)] = application.status.value
        return statuses

    @staticmethod
    def _description_counts(source_result) -> dict[str, int]:
        counts = {"full": 0, "snippet": 0, "missing": 0}
        for collected in source_result.jobs:
            counts[collected.description.completeness.value] += 1
        return counts

    def _next_actions(
        self, request: PipelineRunRequest, top_jobs: list[dict[str, object]]
    ) -> list[str]:
        actions: list[str] = []
        if request.dashboard_hint:
            actions.append("Open dashboard with: python -m app.dashboard")
        if top_jobs:
            first = top_jobs[0]
            actions.append(
                "Shortlist top match with: python -m app.cli applications shortlist "
                f"--profile-id {request.profile_id} --job-id {first['job_id']} "
                "--priority high --note \"Top ranked match\""
            )
            actions.append(
                "Generate CV with: python -m app.cli cv generate "
                "--job-id <JOB_ID> --profile-id <PROFILE_ID> --force-regenerate"
            )
        return actions

    def _write_summary(
        self, summary: dict[str, object], output_path: Path | None
    ) -> Path:
        path = output_path or (
            self.settings.repo_root
            / "data"
            / "pipeline_runs"
            / f"pipeline_{self.now().strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        path = path.expanduser().resolve(strict=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def _validate_profile(self, profile_id: UUID | str) -> None:
        with self.database.read_connection() as connection:
            profile = CandidateProfileRepository(connection).get(profile_id)
        if profile is None:
            raise KeyError(f"Candidate profile not found: {profile_id}")

    @staticmethod
    def _validate_sources(sources: tuple[JobSource, ...]) -> None:
        if not sources:
            raise ValueError("At least one source is required")
        unsupported = [source for source in sources if source not in {
            JobSource.ARBEITSAGENTUR, JobSource.ENGLISHJOBS,
        }]
        if unsupported:
            raise ValueError(
                "Unsupported pipeline source(s): "
                + ", ".join(source.value for source in unsupported)
            )

    def _stored_jobs_count(self) -> int:
        with self.database.read_connection() as connection:
            return len(JobRepository(connection).list_all())

    def _live_collector(self, source: JobSource) -> JobSourceAdapter:
        if source is JobSource.ARBEITSAGENTUR:
            return ArbeitsagenturAdapter(
                self.settings,
                ArbeitsagenturClient(self.settings),
            )
        if source is JobSource.ENGLISHJOBS:
            return EnglishJobsAdapter(
                self.settings,
                EnglishJobsClient(self.settings),
            )
        raise ValueError(f"Unsupported pipeline source: {source.value}")
