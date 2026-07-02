"""Validated application transitions with append-only event history."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.db.connection import Database
from app.db.repositories import ApplicationEventRepository, ApplicationRepository
from app.domain.application import Application, ApplicationEvent
from app.domain.enums import ApplicationStatus


ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.NEW: frozenset({
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.SKIPPED,
    }),
    ApplicationStatus.SHORTLISTED: frozenset({
        ApplicationStatus.CV_READY,
        ApplicationStatus.SKIPPED,
        ApplicationStatus.REJECTED,
    }),
    ApplicationStatus.CV_READY: frozenset({
        ApplicationStatus.APPLIED,
        ApplicationStatus.SKIPPED,
        ApplicationStatus.REJECTED,
    }),
    ApplicationStatus.APPLIED: frozenset({
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
    }),
    ApplicationStatus.INTERVIEW: frozenset({ApplicationStatus.REJECTED}),
    ApplicationStatus.SKIPPED: frozenset({ApplicationStatus.SHORTLISTED}),
    ApplicationStatus.REJECTED: frozenset(),
}


class InvalidStatusTransition(ValueError):
    pass


class ApplicationService:
    def __init__(self, database: Database):
        self.database = database

    def create(self, job_id: UUID, profile_id: UUID) -> Application:
        application = Application(job_id=job_id, profile_id=profile_id)
        event = ApplicationEvent(
            application_id=application.id,
            from_status=None,
            to_status=ApplicationStatus.NEW,
            reason="Application tracking created",
            created_at=application.created_at,
        )
        with self.database.transaction() as connection:
            ApplicationRepository(connection).create(application)
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
                    reason=reason,
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

