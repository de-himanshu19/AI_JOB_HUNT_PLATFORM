from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

import app.cli as cli
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


def test_shortlist_is_idempotent_and_persists_crm_metadata(
    database: Database, master_cv_data: dict
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    service = ApplicationService(database)

    first = service.shortlist_job(
        profile.id, job.id, priority="high", note="Top ranked match"
    )
    second = service.shortlist_job(
        profile.id, job.id, priority="high", note="Top ranked match"
    )
    listed = service.list_applications(profile.id, ApplicationStatus.SHORTLISTED)

    assert second.id == first.id
    assert len(listed) == 1
    assert listed[0].priority.value == "high"
    assert "Top ranked match" in listed[0].notes
    assert listed[0].status is ApplicationStatus.SHORTLISTED


def test_application_tracking_resolves_logical_cluster(
    database: Database, master_cv_data: dict
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    cluster_id = "11111111-1111-4111-8111-111111111111"
    with database.transaction() as connection:
        connection.execute(
            """INSERT INTO duplicate_clusters
            (id, representative_job_id, algorithm_version, created_at, updated_at)
            VALUES (?, ?, 'm4-dedup-v1', '2026-07-09', '2026-07-09')""",
            (cluster_id, str(job.id)),
        )
        connection.execute(
            """INSERT INTO job_duplicate_links
            (id, job_id, cluster_id, algorithm_version, match_method, confidence,
             reasons_json, reviewed, created_at)
            VALUES ('link-1', ?, ?, 'm4-dedup-v1', 'singleton', 1,
                    '[]', 0, '2026-07-09')""",
            (str(job.id), cluster_id),
        )

    application = ApplicationService(database).shortlist_job(profile.id, job.id)

    assert str(application.logical_cluster_id) == cluster_id


def test_due_followups_and_cv_ready_attachment(
    database: Database, master_cv_data: dict
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    artifact_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    with database.transaction() as connection:
        connection.execute(
            """INSERT INTO cv_generation_artifacts (
                id, job_id, logical_cluster_id, description_id,
                description_content_hash, description_completeness, profile_id,
                profile_version, profile_content_hash, analysis_id,
                analyzer_version, rules_version, generator_version,
                formatter_version, generation_mode, generation_identity,
                artifact_format, source, parent_rule_based_artifact_id,
                artifact_path, evidence_report_path, content_hash,
                evidence_report_hash, provider, model, prompt_version,
                ai_generated_at, validated, validation_result_json, created_at
            ) VALUES (
                ?, NULL, NULL, NULL, ?, 'full', ?, 1, ?, NULL,
                'analyzer', 'rules', 'generator', 'formatter',
                'manual_jd', ?, 'flowcv_txt', 'rule_based',
                NULL, 'cv.txt', 'evidence.json', ?, ?, NULL, NULL, NULL,
                NULL, 1, '{}', '2026-07-09'
            )""",
            (
                artifact_id, "d" * 64, str(profile.id), "p" * 64,
                "g" * 64, "c" * 64, "e" * 64,
            ),
        )
    service = ApplicationService(database)
    ready = service.mark_cv_ready(
        profile.id, job.id, cv_artifact_id=artifact_id, note="FlowCV exported"
    )
    service.set_follow_up(
        profile_id=profile.id,
        job_id=job.id,
        follow_up_date=date(2026, 7, 15),
        note="Follow up after one week",
    )

    due = service.list_due_followups(profile.id, "2026-07-15")

    assert ready.status is ApplicationStatus.CV_READY
    assert str(ready.cv_artifact_id) == artifact_id
    assert due[0].id == ready.id
    assert due[0].follow_up_date == date(2026, 7, 15)


def test_invalid_priority_date_and_missing_cv_fail_clearly(
    database: Database, master_cv_data: dict
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    service = ApplicationService(database)

    with pytest.raises(ValueError, match="urgent"):
        service.shortlist_job(profile.id, job.id, priority="urgent")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        service.set_follow_up(
            profile_id=profile.id, job_id=job.id, follow_up_date="07/15/2026"
        )
    with pytest.raises(KeyError, match="CV artifact not found"):
        service.mark_cv_ready(profile.id, job.id, cv_artifact_id="missing")


def test_validated_ai_artifact_can_attach_and_invalid_artifact_is_rejected(
    database: Database, master_cv_data: dict
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    parent_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    ai_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    invalid_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    with database.transaction() as connection:
        for artifact_id, source, parent, validated in (
            (parent_id, "rule_based", None, 1),
            (ai_id, "ai_polished", parent_id, 1),
            (invalid_id, "ai_polished", parent_id, 0),
        ):
            connection.execute(
                """INSERT INTO cv_generation_artifacts (
                    id, job_id, logical_cluster_id, description_id,
                    description_content_hash, description_completeness, profile_id,
                    profile_version, profile_content_hash, analysis_id,
                    analyzer_version, rules_version, generator_version,
                    formatter_version, generation_mode, generation_identity,
                    artifact_format, source, parent_rule_based_artifact_id,
                    artifact_path, evidence_report_path, content_hash,
                    evidence_report_hash, provider, model, prompt_version,
                    ai_generated_at, validated, validation_result_json, created_at
                ) VALUES (
                    ?, NULL, NULL, NULL, ?, 'full', ?, 1, ?, NULL,
                    'analyzer', 'rules', 'generator', 'formatter',
                    'manual_jd', ?, 'flowcv_txt', ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, '{"valid": true}', '2026-07-09'
                )""",
                (
                    artifact_id,
                    "d" * 64,
                    str(profile.id),
                    profile.content_hash,
                    artifact_id.replace("-", "")[:64].ljust(64, "0"),
                    source,
                    parent,
                    f"{artifact_id}.txt",
                    f"{artifact_id}.evidence.txt",
                    "c" * 64,
                    "e" * 64,
                    "openai_compatible" if source == "ai_polished" else None,
                    "test-model" if source == "ai_polished" else None,
                    "m13-cv-polish-v1" if source == "ai_polished" else None,
                    "2026-07-09T00:00:00+00:00"
                    if source == "ai_polished" else None,
                    validated,
                ),
            )

    service = ApplicationService(database)
    ready = service.mark_cv_ready(profile.id, job.id, cv_artifact_id=ai_id)

    assert ready.status is ApplicationStatus.CV_READY
    assert str(ready.cv_artifact_id) == ai_id
    with pytest.raises(ValueError, match="validated CV artifacts"):
        service.mark_cv_ready(profile.id, job.id, cv_artifact_id=invalid_id)


def test_applications_cli_shortlist_list_due_and_history(
    monkeypatch, settings, database: Database, master_cv_data: dict, capsys
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main([
        "applications", "shortlist",
        "--profile-id", str(profile.id),
        "--job-id", str(job.id),
        "--priority", "high",
        "--note", "CLI top match",
    ]) == 0
    shortlist_output = json.loads(capsys.readouterr().out)
    assert shortlist_output["current_status"] == "shortlisted"
    assert shortlist_output["priority"] == "high"

    assert cli.main([
        "applications", "follow-up",
        "--profile-id", str(profile.id),
        "--job-id", str(job.id),
        "--date", "2026-07-15",
    ]) == 0
    capsys.readouterr()
    assert cli.main([
        "applications", "due",
        "--profile-id", str(profile.id),
        "--date", "2026-07-15",
    ]) == 0
    due_output = json.loads(capsys.readouterr().out)
    assert due_output[0]["id"] == shortlist_output["id"]

    assert cli.main([
        "applications", "history",
        "--profile-id", str(profile.id),
        "--job-id", str(job.id),
    ]) == 0
    history = json.loads(capsys.readouterr().out)
    assert history[0]["event_type"] == "created"
    assert history[-1]["new_status"] == "shortlisted"


def test_applications_cli_invalid_date_fails_clearly(
    monkeypatch, settings, database: Database, master_cv_data: dict
) -> None:
    job, profile = _setup_entities(database, master_cv_data)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        cli.main([
            "applications", "follow-up",
            "--profile-id", str(profile.id),
            "--job-id", str(job.id),
            "--date", "15-07-2026",
        ])
