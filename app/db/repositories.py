"""Transaction-scoped SQLite repositories; callers own commit and rollback."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.domain.application import Application, ApplicationEvent
from app.domain.candidate import CandidateProfile
from app.domain.enums import ApplicationStatus, DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.domain.operations import CVArtifact, CollectionRun, Notification


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class JobRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create(self, job: Job) -> Job:
        self.connection.execute(
            """
            INSERT INTO jobs (
                id, source, source_job_id, source_url, canonical_url,
                title_raw, title_normalized, company_raw, company_normalized,
                location_raw, city, region, country, remote_mode,
                language_detected, language_confidence, explicit_german_requirement,
                published_at, expires_at, employment_type,
                first_seen_at, last_seen_at, active,
                first_seen_run_id, last_seen_run_id, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            self._values(job),
        )
        return job

    def get(self, job_id: UUID | str) -> Job | None:
        row = self.connection.execute(
            "SELECT * FROM jobs WHERE id = ?", (str(job_id),)
        ).fetchone()
        return self._from_row(row) if row else None

    def get_by_source_identity(
        self, source: JobSource, source_job_id: str
    ) -> Job | None:
        row = self.connection.execute(
            "SELECT * FROM jobs WHERE source = ? AND source_job_id = ?",
            (source.value, source_job_id),
        ).fetchone()
        return self._from_row(row) if row else None

    def update(self, job: Job) -> Job:
        cursor = self.connection.execute(
            """
            UPDATE jobs SET
                source = ?, source_job_id = ?, source_url = ?, canonical_url = ?,
                title_raw = ?, title_normalized = ?, company_raw = ?,
                company_normalized = ?, location_raw = ?, city = ?, region = ?,
                country = ?, remote_mode = ?, language_detected = ?,
                language_confidence = ?, explicit_german_requirement = ?,
                published_at = ?, expires_at = ?, employment_type = ?,
                first_seen_at = ?, last_seen_at = ?, active = ?,
                first_seen_run_id = ?, last_seen_run_id = ?, created_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            self._values(job)[1:] + (str(job.id),),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"Job not found: {job.id}")
        return job

    def upsert(self, job: Job) -> tuple[Job, bool]:
        existing = None
        if job.source_job_id:
            existing = self.get_by_source_identity(job.source, job.source_job_id)
        if existing is None:
            return self.create(job), True
        merged = job.model_copy(
            update={
                "id": existing.id,
                "first_seen_at": existing.first_seen_at,
                "first_seen_run_id": existing.first_seen_run_id,
                "created_at": existing.created_at,
                "updated_at": datetime.now(UTC),
            }
        )
        return self.update(merged), False

    @staticmethod
    def _values(job: Job) -> tuple[Any, ...]:
        return (
            str(job.id), job.source.value, job.source_job_id, job.source_url,
            job.canonical_url, job.title_raw, job.title_normalized,
            job.company_raw, job.company_normalized, job.location_raw, job.city,
            job.region, job.country, job.remote_mode, job.language_detected,
            job.language_confidence, job.explicit_german_requirement,
            _iso(job.published_at), _iso(job.expires_at), job.employment_type,
            _iso(job.first_seen_at), _iso(job.last_seen_at), int(job.active),
            str(job.first_seen_run_id) if job.first_seen_run_id else None,
            str(job.last_seen_run_id) if job.last_seen_run_id else None,
            _iso(job.created_at), _iso(job.updated_at),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"], source=row["source"], source_job_id=row["source_job_id"],
            source_url=row["source_url"], canonical_url=row["canonical_url"],
            title_raw=row["title_raw"], title_normalized=row["title_normalized"],
            company_raw=row["company_raw"], company_normalized=row["company_normalized"],
            location_raw=row["location_raw"], city=row["city"], region=row["region"],
            country=row["country"], remote_mode=row["remote_mode"],
            language_detected=row["language_detected"],
            language_confidence=row["language_confidence"],
            explicit_german_requirement=row["explicit_german_requirement"],
            published_at=_dt(row["published_at"]), expires_at=_dt(row["expires_at"]),
            employment_type=row["employment_type"],
            first_seen_at=_dt(row["first_seen_at"]), last_seen_at=_dt(row["last_seen_at"]),
            active=bool(row["active"]), first_seen_run_id=_uuid(row["first_seen_run_id"]),
            last_seen_run_id=_uuid(row["last_seen_run_id"]),
            created_at=_dt(row["created_at"]), updated_at=_dt(row["updated_at"]),
        )


class JobDescriptionRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create(self, description: JobDescription) -> JobDescription:
        self.connection.execute(
            """INSERT INTO job_descriptions
            (id, job_id, raw_text, normalized_text, completeness, content_hash,
             structured_data_json, fetched_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(description.id), str(description.job_id), description.raw_text,
                description.normalized_text, description.completeness.value,
                description.content_hash, _json(description.structured_data),
                _iso(description.fetched_at),
                _iso(description.created_at),
            ),
        )
        return description

    def save_version(self, description: JobDescription) -> tuple[JobDescription, bool]:
        existing = self.connection.execute(
            """SELECT * FROM job_descriptions
            WHERE job_id = ? AND content_hash = ?""",
            (str(description.job_id), description.content_hash),
        ).fetchone()
        if existing:
            return self._from_row(existing), False
        return self.create(description), True

    def latest_for_job(self, job_id: UUID | str) -> JobDescription | None:
        row = self.connection.execute(
            """SELECT * FROM job_descriptions WHERE job_id = ?
            ORDER BY fetched_at DESC, created_at DESC LIMIT 1""",
            (str(job_id),),
        ).fetchone()
        if not row:
            return None
        return self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> JobDescription:
        return JobDescription(
            id=row["id"], job_id=row["job_id"], raw_text=row["raw_text"],
            normalized_text=row["normalized_text"], completeness=row["completeness"],
            content_hash=row["content_hash"],
            structured_data=json.loads(row["structured_data_json"]),
            fetched_at=_dt(row["fetched_at"]),
            created_at=_dt(row["created_at"]),
        )


class CandidateProfileRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create_version(
        self, profile_data: dict[str, Any], *, profile_key: str | None = None
    ) -> CandidateProfile:
        if profile_key:
            row = self.connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM candidate_profiles WHERE profile_key = ?",
                (profile_key,),
            ).fetchone()
            version = int(row["version"]) + 1
            profile = CandidateProfile.from_master_cv(
                profile_data, version=version, profile_key=profile_key
            )
        else:
            provisional = CandidateProfile.from_master_cv(profile_data, version=1)
            row = self.connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM candidate_profiles WHERE profile_key = ?",
                (provisional.profile_key,),
            ).fetchone()
            profile = CandidateProfile.from_master_cv(
                profile_data,
                version=int(row["version"]) + 1,
                profile_key=provisional.profile_key,
            )
        self.connection.execute(
            "UPDATE candidate_profiles SET active = 0 WHERE profile_key = ? AND active = 1",
            (profile.profile_key,),
        )
        self.connection.execute(
            """INSERT INTO candidate_profiles
            (id, profile_key, version, display_name, profile_json, content_hash, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(profile.id), profile.profile_key, profile.version,
                profile.display_name, _json(profile.profile_data), profile.content_hash,
                int(profile.active), _iso(profile.created_at),
            ),
        )
        return profile

    def get(self, profile_id: UUID | str) -> CandidateProfile | None:
        row = self.connection.execute(
            "SELECT * FROM candidate_profiles WHERE id = ?", (str(profile_id),)
        ).fetchone()
        return self._from_row(row) if row else None

    def get_active(self, profile_key: str) -> CandidateProfile | None:
        row = self.connection.execute(
            "SELECT * FROM candidate_profiles WHERE profile_key = ? AND active = 1",
            (profile_key,),
        ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CandidateProfile:
        return CandidateProfile(
            id=row["id"], profile_key=row["profile_key"], version=row["version"],
            display_name=row["display_name"], profile_data=json.loads(row["profile_json"]),
            content_hash=row["content_hash"], active=bool(row["active"]),
            created_at=_dt(row["created_at"]),
        )


class ApplicationRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create(self, application: Application) -> Application:
        self.connection.execute(
            """INSERT INTO applications
            (id, job_id, profile_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(application.id), str(application.job_id), str(application.profile_id),
                application.status.value, _iso(application.created_at),
                _iso(application.updated_at),
            ),
        )
        return application

    def get(self, application_id: UUID | str) -> Application | None:
        row = self.connection.execute(
            "SELECT * FROM applications WHERE id = ?", (str(application_id),)
        ).fetchone()
        if not row:
            return None
        return Application(
            id=row["id"], job_id=row["job_id"], profile_id=row["profile_id"],
            status=row["status"], created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    def update_status(
        self,
        application_id: UUID,
        expected: ApplicationStatus,
        new_status: ApplicationStatus,
        updated_at: datetime,
    ) -> None:
        cursor = self.connection.execute(
            """UPDATE applications SET status = ?, updated_at = ?
            WHERE id = ? AND status = ?""",
            (new_status.value, _iso(updated_at), str(application_id), expected.value),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Application status changed concurrently")


class ApplicationEventRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create(self, event: ApplicationEvent) -> ApplicationEvent:
        self.connection.execute(
            """INSERT INTO application_events
            (id, application_id, from_status, to_status, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(event.id), str(event.application_id),
                event.from_status.value if event.from_status else None,
                event.to_status.value, event.reason, _iso(event.created_at),
            ),
        )
        return event

    def list_for_application(
        self, application_id: UUID | str
    ) -> list[ApplicationEvent]:
        rows = self.connection.execute(
            """SELECT * FROM application_events WHERE application_id = ?
            ORDER BY created_at, id""",
            (str(application_id),),
        ).fetchall()
        return [
            ApplicationEvent(
                id=row["id"], application_id=row["application_id"],
                from_status=row["from_status"], to_status=row["to_status"],
                reason=row["reason"], created_at=_dt(row["created_at"]),
            )
            for row in rows
        ]


class CollectionRunRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create(self, run: CollectionRun) -> CollectionRun:
        self.connection.execute(
            """INSERT INTO collection_runs
            (id, source, status, started_at, finished_at, jobs_found, jobs_stored,
             jobs_inserted, jobs_updated, queries_executed, pages_requested,
             search_requests_succeeded, search_requests_failed,
             detail_requests_succeeded, detail_requests_failed,
             error_count, error_summary, config_snapshot_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(run.id), run.source.value, run.status.value, _iso(run.started_at),
                _iso(run.finished_at), run.jobs_found, run.jobs_stored,
                run.jobs_inserted, run.jobs_updated, run.queries_executed,
                run.pages_requested, run.search_requests_succeeded,
                run.search_requests_failed, run.detail_requests_succeeded,
                run.detail_requests_failed,
                run.error_count, run.error_summary, _json(run.config_snapshot),
                _iso(run.created_at),
            ),
        )
        return run

    def update(self, run: CollectionRun) -> CollectionRun:
        cursor = self.connection.execute(
            """UPDATE collection_runs SET
                status = ?, started_at = ?, finished_at = ?, jobs_found = ?,
                jobs_stored = ?, jobs_inserted = ?, jobs_updated = ?,
                queries_executed = ?, pages_requested = ?,
                search_requests_succeeded = ?, search_requests_failed = ?,
                detail_requests_succeeded = ?, detail_requests_failed = ?,
                error_count = ?, error_summary = ?, config_snapshot_json = ?
            WHERE id = ?""",
            (
                run.status.value, _iso(run.started_at), _iso(run.finished_at),
                run.jobs_found, run.jobs_stored, run.jobs_inserted,
                run.jobs_updated, run.queries_executed, run.pages_requested,
                run.search_requests_succeeded, run.search_requests_failed,
                run.detail_requests_succeeded, run.detail_requests_failed,
                run.error_count, run.error_summary, _json(run.config_snapshot),
                str(run.id),
            ),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"Collection run not found: {run.id}")
        return run

    def get(self, run_id: UUID | str) -> CollectionRun | None:
        row = self.connection.execute(
            "SELECT * FROM collection_runs WHERE id = ?", (str(run_id),)
        ).fetchone()
        if not row:
            return None
        return CollectionRun(
            id=row["id"], source=row["source"], status=row["status"],
            started_at=_dt(row["started_at"]), finished_at=_dt(row["finished_at"]),
            jobs_found=row["jobs_found"], jobs_stored=row["jobs_stored"],
            jobs_inserted=row["jobs_inserted"], jobs_updated=row["jobs_updated"],
            queries_executed=row["queries_executed"], pages_requested=row["pages_requested"],
            search_requests_succeeded=row["search_requests_succeeded"],
            search_requests_failed=row["search_requests_failed"],
            detail_requests_succeeded=row["detail_requests_succeeded"],
            detail_requests_failed=row["detail_requests_failed"],
            error_count=row["error_count"], error_summary=row["error_summary"],
            config_snapshot=json.loads(row["config_snapshot_json"]),
            created_at=_dt(row["created_at"]),
        )


class NotificationRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create(self, notification: Notification) -> Notification:
        self.connection.execute(
            """INSERT INTO notifications
            (id, job_id, profile_id, channel, status, idempotency_key,
             remote_message_id, attempted_at, sent_at, error_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(notification.id), str(notification.job_id),
                str(notification.profile_id), notification.channel.value,
                notification.status.value, notification.idempotency_key,
                notification.remote_message_id, _iso(notification.attempted_at),
                _iso(notification.sent_at), notification.error_summary,
            ),
        )
        return notification


class CVArtifactRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create(self, artifact: CVArtifact) -> CVArtifact:
        self.connection.execute(
            """INSERT INTO cv_artifacts
            (id, job_id, profile_id, analysis_id, profile_version, artifact_format,
             source, path, validated, validation_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(artifact.id), str(artifact.job_id), str(artifact.profile_id),
                str(artifact.analysis_id) if artifact.analysis_id else None,
                artifact.profile_version, artifact.artifact_format.value,
                artifact.source.value, str(Path(artifact.path)), int(artifact.validated),
                artifact.validation_summary, _iso(artifact.created_at),
            ),
        )
        return artifact
