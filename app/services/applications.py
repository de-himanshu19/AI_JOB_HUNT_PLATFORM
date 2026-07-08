"""Validated application transitions with append-only event history."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from app.db.connection import Database
from app.db.repositories import (
    ApplicationEventRepository,
    ApplicationRepository,
    CVGenerationArtifactRepository,
    CandidateProfileRepository,
    JobRepository,
)
from app.domain.application import Application, ApplicationEvent, ApplicationPriority
from app.domain.enums import ApplicationStatus


ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.NEW: frozenset({
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.SKIPPED,
        ApplicationStatus.WITHDRAWN,
    }),
    ApplicationStatus.SHORTLISTED: frozenset({
        ApplicationStatus.CV_READY,
        ApplicationStatus.SKIPPED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }),
    ApplicationStatus.CV_READY: frozenset({
        ApplicationStatus.APPLIED,
        ApplicationStatus.SKIPPED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }),
    ApplicationStatus.APPLIED: frozenset({
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }),
    ApplicationStatus.INTERVIEW: frozenset({
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    }),
    ApplicationStatus.OFFER: frozenset({ApplicationStatus.WITHDRAWN}),
    ApplicationStatus.SKIPPED: frozenset({
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.WITHDRAWN,
    }),
    ApplicationStatus.REJECTED: frozenset(),
    ApplicationStatus.WITHDRAWN: frozenset(),
}

_STATUS_PATHS: dict[tuple[ApplicationStatus, ApplicationStatus], tuple[ApplicationStatus, ...]] = {
    (ApplicationStatus.NEW, ApplicationStatus.APPLIED): (
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.CV_READY,
        ApplicationStatus.APPLIED,
    ),
    (ApplicationStatus.NEW, ApplicationStatus.CV_READY): (
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.CV_READY,
    ),
    (ApplicationStatus.NEW, ApplicationStatus.REJECTED): (
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.REJECTED,
    ),
    (ApplicationStatus.NEW, ApplicationStatus.INTERVIEW): (
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.CV_READY,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
    ),
    (ApplicationStatus.NEW, ApplicationStatus.OFFER): (
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.CV_READY,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
    ),
    (ApplicationStatus.SHORTLISTED, ApplicationStatus.APPLIED): (
        ApplicationStatus.CV_READY,
        ApplicationStatus.APPLIED,
    ),
    (ApplicationStatus.SHORTLISTED, ApplicationStatus.INTERVIEW): (
        ApplicationStatus.CV_READY,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
    ),
    (ApplicationStatus.SHORTLISTED, ApplicationStatus.OFFER): (
        ApplicationStatus.CV_READY,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
    ),
    (ApplicationStatus.CV_READY, ApplicationStatus.INTERVIEW): (
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
    ),
    (ApplicationStatus.CV_READY, ApplicationStatus.OFFER): (
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
    ),
    (ApplicationStatus.APPLIED, ApplicationStatus.OFFER): (
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
    ),
}


class InvalidStatusTransition(ValueError):
    pass


class ApplicationService:
    def __init__(self, database: Database):
        self.database = database

    def create(self, job_id: UUID, profile_id: UUID) -> Application:
        with self.database.transaction() as connection:
            self._validate_profile_and_job(connection, profile_id, job_id)
            applications = ApplicationRepository(connection)
            cluster_id = applications.resolve_cluster_id(job_id)
            application = Application(
                job_id=job_id, profile_id=profile_id,
                logical_cluster_id=cluster_id,
            )
            event = ApplicationEvent(
                application_id=application.id,
                from_status=None,
                to_status=ApplicationStatus.NEW,
                event_type="created",
                reason="Application tracking created",
                created_at=application.created_at,
            )
            applications.create(application)
            ApplicationEventRepository(connection).create(event)
        return application

    def transition(
        self,
        application_id: UUID,
        to_status: ApplicationStatus,
        *,
        reason: str | None = None,
    ) -> Application:
        with self.database.transaction() as connection:
            applications = ApplicationRepository(connection)
            current = applications.get(application_id)
            if current is None:
                raise KeyError(f"Application not found: {application_id}")
            if to_status is current.status:
                return current
            if to_status not in ALLOWED_TRANSITIONS[current.status]:
                raise InvalidStatusTransition(
                    f"Transition {current.status.value} -> {to_status.value} is not allowed"
                )
            changed_at = datetime.now(UTC)
            applications.update_status(
                current.id, current.status, to_status, changed_at
            )
            ApplicationEventRepository(connection).create(
                ApplicationEvent(
                    application_id=current.id,
                    from_status=current.status,
                    to_status=to_status,
                    event_type="status_changed",
                    reason=reason,
                    note=reason,
                    created_at=changed_at,
                )
            )
            return current.model_copy(
                update={"status": to_status, "updated_at": changed_at}
            )

    def history(self, application_id: UUID) -> list[ApplicationEvent]:
        with self.database.read_connection() as connection:
            return ApplicationEventRepository(connection).list_for_application(
                application_id
            )

    def shortlist_job(
        self,
        profile_id: UUID | str,
        job_id: UUID | str,
        *,
        note: str | None = None,
        priority: ApplicationPriority | str | None = None,
    ) -> Application:
        application = self._get_or_create(profile_id, job_id, priority=priority)
        return self.set_status(
            application_id=application.id,
            status=ApplicationStatus.SHORTLISTED,
            note=note,
            priority=priority,
        )

    def track_job(
        self, profile_id: UUID | str, job_id: UUID | str
    ) -> tuple[Application, bool]:
        before = None
        with self.database.read_connection() as connection:
            applications = ApplicationRepository(connection)
            cluster_id = applications.resolve_cluster_id(job_id)
            before = (
                applications.get_by_profile_cluster(profile_id, cluster_id)
                if cluster_id else None
            ) or applications.get_by_profile_job(profile_id, job_id)
        application = self._get_or_create(profile_id, job_id)
        return application, before is not None

    def skip_job(
        self, profile_id: UUID | str, job_id: UUID | str, *, note: str | None = None
    ) -> Application:
        application = self._get_or_create(profile_id, job_id)
        return self.set_status(
            application_id=application.id,
            status=ApplicationStatus.SKIPPED,
            note=note,
        )

    def mark_cv_ready(
        self,
        profile_id: UUID | str,
        job_id: UUID | str,
        *,
        cv_artifact_id: UUID | str | None = None,
        note: str | None = None,
    ) -> Application:
        application = self._get_or_create(profile_id, job_id)
        return self.set_status(
            application_id=application.id,
            status=ApplicationStatus.CV_READY,
            note=note,
            cv_artifact_id=cv_artifact_id,
        )

    def mark_applied(
        self, profile_id: UUID | str, job_id: UUID | str, *, note: str | None = None
    ) -> Application:
        application = self._get_or_create(profile_id, job_id)
        return self.set_status(
            application_id=application.id,
            status=ApplicationStatus.APPLIED,
            note=note,
        )

    def set_status(
        self,
        *,
        status: ApplicationStatus | str,
        application_id: UUID | str | None = None,
        profile_id: UUID | str | None = None,
        job_id: UUID | str | None = None,
        note: str | None = None,
        priority: ApplicationPriority | str | None = None,
        cv_artifact_id: UUID | str | None = None,
    ) -> Application:
        target = ApplicationStatus(status)
        with self.database.transaction() as connection:
            application = self._resolve_application(
                connection, application_id=application_id,
                profile_id=profile_id, job_id=job_id, create=True,
            )
            if cv_artifact_id:
                self._validate_cv_artifact(connection, cv_artifact_id)
            priority_value = self._priority(priority)
            applications = ApplicationRepository(connection)
            events = ApplicationEventRepository(connection)
            current = application
            path = self._transition_path(current.status, target)
            changed_at = datetime.now(UTC)
            if not path:
                if note:
                    current = self._append_note(
                        applications, events, current, note, changed_at
                    )
                if priority is not None or cv_artifact_id is not None:
                    current = self._update_metadata(
                        applications, events, current, changed_at,
                        priority=priority_value,
                        cv_artifact_id=cv_artifact_id,
                        event_type="status_noop",
                        note=note,
                    )
                return current
            for index, step in enumerate(path):
                final = index == len(path) - 1
                old_status = current.status
                applications.update_status(current.id, old_status, step, changed_at)
                events.create(ApplicationEvent(
                    application_id=current.id,
                    from_status=old_status,
                    to_status=step,
                    event_type="status_changed",
                    reason=note if final else None,
                    note=note if final else None,
                    created_at=changed_at,
                ))
                current = current.model_copy(
                    update={"status": step, "updated_at": changed_at}
                )
            if note or priority is not None or cv_artifact_id is not None:
                current = self._update_metadata(
                    applications, events, current, changed_at,
                    priority=priority_value if priority is not None else None,
                    cv_artifact_id=cv_artifact_id,
                    append_note=note,
                    event_type=(
                        "cv_attached" if cv_artifact_id else
                        "priority_changed" if priority is not None else
                        "note_added"
                    ),
                    note=note,
                )
            return current

    def add_note(
        self,
        *,
        note: str,
        application_id: UUID | str | None = None,
        profile_id: UUID | str | None = None,
        job_id: UUID | str | None = None,
    ) -> Application:
        if not note.strip():
            raise ValueError("Application note cannot be empty")
        with self.database.transaction() as connection:
            application = self._resolve_application(
                connection, application_id=application_id,
                profile_id=profile_id, job_id=job_id, create=True,
            )
            return self._append_note(
                ApplicationRepository(connection),
                ApplicationEventRepository(connection),
                application,
                note.strip(),
                datetime.now(UTC),
            )

    def set_follow_up(
        self,
        *,
        follow_up_date: date | str,
        note: str | None = None,
        application_id: UUID | str | None = None,
        profile_id: UUID | str | None = None,
        job_id: UUID | str | None = None,
    ) -> Application:
        due = self._date(follow_up_date)
        with self.database.transaction() as connection:
            application = self._resolve_application(
                connection, application_id=application_id,
                profile_id=profile_id, job_id=job_id, create=True,
            )
            changed_at = datetime.now(UTC)
            notes = self._notes_with(application.notes, note)
            updated = ApplicationRepository(connection).update_metadata(
                application.id,
                follow_up_date=due.isoformat(),
                notes=notes,
                updated_at=changed_at,
            )
            ApplicationEventRepository(connection).create(ApplicationEvent(
                application_id=application.id,
                from_status=application.status,
                to_status=application.status,
                event_type="follow_up_changed",
                reason=note,
                note=note,
                created_at=changed_at,
            ))
            return updated

    def list_applications(
        self, profile_id: UUID | str, status: ApplicationStatus | str | None = None
    ) -> list[Application]:
        parsed_status = ApplicationStatus(status) if status else None
        with self.database.read_connection() as connection:
            return ApplicationRepository(connection).list(
                profile_id=profile_id, status=parsed_status
            )

    def list_due_followups(
        self, profile_id: UUID | str, due_on_or_before: date | str | None = None
    ) -> list[Application]:
        due = self._date(due_on_or_before or date.today())
        with self.database.read_connection() as connection:
            return ApplicationRepository(connection).list_due_followups(
                profile_id, due.isoformat()
            )

    def _get_or_create(
        self,
        profile_id: UUID | str,
        job_id: UUID | str,
        *,
        priority: ApplicationPriority | str | None = None,
    ) -> Application:
        with self.database.transaction() as connection:
            self._validate_profile_and_job(connection, profile_id, job_id)
            applications = ApplicationRepository(connection)
            cluster_id = applications.resolve_cluster_id(job_id)
            existing = (
                applications.get_by_profile_cluster(profile_id, cluster_id)
                if cluster_id else None
            ) or applications.get_by_profile_job(profile_id, job_id)
            if existing:
                if priority is not None:
                    return applications.update_metadata(
                        existing.id,
                        priority=self._priority(priority),
                        updated_at=datetime.now(UTC),
                    )
                return existing
            created_at = datetime.now(UTC)
            application = Application(
                job_id=job_id,
                profile_id=profile_id,
                logical_cluster_id=cluster_id,
                priority=self._priority(priority),
                created_at=created_at,
                updated_at=created_at,
            )
            applications.create(application)
            ApplicationEventRepository(connection).create(ApplicationEvent(
                application_id=application.id,
                from_status=None,
                to_status=ApplicationStatus.NEW,
                event_type="created",
                reason="Application tracking created",
                note="Application tracking created",
                created_at=created_at,
            ))
            return application

    def _resolve_application(
        self,
        connection,
        *,
        application_id: UUID | str | None,
        profile_id: UUID | str | None,
        job_id: UUID | str | None,
        create: bool,
    ) -> Application:
        applications = ApplicationRepository(connection)
        if application_id:
            application = applications.get(application_id)
            if application is None:
                raise KeyError(f"Application not found: {application_id}")
            return application
        if not profile_id or not job_id:
            raise ValueError("application_id or both profile_id and job_id are required")
        self._validate_profile_and_job(connection, profile_id, job_id)
        cluster_id = applications.resolve_cluster_id(job_id)
        existing = (
            applications.get_by_profile_cluster(profile_id, cluster_id)
            if cluster_id else None
        ) or applications.get_by_profile_job(profile_id, job_id)
        if existing or not create:
            if existing is None:
                raise KeyError(f"Application not found for job: {job_id}")
            return existing
        created_at = datetime.now(UTC)
        application = Application(
            job_id=job_id, profile_id=profile_id, logical_cluster_id=cluster_id,
            created_at=created_at, updated_at=created_at,
        )
        applications.create(application)
        ApplicationEventRepository(connection).create(ApplicationEvent(
            application_id=application.id,
            from_status=None,
            to_status=ApplicationStatus.NEW,
            event_type="created",
            reason="Application tracking created",
            note="Application tracking created",
            created_at=created_at,
        ))
        return application

    @staticmethod
    def _transition_path(
        current: ApplicationStatus, target: ApplicationStatus
    ) -> tuple[ApplicationStatus, ...]:
        if current is target:
            return ()
        if target in ALLOWED_TRANSITIONS[current]:
            return (target,)
        path = _STATUS_PATHS.get((current, target))
        if path:
            return path
        if target in {
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.SKIPPED,
        } and target in ALLOWED_TRANSITIONS[current]:
            return (target,)
        raise InvalidStatusTransition(
            f"Transition {current.value} -> {target.value} is not allowed"
        )

    @staticmethod
    def _priority(value: ApplicationPriority | str | None) -> ApplicationPriority | None:
        return ApplicationPriority(value) if value else None

    @staticmethod
    def _date(value: date | str) -> date:
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("follow_up_date must use YYYY-MM-DD") from error

    @staticmethod
    def _notes_with(existing: str, note: str | None) -> str:
        if not note or not note.strip():
            return existing
        note = note.strip()
        lines = [line.strip() for line in existing.splitlines() if line.strip()]
        if note not in lines:
            lines.append(note)
        return "\n".join(lines)

    def _append_note(
        self,
        applications: ApplicationRepository,
        events: ApplicationEventRepository,
        application: Application,
        note: str,
        changed_at: datetime,
    ) -> Application:
        updated = applications.update_metadata(
            application.id,
            notes=self._notes_with(application.notes, note),
            updated_at=changed_at,
        )
        events.create(ApplicationEvent(
            application_id=application.id,
            from_status=application.status,
            to_status=application.status,
            event_type="note_added",
            reason=note,
            note=note,
            created_at=changed_at,
        ))
        return updated

    def _update_metadata(
        self,
        applications: ApplicationRepository,
        events: ApplicationEventRepository,
        application: Application,
        changed_at: datetime,
        *,
        priority: ApplicationPriority | None = None,
        cv_artifact_id: UUID | str | None = None,
        append_note: str | None = None,
        event_type: str,
        note: str | None,
    ) -> Application:
        metadata: dict[str, object] = {
            "notes": self._notes_with(application.notes, append_note),
            "updated_at": changed_at,
        }
        if priority is not None:
            metadata["priority"] = priority
        if cv_artifact_id is not None:
            metadata["cv_artifact_id"] = cv_artifact_id
        updated = applications.update_metadata(application.id, **metadata)
        if event_type != "note_added":
            events.create(ApplicationEvent(
                application_id=application.id,
                from_status=application.status,
                to_status=application.status,
                event_type=event_type,
                reason=note,
                note=note,
                created_at=changed_at,
            ))
        return updated

    @staticmethod
    def _validate_profile_and_job(connection, profile_id, job_id) -> None:
        if CandidateProfileRepository(connection).get(profile_id) is None:
            raise KeyError(f"Candidate profile not found: {profile_id}")
        if JobRepository(connection).get(job_id) is None:
            raise KeyError(f"Job not found: {job_id}")

    @staticmethod
    def _validate_cv_artifact(connection, cv_artifact_id) -> None:
        if CVGenerationArtifactRepository(connection).get(cv_artifact_id) is None:
            raise KeyError(f"CV artifact not found: {cv_artifact_id}")
