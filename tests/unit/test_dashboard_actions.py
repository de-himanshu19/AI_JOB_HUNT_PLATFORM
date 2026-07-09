from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings_from_mapping
from app.dashboard.actions import ConfirmationRequired, DashboardActions
from app.db.connection import Database
from app.db.migrations import migrate
from app.db.repositories import CandidateProfileRepository, JobRepository
from app.db.repositories import ApplicationRepository, JobDescriptionRepository
from app.domain.enums import ApplicationStatus, DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.services.applications import InvalidStatusTransition
from app.services.deduplication import DeduplicationService
from tests.integration.test_deduplication_persistence import _seed as seed_duplicates
from tests.notification_helpers import seed_ranked_vacancies


ROOT = Path(__file__).parents[2]


def _context(tmp_path):
    settings = settings_from_mapping({
        "JOBHUNT_DATABASE_PATH": "dashboard-actions.sqlite3",
        "FIT_RULES_PATH": str(ROOT / "config" / "fit_rules.json"),
        "DEDUP_COMPANY_ALIASES_PATH": str(ROOT / "config" / "company_aliases.json"),
        "TELEGRAM_ENABLED": "false",
        "AI_PROVIDER": "rule_based",
    }, root=tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    profile_data = json.loads(
        (ROOT / "tests/fixtures/fit_analysis/candidate_profile.json").read_text(
            encoding="utf-8"
        )
    )
    with database.transaction() as connection:
        profile = CandidateProfileRepository(connection).create_version(
            profile_data, profile_key="dashboard-actions"
        )
        job = JobRepository(connection).create(Job(
            source=JobSource.MANUAL, title_raw="Analyst", title_normalized="analyst"
        ))
    return settings, database, profile, job


def test_application_actions_use_existing_transition_rules_and_are_idempotent(tmp_path) -> None:
    settings, database, profile, job = _context(tmp_path)
    actions = DashboardActions(database, settings)
    application, reused = actions.start_tracking(job.id, profile.id)
    same, second_reused = actions.start_tracking(job.id, profile.id)
    assert not reused and second_reused and same.id == application.id
    assert actions.allowed_transitions(application.id) == (
        "shortlisted", "skipped", "withdrawn"
    )
    with pytest.raises(InvalidStatusTransition):
        actions.transition_application(application.id, ApplicationStatus.APPLIED.value)
    changed = actions.transition_application(
        application.id, ApplicationStatus.SHORTLISTED.value, reason="reviewed in dashboard"
    )
    assert changed.status is ApplicationStatus.SHORTLISTED


def test_live_actions_remain_disabled_without_configuration_and_confirmation(tmp_path) -> None:
    settings, database, profile, _ = _context(tmp_path)
    actions = DashboardActions(database, settings)
    with pytest.raises(ConfirmationRequired, match="TELEGRAM_ENABLED"):
        actions.send_notifications(profile.id, confirmation="SEND TELEGRAM")
    with pytest.raises(ConfirmationRequired, match="both request"):
        actions.generate_manual_cv(
            "Data Analyst requires SQL", profile.id,
            ai_polish=True, live_ai_confirmed=False,
        )
    result = actions.generate_manual_cv(
        "Data Analyst requires SQL", profile.id,
        ai_polish=True, live_ai_confirmed=True,
    )
    assert result.ai_status == "failed"
    assert result.ai_failure_category == "configuration_error"


def test_duplicate_and_split_actions_require_confirmation(tmp_path) -> None:
    settings, database, _, job = _context(tmp_path)
    actions = DashboardActions(database, settings)
    with pytest.raises(ConfirmationRequired):
        actions.review_duplicate("00000000-0000-0000-0000-000000000001", "approved", confirmed=False)
    with pytest.raises(ConfirmationRequired):
        actions.split_duplicate(job.id, confirmation="wrong")


def test_duplicate_decision_delegates_to_transactional_service(tmp_path) -> None:
    settings, database, _, _ = _context(tmp_path)
    seed_duplicates(database)
    DeduplicationService(database).backfill()
    with database.read_connection() as connection:
        candidate_id = connection.execute(
            "SELECT id FROM duplicate_candidates WHERE status = 'pending' LIMIT 1"
        ).fetchone()[0]
    DashboardActions(database, settings).review_duplicate(
        candidate_id, "rejected", confirmed=True
    )
    with database.read_connection() as connection:
        assert connection.execute(
            "SELECT status FROM duplicate_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()[0] == "rejected"


def test_cv_actions_preserve_rule_based_cache_and_manual_provenance(tmp_path) -> None:
    settings, database, profile, job = _context(tmp_path)
    text = (ROOT / "tests/fixtures/fit_analysis/full_data_analyst.txt").read_text(
        encoding="utf-8"
    )
    with database.transaction() as connection:
        JobDescriptionRepository(connection).create(JobDescription(
            job_id=job.id, raw_text=text, normalized_text=text,
            completeness=DescriptionCompleteness.FULL, content_hash="d" * 64,
        ))
    actions = DashboardActions(database, settings)
    first = actions.generate_cv(job.id, profile.id)
    repeated = actions.generate_cv(job.id, profile.id)
    manual = actions.generate_manual_cv(text, profile.id)
    assert not first.cache_hit and repeated.cache_hit
    assert repeated.rule_based_artifact.id == first.rule_based_artifact.id
    assert manual.rule_based_artifact.job_id is None
    assert manual.rule_based_artifact.artifact_path.is_file()


def test_attach_cv_action_delegates_to_application_service(tmp_path) -> None:
    settings, database, profile, job = _context(tmp_path)
    text = (ROOT / "tests/fixtures/fit_analysis/full_data_analyst.txt").read_text(
        encoding="utf-8"
    )
    with database.transaction() as connection:
        JobDescriptionRepository(connection).create(JobDescription(
            job_id=job.id, raw_text=text, normalized_text=text,
            completeness=DescriptionCompleteness.FULL, content_hash="e" * 64,
        ))
    actions = DashboardActions(database, settings)
    artifact = actions.generate_cv(job.id, profile.id).rule_based_artifact
    tracked, _ = actions.start_tracking(job.id, profile.id)

    ready = actions.attach_cv_artifact(
        job.id,
        profile.id,
        artifact.id,
        note="CV reviewed in dashboard",
    )

    assert ready.id == tracked.id
    assert ready.status is ApplicationStatus.CV_READY
    assert str(ready.cv_artifact_id) == str(artifact.id)
    with database.read_connection() as connection:
        stored = ApplicationRepository(connection).get(tracked.id)
        assert stored.status is ApplicationStatus.CV_READY


def test_notification_preview_is_offline_and_does_not_create_batches(tmp_path) -> None:
    settings = settings_from_mapping({
        "JOBHUNT_DATABASE_PATH": "dashboard-preview.sqlite3",
        "FIT_RULES_PATH": str(ROOT / "config" / "fit_rules.json"),
        "DEDUP_COMPANY_ALIASES_PATH": str(ROOT / "config" / "company_aliases.json"),
        "TELEGRAM_ENABLED": "false",
    }, root=tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    profile, _ = seed_ranked_vacancies(database, 2)
    preview = DashboardActions(database, settings).notification_preview(profile.id)
    assert preview.selected_count == 2
    with database.read_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM notification_batches"
        ).fetchone()[0] == 0
