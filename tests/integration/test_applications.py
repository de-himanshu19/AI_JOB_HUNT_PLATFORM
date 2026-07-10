from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.db.repositories import JobDescriptionRepository
from app.db.repositories import ApplicationRepository, DuplicateRepository
from app.domain.job import JobDescription
from app.domain.enums import DescriptionCompleteness
from app.services.applications import ApplicationService
from app.services.cv_generation import CVGenerationService
from app.services.deduplication import DEDUPLICATION_VERSION
from app.services.deduplication import DeduplicationService
from app.services.pipeline import PipelineRunRequest, PipelineService
from tests.integration.test_pipeline import _rules, _seed_stored_job, _service


FIT_FIXTURES = Path(__file__).parents[1] / "fixtures" / "fit_analysis"


def test_deduplication_clear_version_does_not_delete_application_tracking(
    tmp_path,
) -> None:
    _, database, _ = _service(tmp_path)
    profile, job = _seed_stored_job(database)

    DeduplicationService(database).backfill(algorithm_version=DEDUPLICATION_VERSION)
    application = ApplicationService(database).shortlist_job(
        profile.id, job.id, priority="high", note="Keep tracking"
    )
    assert application.logical_cluster_id is not None

    with database.transaction() as connection:
        DuplicateRepository(connection).clear_version(DEDUPLICATION_VERSION)

    with database.read_connection() as connection:
        stored = ApplicationRepository(connection).get(application.id)
        assert stored is not None
        assert stored.status.value == "shortlisted"
        assert stored.notes == "Keep tracking"
        assert connection.execute(
            "SELECT COUNT(*) FROM application_events WHERE application_id = ?",
            (str(application.id),),
        ).fetchone()[0] >= 1


def test_pipeline_succeeds_after_application_exists_and_dedup_rebuilds(
    tmp_path,
) -> None:
    settings, database, _ = _service(tmp_path)
    profile, job = _seed_stored_job(database)

    DeduplicationService(database).backfill(algorithm_version=DEDUPLICATION_VERSION)
    ApplicationService(database).shortlist_job(profile.id, job.id, priority="high")

    summary = PipelineService(
        database,
        settings,
        _rules(),
        now=lambda: datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
    ).run(PipelineRunRequest(profile_id=profile.id))

    assert summary["deduplication"]["status"] == "completed"
    assert summary["top_jobs"][0]["application_status"] == "shortlisted"
    with database.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1


def test_attach_cv_artifact_marks_application_ready_without_duplicate_rows(
    tmp_path,
) -> None:
    settings, database, _ = _service(tmp_path)
    profile, job = _seed_stored_job(database)
    full_text = (FIT_FIXTURES / "full_data_analyst.txt").read_text(encoding="utf-8")
    with database.transaction() as connection:
        JobDescriptionRepository(connection).create(JobDescription(
            id=uuid4(),
            job_id=job.id,
            raw_text=full_text,
            normalized_text=full_text,
            completeness=DescriptionCompleteness.FULL,
            content_hash="b" * 64,
            fetched_at=datetime(2026, 7, 11, tzinfo=UTC),
        ))
    artifact = CVGenerationService(
        database, settings, _rules()
    ).generate_for_job(job.id, profile.id, force_regenerate=True).rule_based_artifact
    service = ApplicationService(database)
    shortlisted = service.shortlist_job(profile.id, job.id, priority="high")

    ready = service.mark_cv_ready(
        profile.id,
        job.id,
        cv_artifact_id=artifact.id,
        note="FlowCV reviewed",
    )
    repeated = service.mark_cv_ready(
        profile.id,
        job.id,
        cv_artifact_id=artifact.id,
        note="FlowCV reviewed",
    )

    assert ready.id == shortlisted.id == repeated.id
    assert ready.status.value == "cv_ready"
    assert str(ready.cv_artifact_id) == str(artifact.id)
    with database.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
        events = connection.execute(
            """SELECT event_type FROM application_events
            WHERE application_id = ? ORDER BY created_at, id""",
            (str(ready.id),),
        ).fetchall()
    assert "cv_attached" in {row["event_type"] for row in events}
