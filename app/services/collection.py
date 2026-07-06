"""Source-independent collection orchestration and SQLite persistence."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.connection import Database
from app.db.repositories import (
    CollectionRunRepository,
    JobDescriptionRepository,
    JobRepository,
)
from app.domain.enums import CollectionRunStatus, JobSource
from app.domain.operations import CollectionRun
from app.sources.base import (
    CollectionError,
    CollectionRequest,
    CollectionResult,
    JobSourceAdapter,
    SourceRunStatus,
)


class CollectionExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID | None = None
    source_result: CollectionResult
    jobs_inserted: int = Field(default=0, ge=0)
    jobs_updated: int = Field(default=0, ge=0)
    description_versions_inserted: int = Field(default=0, ge=0)
    dry_run: bool = False


STATUS_MAP = {
    SourceRunStatus.STARTED: CollectionRunStatus.RUNNING,
    SourceRunStatus.COMPLETED: CollectionRunStatus.COMPLETED,
    SourceRunStatus.COMPLETED_WITH_ERRORS: CollectionRunStatus.PARTIAL,
    SourceRunStatus.FAILED: CollectionRunStatus.FAILED,
}


class CollectionService:
    def __init__(self, database: Database):
        self.database = database

    def execute(
        self,
        adapter: JobSourceAdapter,
        request: CollectionRequest,
        *,
        source: JobSource,
        dry_run: bool = False,
    ) -> CollectionExecutionReport:
        if dry_run:
            try:
                result = adapter.collect(request)
            except Exception as error:
                result = CollectionResult(
                    status=SourceRunStatus.FAILED,
                    errors=[
                        CollectionError(
                            operation="collection_service",
                            message=str(error),
                            error_type=type(error).__name__,
                            retriable=False,
                        )
                    ],
                )
            inserted, updated = self._dry_run_counts(result)
            return CollectionExecutionReport(
                source_result=result,
                jobs_inserted=inserted,
                jobs_updated=updated,
                dry_run=True,
            )

        started_at = datetime.now(UTC)
        run = CollectionRun(
            source=source,
            status=CollectionRunStatus.RUNNING,
            started_at=started_at,
            config_snapshot={
                "queries": list(request.queries),
                "states": list(request.states),
                "location": request.location,
                "published_within_days": request.published_within_days,
                "max_pages": request.max_pages,
                "page_size": request.page_size,
            },
        )
        with self.database.transaction() as connection:
            CollectionRunRepository(connection).create(run)

        result: CollectionResult | None = None
        inserted = 0
        updated = 0
        description_versions = 0
        try:
            result = adapter.collect(request)
            if result.status is not SourceRunStatus.FAILED:
                inserted, updated, description_versions = self._persist_result(
                    result, run.id, started_at
                )
        except Exception as error:
            service_error = CollectionError(
                operation="collection_service",
                message=str(error),
                error_type=type(error).__name__,
                retriable=False,
            )
            if result is None:
                result = CollectionResult(
                    status=SourceRunStatus.FAILED, errors=[service_error]
                )
            else:
                result.errors.append(service_error)
                result.status = SourceRunStatus.FAILED

        final_status = STATUS_MAP[result.status]
        if result.status is not SourceRunStatus.FAILED and result.errors:
            final_status = CollectionRunStatus.PARTIAL
        finished_run = run.model_copy(
            update={
                "status": final_status,
                "finished_at": datetime.now(UTC),
                "jobs_found": len(result.jobs),
                "jobs_stored": inserted + updated,
                "jobs_inserted": inserted,
                "jobs_updated": updated,
                "queries_executed": result.queries_executed,
                "pages_requested": result.pages_requested,
                "search_requests_succeeded": result.search_requests_succeeded,
                "search_requests_failed": result.search_requests_failed,
                "detail_requests_succeeded": result.detail_requests_succeeded,
                "detail_requests_failed": result.detail_requests_failed,
                "error_count": len(result.errors),
                "error_summary": self._error_summary(result.errors),
            }
        )
        with self.database.transaction() as connection:
            CollectionRunRepository(connection).update(finished_run)

        return CollectionExecutionReport(
            run_id=run.id,
            source_result=result,
            jobs_inserted=inserted,
            jobs_updated=updated,
            description_versions_inserted=description_versions,
            dry_run=False,
        )

    def _persist_result(
        self,
        result: CollectionResult,
        run_id: UUID,
        observed_at: datetime,
    ) -> tuple[int, int, int]:
        inserted = 0
        updated = 0
        description_versions = 0
        with self.database.transaction() as connection:
            jobs = JobRepository(connection)
            descriptions = JobDescriptionRepository(connection)
            for collected in result.jobs:
                existing = jobs.get_by_source_identity(
                    collected.job.source, collected.job.source_job_id or ""
                )
                job = collected.job.model_copy(
                    update={
                        "first_seen_at": (
                            existing.first_seen_at if existing else observed_at
                        ),
                        "last_seen_at": observed_at,
                        "first_seen_run_id": (
                            existing.first_seen_run_id if existing else run_id
                        ),
                        "last_seen_run_id": run_id,
                        "created_at": (
                            existing.created_at if existing else observed_at
                        ),
                        "updated_at": observed_at,
                    }
                )
                stored, created = jobs.upsert(job)
                inserted += int(created)
                updated += int(not created)
                description = collected.description.model_copy(
                    update={"job_id": stored.id}
                )
                _, description_created = descriptions.save_version(description)
                description_versions += int(description_created)
        return inserted, updated, description_versions

    def _dry_run_counts(self, result: CollectionResult) -> tuple[int, int]:
        if not self.database.path.exists():
            return len(result.jobs), 0
        inserted = 0
        updated = 0
        connection: sqlite3.Connection | None = None
        try:
            uri = self.database.path.resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            for collected in result.jobs:
                row = connection.execute(
                    "SELECT 1 FROM jobs WHERE source = ? AND source_job_id = ?",
                    (
                        collected.job.source.value,
                        collected.job.source_job_id,
                    ),
                ).fetchone()
                if row:
                    updated += 1
                else:
                    inserted += 1
        except sqlite3.Error:
            return len(result.jobs), 0
        finally:
            if connection is not None:
                connection.close()
        return inserted, updated

    @staticmethod
    def _error_summary(errors: list[CollectionError]) -> str | None:
        if not errors:
            return None
        summary = " | ".join(
            f"{error.operation}:{error.error_type}:{error.message}"
            for error in errors[:20]
        )
        return summary[:4000]
