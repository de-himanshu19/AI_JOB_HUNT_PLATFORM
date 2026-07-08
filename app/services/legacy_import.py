"""Dry-run-first legacy import workflows for Milestone 9."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from app.config import Settings
from app.db.connection import Database
from app.db.repositories import (
    CandidateProfileRepository,
    DuplicateRepository,
    JobDescriptionRepository,
    JobRepository,
    LegacyImportRepository,
)
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.domain.legacy_import import (
    IMPORTER_VERSION,
    LegacyArtifactKind,
    LegacyBackup,
    LegacyImportAction,
    LegacyImportBatch,
    LegacyImportItem,
    LegacyImportMapping,
    LegacyImportMode,
    LegacyImportPlan,
    LegacyImportStatus,
    LegacyItemType,
    LegacySourceType,
)
from app.sources.englishjobs.url_builder import build_fingerprint, normalize_identity_url


REQUIRED_ENGLISHJOBS_COLUMNS = {
    "job_title",
    "company",
    "location",
    "job_url",
    "description_snippet",
    "scraped_at",
}
REQUIRED_STATE_COLUMNS = {
    "state_key",
    "state_slug",
    "job_title",
    "company",
    "city",
    "job_url",
    "description_snippet",
    "scraped_at",
    "job_id",
}
IMPORTABLE_SOURCE_TYPES = {
    LegacySourceType.ENGLISHJOBS_CSV,
    LegacySourceType.STATE_INTELLIGENCE_CSV,
    LegacySourceType.SENT_JOBS_JSON,
    LegacySourceType.MASTER_CV_JSON,
    LegacySourceType.LEGACY_ARTIFACT,
    LegacySourceType.MYSQL_FIXTURE,
}


class LegacyImportError(ValueError):
    """Raised for unsafe or unsupported legacy import requests."""


class LegacyMySQLReader(Protocol):
    """Read-only boundary for optional legacy MySQL access."""

    def read_table(self, table: str, *, limit: int) -> list[dict[str, Any]]:
        ...


class FixtureMySQLReader:
    """Fixture-backed MySQL reader used by tests and ordinary implementation."""

    def __init__(self, rows_by_table: dict[str, list[dict[str, Any]]]):
        self.rows_by_table = rows_by_table

    def read_table(self, table: str, *, limit: int) -> list[dict[str, Any]]:
        if limit < 1:
            raise LegacyImportError("MySQL fixture limit must be positive")
        return list(self.rows_by_table.get(table, ()))[:limit]


class SelectOnlyMySQLReader:
    """Optional real-reader guard; deliberately dependency-free until enabled."""

    FORBIDDEN = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE)\b",
        re.IGNORECASE,
    )

    def __init__(self, settings: Settings):
        if not settings.legacy_mysql_enabled:
            raise LegacyImportError("LEGACY_MYSQL_ENABLED must be true for real MySQL")
        raise LegacyImportError(
            "Real MySQL access is intentionally not required for Milestone 9 tests; "
            "use an injected reader or add an optional driver in a later approval."
        )

    @classmethod
    def validate_select(cls, statement: str) -> None:
        stripped = statement.strip()
        if not stripped.lower().startswith("select") or cls.FORBIDDEN.search(stripped):
            raise LegacyImportError("Legacy MySQL reader permits SELECT statements only")


@dataclass(frozen=True)
class _ParsedRecord:
    item_key: str
    item_type: LegacyItemType
    source_identifier: str | None
    content_checksum: str | None
    confidence: float
    payload: dict[str, Any]
    warnings: tuple[str, ...] = ()


def _now() -> datetime:
    return datetime.now(UTC)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return _now()
    normalized = value.strip()
    if not normalized:
        return _now()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        except ValueError:
            continue
    return _now()


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip().casefold() or None


def _city_from_location(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(",", 1)[0].strip() or None


def _englishjobs_identity(row: dict[str, Any]) -> str:
    url = _clean(row.get("job_url"))
    normalized_url = normalize_identity_url(url)
    if normalized_url:
        if "/clickout/" in normalized_url:
            return f"clickout_url:{normalized_url}"
        return f"listing_url:{normalized_url}"
    legacy_id = _clean(row.get("job_id"))
    if legacy_id:
        return f"legacy_job_id:{legacy_id}"
    return "fingerprint:" + build_fingerprint(
        _clean(row.get("job_title")),
        _clean(row.get("company")),
        _clean(row.get("location")) or _clean(row.get("city")),
        _clean(row.get("published_date")),
    )


def _artifact_kind(path: Path, requested: str | None = None) -> LegacyArtifactKind:
    if requested:
        return LegacyArtifactKind(requested)
    name = path.name.lower()
    if "flowcv" in name:
        return LegacyArtifactKind.FLOWCV_TXT
    if "evidence" in name:
        return LegacyArtifactKind.EVIDENCE_REPORT
    if "debug" in name or "ai_response" in name:
        return LegacyArtifactKind.AI_DEBUG
    if "cover" in name:
        return LegacyArtifactKind.COVER_LETTER
    if "analysis" in name:
        return LegacyArtifactKind.ANALYSIS_REPORT
    return LegacyArtifactKind.OTHER_TXT


class LegacyImportService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings

    def create_backup(self, backup_dir: Path | None = None) -> LegacyBackup:
        backup_dir = backup_dir or (self.settings.data_dir / "backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        source = self.database.path
        if not source.exists():
            # Ensure the SQLite file exists before using the SQLite backup API.
            with self.database.read_connection():
                pass
        created_at = _now()
        backup_path = backup_dir / (
            f"{source.stem}-{created_at.strftime('%Y%m%d%H%M%S')}.sqlite3"
        )
        with sqlite3.connect(source) as src, sqlite3.connect(backup_path) as dst:
            src.backup(dst)
        checksum = _hash_file(backup_path)
        size = backup_path.stat().st_size
        verified = self._verify_sqlite_file(backup_path, checksum)
        backup = LegacyBackup(
            database_path=source,
            backup_path=backup_path,
            sha256=checksum,
            size_bytes=size,
            verified=verified,
            created_at=created_at,
            verified_at=_now() if verified else None,
        )
        with self.database.transaction() as connection:
            LegacyImportRepository(connection).create_backup(backup)
        return backup

    def dry_run(
        self,
        source_type: LegacySourceType,
        path: Path,
        *,
        mysql_reader: LegacyMySQLReader | None = None,
    ) -> LegacyImportPlan:
        records = self._records(source_type, path, mysql_reader=mysql_reader)
        return self._plan(source_type, path, records, database_modified=False)

    def apply(
        self,
        source_type: LegacySourceType,
        path: Path,
        *,
        backup_id: UUID | str,
        profile_key: str | None = None,
        artifact_kind: str | None = None,
        mysql_reader: LegacyMySQLReader | None = None,
    ) -> LegacyImportPlan:
        records = self._records(source_type, path, mysql_reader=mysql_reader)
        plan = self._plan(source_type, path, records, database_modified=True)
        with self.database.transaction() as connection:
            repository = LegacyImportRepository(connection)
            backup = repository.get_backup(backup_id)
            self._verify_backup_gate(backup)
            existing = repository.find_completed_batch(
                source_type, plan.source_name, plan.source_checksum, IMPORTER_VERSION
            )
            if existing:
                return plan.model_copy(
                    update={
                        "batch_id": existing.id,
                        "backup_id": existing.backup_id,
                        "skips": plan.records_read,
                        "creates": 0,
                        "updates": 0,
                        "idempotent_replay": True,
                    }
                )

            batch = LegacyImportBatch(
                source_type=source_type,
                source_name=plan.source_name,
                source_path=path.resolve(strict=False),
                source_checksum=plan.source_checksum,
                mode=LegacyImportMode.APPLY,
                status=LegacyImportStatus.COMPLETED,
                backup_id=backup.id,
                finished_at=_now(),
                records_read=plan.records_read,
                creates=plan.creates,
                updates=plan.updates,
                skips=plan.skips,
                conflicts=plan.conflicts,
                uncertain=plan.uncertain,
                rejected=plan.rejected,
                warnings=plan.warnings,
                reconciliation=plan.reconciliation,
            )
            repository.create_batch(batch)
            repository.create_source(
                batch_id=batch.id,
                source_type=source_type,
                source_path=path.resolve(strict=False),
                logical_name=plan.source_name,
                source_checksum=plan.source_checksum,
                size_bytes=path.stat().st_size if path.exists() else 0,
                record_count=plan.records_read,
                created_at=_now(),
            )
            applied_items = self._apply_records(
                connection,
                repository,
                batch,
                records,
                profile_key=profile_key,
                artifact_kind=artifact_kind,
            )
        return plan.model_copy(
            update={
                "batch_id": batch.id,
                "backup_id": backup.id,
                "items": tuple(applied_items),
            }
        )

    def verify(self, batch_id: UUID | str) -> dict[str, Any]:
        with self.database.read_connection() as connection:
            repository = LegacyImportRepository(connection)
            batch = repository.get_batch(batch_id)
            if batch is None:
                raise LegacyImportError(f"Legacy import batch not found: {batch_id}")
            items = repository.items_for_batch(batch_id)
            return {
                "batch_id": str(batch.id),
                "status": batch.status.value,
                "records_read": batch.records_read,
                "item_count": len(items),
                "foreign_key_check": [
                    dict(row) for row in connection.execute("PRAGMA foreign_key_check")
                ],
            }

    def reconcile(self, batch_id: UUID | str) -> dict[str, Any]:
        with self.database.read_connection() as connection:
            repository = LegacyImportRepository(connection)
            batch = repository.get_batch(batch_id)
            if batch is None:
                raise LegacyImportError(f"Legacy import batch not found: {batch_id}")
            items = repository.items_for_batch(batch_id)
            actions: dict[str, int] = {}
            types: dict[str, int] = {}
            for item in items:
                actions[item.action.value] = actions.get(item.action.value, 0) + 1
                types[item.item_type.value] = types.get(item.item_type.value, 0) + 1
            return {
                "batch_id": str(batch.id),
                "source_type": batch.source_type.value,
                "source_checksum": batch.source_checksum,
                "records_read": batch.records_read,
                "item_count": len(items),
                "actions": actions,
                "item_types": types,
                "warnings": list(batch.warnings),
            }

    def batches(self) -> list[LegacyImportBatch]:
        with self.database.read_connection() as connection:
            return LegacyImportRepository(connection).list_batches()

    def show(self, batch_id: UUID | str) -> tuple[LegacyImportBatch, list[LegacyImportItem]]:
        with self.database.read_connection() as connection:
            repository = LegacyImportRepository(connection)
            batch = repository.get_batch(batch_id)
            if batch is None:
                raise LegacyImportError(f"Legacy import batch not found: {batch_id}")
            return batch, repository.items_for_batch(batch_id)

    def inventory(self, root: Path | None = None) -> list[dict[str, Any]]:
        root = root or (self.settings.repo_root / "existing_projects")
        if not root.exists():
            return []
        patterns = ("*.csv", "*.json", "*.txt", "*.sql")
        results: list[dict[str, Any]] = []
        for pattern in patterns:
            for path in root.rglob(pattern):
                if ".venv" in path.parts or "__pycache__" in path.parts:
                    continue
                if path.name == ".env":
                    continue
                source_type = self._classify_path(path)
                if source_type:
                    results.append({
                        "path": str(path),
                        "source_type": source_type.value,
                        "size_bytes": path.stat().st_size,
                        "checksum": _hash_file(path),
                    })
        return sorted(results, key=lambda item: item["path"])

    def _records(
        self,
        source_type: LegacySourceType,
        path: Path,
        *,
        mysql_reader: LegacyMySQLReader | None = None,
    ) -> list[_ParsedRecord]:
        if source_type not in IMPORTABLE_SOURCE_TYPES:
            raise LegacyImportError(f"Unsupported legacy source type: {source_type}")
        if source_type is LegacySourceType.MYSQL_FIXTURE:
            reader = mysql_reader or FixtureMySQLReader({})
            rows = reader.read_table("jobs", limit=1000)
            return [
                _ParsedRecord(
                    item_key=f"mysql:jobs:{index}",
                    item_type=LegacyItemType.MYSQL_ROW,
                    source_identifier=_clean(row.get("job_id")),
                    content_checksum=_stable_hash(row),
                    confidence=0.5,
                    payload=dict(row),
                    warnings=("fixture mysql rows are reference-only",),
                )
                for index, row in enumerate(rows, start=1)
            ]
        if not path.exists():
            raise LegacyImportError(f"Legacy source path does not exist: {path}")
        if path.name == ".env":
            raise LegacyImportError("Legacy .env files must not be imported or read")
        if source_type in {
            LegacySourceType.ENGLISHJOBS_CSV,
            LegacySourceType.STATE_INTELLIGENCE_CSV,
        }:
            return self._csv_records(source_type, path)
        if source_type is LegacySourceType.SENT_JOBS_JSON:
            return self._sent_jobs_records(path)
        if source_type is LegacySourceType.MASTER_CV_JSON:
            return self._master_cv_records(path)
        if source_type is LegacySourceType.LEGACY_ARTIFACT:
            return self._artifact_records(path)
        raise AssertionError("Unhandled legacy source type")

    def _csv_records(
        self, source_type: LegacySourceType, path: Path
    ) -> list[_ParsedRecord]:
        required = (
            REQUIRED_STATE_COLUMNS
            if source_type is LegacySourceType.STATE_INTELLIGENCE_CSV
            else REQUIRED_ENGLISHJOBS_COLUMNS
        )
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or ())
            missing = sorted(required - columns)
            if missing:
                raise LegacyImportError(
                    f"{path.name} is missing required columns: {', '.join(missing)}"
                )
            records = []
            for index, row in enumerate(reader, start=1):
                if not _clean(row.get("job_title")):
                    records.append(_ParsedRecord(
                        item_key=f"{path.name}:row:{index}",
                        item_type=LegacyItemType.JOB,
                        source_identifier=None,
                        content_checksum=_stable_hash(row),
                        confidence=0,
                        payload=row,
                        warnings=("missing title; rejected",),
                    ))
                    continue
                identity = _englishjobs_identity(row)
                records.append(_ParsedRecord(
                    item_key=f"{path.name}:{identity}",
                    item_type=LegacyItemType.JOB,
                    source_identifier=identity,
                    content_checksum=_stable_hash(row),
                    confidence=0.9 if identity.startswith(("clickout_url:", "listing_url:")) else 0.75,
                    payload=row,
                ))
            return records

    def _sent_jobs_records(self, path: Path) -> list[_ParsedRecord]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise LegacyImportError("sent_jobs.json must contain a JSON list")
        records = []
        for index, value in enumerate(data, start=1):
            if not isinstance(value, str) or not value.strip():
                records.append(_ParsedRecord(
                    item_key=f"sent:{index}",
                    item_type=LegacyItemType.NOTIFICATION,
                    source_identifier=None,
                    content_checksum=_stable_hash(value),
                    confidence=0,
                    payload={"value": value},
                    warnings=("invalid sent-history value",),
                ))
                continue
            identifier = value.strip()
            records.append(_ParsedRecord(
                item_key=f"sent:{identifier}",
                item_type=LegacyItemType.NOTIFICATION,
                source_identifier=identifier,
                content_checksum=_hash_text(identifier),
                confidence=0.4,
                payload={"value": identifier},
                warnings=("requires current-job mapping before suppression",),
            ))
        return records

    def _master_cv_records(self, path: Path) -> list[_ParsedRecord]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise LegacyImportError("master_cv.json must contain a JSON object")
        return [_ParsedRecord(
            item_key=f"profile:{_stable_hash(data)}",
            item_type=LegacyItemType.PROFILE,
            source_identifier="master_cv.json",
            content_checksum=_stable_hash(data),
            confidence=1,
            payload=data,
            warnings=("candidate-private profile data",),
        )]

    def _artifact_records(self, path: Path) -> list[_ParsedRecord]:
        if path.suffix.casefold() != ".txt":
            raise LegacyImportError("Milestone 9 artifact import supports TXT files first")
        checksum = _hash_file(path)
        return [_ParsedRecord(
            item_key=f"artifact:{checksum}",
            item_type=LegacyItemType.ARTIFACT,
            source_identifier=path.name,
            content_checksum=checksum,
            confidence=1,
            payload={"path": str(path), "size_bytes": path.stat().st_size},
            warnings=("legacy artifact is non-authoritative",),
        )]

    def _plan(
        self,
        source_type: LegacySourceType,
        path: Path,
        records: list[_ParsedRecord],
        *,
        database_modified: bool,
    ) -> LegacyImportPlan:
        checksum = _hash_file(path) if path.exists() else _stable_hash([r.payload for r in records])
        creates = updates = skips = conflicts = uncertain = rejected = 0
        for record in records:
            if record.warnings and any("rejected" in warning for warning in record.warnings):
                rejected += 1
            elif record.item_type is LegacyItemType.NOTIFICATION:
                uncertain += 1
            elif record.item_type is LegacyItemType.MYSQL_ROW:
                skips += 1
            elif self._existing_target(source_type, record):
                updates += 1
            else:
                creates += 1
        warnings = self._plan_warnings(source_type, records)
        return LegacyImportPlan(
            source_type=source_type,
            source_name=path.name if path.name else source_type.value,
            source_path=path.resolve(strict=False) if path.exists() else path,
            source_checksum=checksum,
            records_read=len(records),
            creates=creates,
            updates=updates,
            skips=skips,
            conflicts=conflicts,
            uncertain=uncertain,
            rejected=rejected,
            warnings=warnings,
            items=tuple(
                LegacyImportItem(
                    batch_id=UUID("00000000-0000-0000-0000-000000000000"),
                    item_key=record.item_key,
                    item_type=record.item_type,
                    action=self._planned_action(source_type, record),
                    original_source_identifier=record.source_identifier,
                    source_checksum=checksum,
                    content_checksum=record.content_checksum,
                    mapping_confidence=record.confidence,
                    warnings=record.warnings,
                    summary=self._summary(record),
                )
                for record in records[:100]
            ),
            reconciliation={
                "legacy_scores_authoritative": False,
                "description_completeness": (
                    "snippet" if source_type in {
                        LegacySourceType.ENGLISHJOBS_CSV,
                        LegacySourceType.STATE_INTELLIGENCE_CSV,
                    } else None
                ),
                "network_requested": False,
            },
            database_modified=database_modified,
            network_requested=False,
        )

    def _apply_records(
        self,
        connection,
        repository: LegacyImportRepository,
        batch: LegacyImportBatch,
        records: list[_ParsedRecord],
        *,
        profile_key: str | None,
        artifact_kind: str | None,
    ) -> list[LegacyImportItem]:
        applied: list[LegacyImportItem] = []
        for record in records:
            action, target_table, target_id, warnings = self._apply_one(
                connection, repository, batch, record,
                profile_key=profile_key, artifact_kind=artifact_kind,
            )
            item = LegacyImportItem(
                batch_id=batch.id,
                item_key=record.item_key,
                item_type=record.item_type,
                action=action,
                original_source_identifier=record.source_identifier,
                source_checksum=batch.source_checksum,
                content_checksum=record.content_checksum,
                mapping_confidence=record.confidence,
                target_table=target_table,
                target_id=target_id,
                warnings=tuple(dict.fromkeys((*record.warnings, *warnings))),
                summary=self._summary(record),
            )
            repository.create_item(item)
            if target_table and target_id:
                repository.create_mapping(LegacyImportMapping(
                    item_id=item.id,
                    mapping_type=f"{record.item_type.value}_target",
                    target_table=target_table,
                    target_id=target_id,
                    confidence=record.confidence,
                    warnings=item.warnings,
                ))
            if record.item_type is LegacyItemType.NOTIFICATION:
                self._maybe_create_suppression(connection, repository, item, record)
            if record.item_type is LegacyItemType.ARTIFACT and target_id:
                repository.create_legacy_artifact(
                    import_item_id=item.id,
                    artifact_kind=_artifact_kind(Path(record.payload["path"]), artifact_kind).value,
                    original_path=Path(record.payload["path"]),
                    stored_path=Path(target_id),
                    content_hash=record.content_checksum or "",
                    size_bytes=int(record.payload["size_bytes"]),
                    created_at=_now(),
                )
            applied.append(item)
        return applied

    def _apply_one(
        self,
        connection,
        repository: LegacyImportRepository,
        batch: LegacyImportBatch,
        record: _ParsedRecord,
        *,
        profile_key: str | None,
        artifact_kind: str | None,
    ) -> tuple[LegacyImportAction, str | None, str | None, tuple[str, ...]]:
        if record.item_type is LegacyItemType.JOB:
            return self._apply_job(connection, record)
        if record.item_type is LegacyItemType.NOTIFICATION:
            return LegacyImportAction.UNCERTAIN, None, None, (
                "no notification suppression unless a current cluster maps exactly",
            )
        if record.item_type is LegacyItemType.PROFILE:
            profile = CandidateProfileRepository(connection).create_version(
                record.payload, profile_key=profile_key
            )
            return LegacyImportAction.CREATED, "candidate_profiles", str(profile.id), ()
        if record.item_type is LegacyItemType.ARTIFACT:
            stored = self._copy_artifact(Path(record.payload["path"]), batch.id, artifact_kind)
            return LegacyImportAction.CREATED, "legacy_artifacts", str(stored), (
                "legacy artifact is copied as non-authoritative",
            )
        return LegacyImportAction.SKIPPED, None, None, (
            "fixture MySQL row retained as reference metadata only",
        )

    def _apply_job(
        self, connection, record: _ParsedRecord
    ) -> tuple[LegacyImportAction, str | None, str | None, tuple[str, ...]]:
        if record.warnings and any("rejected" in warning for warning in record.warnings):
            return LegacyImportAction.REJECTED, None, None, record.warnings
        row = record.payload
        scraped_at = _parse_datetime(_clean(row.get("scraped_at")))
        location = _clean(row.get("location")) or _clean(row.get("city"))
        source_url = _clean(row.get("job_url"))
        job = Job(
            source=JobSource.ENGLISHJOBS,
            source_job_id=record.source_identifier,
            source_url=source_url,
            canonical_url=normalize_identity_url(source_url),
            title_raw=_clean(row.get("job_title")) or "Untitled legacy vacancy",
            title_normalized=_normalized(_clean(row.get("job_title"))) or "untitled legacy vacancy",
            company_raw=_clean(row.get("company")),
            company_normalized=_normalized(_clean(row.get("company"))),
            location_raw=location,
            city=_clean(row.get("city")) or _city_from_location(location),
            region=_clean(row.get("state_key")) or _clean(row.get("search_location")),
            country="Germany",
            first_seen_at=scraped_at,
            last_seen_at=scraped_at,
            created_at=scraped_at,
            updated_at=_now(),
        )
        jobs = JobRepository(connection)
        stored, created = jobs.upsert(job)
        snippet = _clean(row.get("description_snippet"))
        basis = snippet or f"missing:{stored.source_job_id}:legacy"
        description = JobDescription(
            job_id=stored.id,
            raw_text=snippet,
            normalized_text=_normalized(snippet),
            completeness=(
                DescriptionCompleteness.SNIPPET
                if snippet else DescriptionCompleteness.MISSING
            ),
            content_hash=_hash_text(basis),
            structured_data={
                "legacy_import": True,
                "legacy_scores_reference_only": {
                    "fit_score": _clean(row.get("fit_score")),
                    "fit_reason": _clean(row.get("fit_reason")),
                    "fit_category": _clean(row.get("fit_category")),
                    "recommended_action": _clean(row.get("recommended_action")),
                    "job_category": _clean(row.get("job_category")),
                },
                "legacy_row": {
                    key: value for key, value in row.items()
                    if key not in {"description_snippet"}
                },
            },
            fetched_at=scraped_at,
            created_at=_now(),
        )
        JobDescriptionRepository(connection).save_version(description)
        return (
            LegacyImportAction.CREATED if created else LegacyImportAction.UPDATED,
            "jobs",
            str(stored.id),
            ("description imported as snippet",),
        )

    def _maybe_create_suppression(
        self,
        connection,
        repository: LegacyImportRepository,
        item: LegacyImportItem,
        record: _ParsedRecord,
    ) -> None:
        identifier = record.source_identifier
        if not identifier:
            return
        rows = connection.execute(
            """SELECT jobs.id
            FROM jobs
            WHERE jobs.source_job_id = ?
               OR jobs.source_url LIKE ?
               OR jobs.canonical_url LIKE ?""",
            (identifier, f"%{identifier}%", f"%{identifier}%"),
        ).fetchall()
        if len(rows) != 1:
            return
        link = connection.execute(
            """SELECT cluster_id, algorithm_version
            FROM job_duplicate_links WHERE job_id = ?
            ORDER BY created_at DESC LIMIT 1""",
            (rows[0]["id"],),
        ).fetchone()
        if not link:
            return
        repository.create_notification_suppression(
            import_item_id=item.id,
            duplicate_cluster_id=link["cluster_id"],
            duplicate_algorithm_version=link["algorithm_version"],
            profile_id=None,
            channel="telegram",
            source_identifier=identifier,
            confidence=1,
            reason="exact legacy sent-history source identifier match",
            created_at=_now(),
        )

    def _copy_artifact(
        self, source: Path, batch_id: UUID, artifact_kind: str | None
    ) -> Path:
        kind = _artifact_kind(source, artifact_kind)
        checksum = _hash_file(source)
        target_dir = self.settings.cv_artifact_root / "legacy_imports" / str(batch_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{kind.value}-{checksum[:16]}{source.suffix.lower()}"
        if target.exists() and _hash_file(target) == checksum:
            return target
        if target.exists():
            target = target_dir / f"{kind.value}-{checksum}{source.suffix.lower()}"
        shutil.copy2(source, target)
        return target

    def _existing_target(
        self, source_type: LegacySourceType, record: _ParsedRecord
    ) -> bool:
        if record.item_type is not LegacyItemType.JOB or not record.source_identifier:
            return False
        if not self.database.path.exists():
            return False
        try:
            with self.database.read_connection() as connection:
                row = connection.execute(
                    "SELECT 1 FROM jobs WHERE source = 'englishjobs' AND source_job_id = ?",
                    (record.source_identifier,),
                ).fetchone()
                return row is not None
        except sqlite3.Error:
            return False

    def _planned_action(
        self, source_type: LegacySourceType, record: _ParsedRecord
    ) -> LegacyImportAction:
        if record.warnings and any("rejected" in warning for warning in record.warnings):
            return LegacyImportAction.REJECTED
        if record.item_type is LegacyItemType.NOTIFICATION:
            return LegacyImportAction.UNCERTAIN
        if record.item_type is LegacyItemType.MYSQL_ROW:
            return LegacyImportAction.SKIPPED
        return (
            LegacyImportAction.UPDATED
            if self._existing_target(source_type, record)
            else LegacyImportAction.CREATED
        )

    def _summary(self, record: _ParsedRecord) -> dict[str, Any]:
        if record.item_type is LegacyItemType.JOB:
            return {
                "title": _clean(record.payload.get("job_title")),
                "company": _clean(record.payload.get("company")),
                "description_completeness": "snippet",
                "legacy_scores_reference_only": True,
            }
        if record.item_type is LegacyItemType.NOTIFICATION:
            return {"source_identifier": record.source_identifier}
        if record.item_type is LegacyItemType.ARTIFACT:
            return {"path": Path(record.payload["path"]).name}
        if record.item_type is LegacyItemType.PROFILE:
            return {"top_level_keys": sorted(record.payload.keys())}
        return {"reference_only": True}

    def _plan_warnings(
        self, source_type: LegacySourceType, records: list[_ParsedRecord]
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if source_type in {
            LegacySourceType.ENGLISHJOBS_CSV,
            LegacySourceType.STATE_INTELLIGENCE_CSV,
        }:
            warnings.append("CSV descriptions are imported as snippets only")
            warnings.append("legacy scores are retained as reference metadata only")
        if source_type is LegacySourceType.SENT_JOBS_JSON:
            warnings.append("uncertain sent-history mappings do not suppress Telegram")
        if source_type is LegacySourceType.MASTER_CV_JSON:
            warnings.append("candidate profile import is explicit and versioned")
        if source_type is LegacySourceType.LEGACY_ARTIFACT:
            warnings.append("legacy artifacts are copied as non-authoritative")
        for record in records:
            warnings.extend(record.warnings)
        return tuple(dict.fromkeys(warnings))

    def _verify_backup_gate(self, backup: LegacyBackup | None) -> None:
        if backup is None:
            raise LegacyImportError("Apply requires an existing verified backup ID")
        if not backup.verified:
            raise LegacyImportError("Backup is not marked verified")
        if not backup.backup_path.exists():
            raise LegacyImportError("Backup file is missing")
        if _hash_file(backup.backup_path) != backup.sha256:
            raise LegacyImportError("Backup hash verification failed")
        if not self._verify_sqlite_file(backup.backup_path, backup.sha256):
            raise LegacyImportError("Backup SQLite integrity verification failed")

    @staticmethod
    def _verify_sqlite_file(path: Path, expected_hash: str) -> bool:
        if not path.exists() or _hash_file(path) != expected_hash:
            return False
        try:
            with sqlite3.connect(path) as connection:
                return connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        except sqlite3.Error:
            return False

    @staticmethod
    def _classify_path(path: Path) -> LegacySourceType | None:
        lower = path.name.lower()
        parts = {part.lower() for part in path.parts}
        if lower == "sent_jobs.json":
            return LegacySourceType.SENT_JOBS_JSON
        if lower == "master_cv.json":
            return LegacySourceType.MASTER_CV_JSON
        if lower.endswith(".txt") and ("outputs" in parts or "reports" in parts):
            return LegacySourceType.LEGACY_ARTIFACT
        if lower.endswith(".csv") and "englishjobs_scraper" in parts:
            return LegacySourceType.ENGLISHJOBS_CSV
        if lower.endswith(".csv") and "germany-english-job-intelligence" in parts:
            return LegacySourceType.STATE_INTELLIGENCE_CSV
        return None
