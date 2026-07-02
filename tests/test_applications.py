from __future__ import annotations

import sqlite3

import pytest

from app.db.connection import Database
from app.db.repositories import (
    ApplicationRepository,
    CVArtifactRepository,
    CandidateProfileRepository,
    JobRepository,
)
from app.domain.enums import ApplicationStatus, JobSource
from app.domain.job import Job
from app.domain.operations import CVArtifact
from app.services.applications import ApplicationService, InvalidStatusTransition


def _setup_entities(database: Database, master_cv_data: dict):
    with database.transaction() as connection:
        job = JobRepository(connection).create(
            Job(
                source=JobSource.MANUAL,
                title_raw="Data Analyst",
                title_normalized="data analyst",
            )
        )
        profile = CandidateProfileRepository(connection).create_version(
            master_cv_data, profile_key="candidate"
        )
    return job, profile


def test_allowed_application_lifecycle_and_immutable_history(
    database: Database, master_cv_data: dict
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    service = ApplicationService(database)
    application = service.create(job.id, profile.id)

    for status in (
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.CV_READY,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
    ):
        application = service.transition(application.id, status, reason="fixture")

    assert application.status is ApplicationStatus.REJECTED
    history = service.history(application.id)
    assert [event.to_status for event in history] == [
        ApplicationStatus.NEW,
        ApplicationStatus.SHORTLISTED,
        ApplicationStatus.CV_READY,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
    ]

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with database.transaction() as connection:
            connection.execute(
                "UPDATE application_events SET reason = 'tampered' WHERE id = ?",
                (str(history[0].id),),
            )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with database.transaction() as connection:
            connection.execute(
                "DELETE FROM application_events WHERE id = ?",
                (str(history[0].id),),
            )


def test_invalid_transition_cannot_mark_job_applied(
    database: Database, master_cv_data: dict
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    service = ApplicationService(database)
    application = service.create(job.id, profile.id)

    with pytest.raises(InvalidStatusTransition, match="new -> applied"):
        service.transition(application.id, ApplicationStatus.APPLIED)
    assert service.history(application.id)[-1].to_status is ApplicationStatus.NEW


def test_skipped_application_can_be_reopened(
    database: Database, master_cv_data: dict
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    service = ApplicationService(database)
    application = service.create(job.id, profile.id)
    service.transition(application.id, ApplicationStatus.SKIPPED)
    reopened = service.transition(application.id, ApplicationStatus.SHORTLISTED)
    assert reopened.status is ApplicationStatus.SHORTLISTED


@pytest.mark.parametrize(
    ("path_to_source", "target"),
    [
        ([], ApplicationStatus.SHORTLISTED),
        ([], ApplicationStatus.SKIPPED),
        ([ApplicationStatus.SHORTLISTED], ApplicationStatus.CV_READY),
        ([ApplicationStatus.SHORTLISTED], ApplicationStatus.SKIPPED),
        ([ApplicationStatus.SHORTLISTED], ApplicationStatus.REJECTED),
        (
            [ApplicationStatus.SHORTLISTED, ApplicationStatus.CV_READY],
            ApplicationStatus.APPLIED,
        ),
        (
            [ApplicationStatus.SHORTLISTED, ApplicationStatus.CV_READY],
            ApplicationStatus.SKIPPED,
        ),
        (
            [ApplicationStatus.SHORTLISTED, ApplicationStatus.CV_READY],
            ApplicationStatus.REJECTED,
        ),
        (
            [
                ApplicationStatus.SHORTLISTED,
                ApplicationStatus.CV_READY,
                ApplicationStatus.APPLIED,
            ],
            ApplicationStatus.INTERVIEW,
        ),
        (
            [
                ApplicationStatus.SHORTLISTED,
                ApplicationStatus.CV_READY,
                ApplicationStatus.APPLIED,
            ],
            ApplicationStatus.REJECTED,
        ),
        (
            [
                ApplicationStatus.SHORTLISTED,
                ApplicationStatus.CV_READY,
                ApplicationStatus.APPLIED,
                ApplicationStatus.INTERVIEW,
            ],
            ApplicationStatus.REJECTED,
        ),
        (
            [ApplicationStatus.SKIPPED],
            ApplicationStatus.SHORTLISTED,
        ),
    ],
)
def test_every_approved_transition_is_accepted(
    database: Database,
    master_cv_data: dict,
    path_to_source: list[ApplicationStatus],
    target: ApplicationStatus,
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    service = ApplicationService(database)
    application = service.create(job.id, profile.id)
    for status in path_to_source:
        application = service.transition(application.id, status)
    application = service.transition(application.id, target)
    assert application.status is target


def test_cv_artifact_creation_does_not_change_application_status(
    database: Database, master_cv_data: dict, tmp_path
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    service = ApplicationService(database)
    application = service.create(job.id, profile.id)
    application = service.transition(application.id, ApplicationStatus.SHORTLISTED)

    with database.transaction() as connection:
        CVArtifactRepository(connection).create(
            CVArtifact(
                job_id=job.id,
                profile_id=profile.id,
                profile_version=profile.version,
                path=tmp_path / "tailored_cv.txt",
                validated=True,
            )
        )

    with database.read_connection() as connection:
        stored = ApplicationRepository(connection).get(application.id)
        assert stored.status is ApplicationStatus.SHORTLISTED
