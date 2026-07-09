from __future__ import annotations

from datetime import UTC, datetime

from app.db.repositories import ApplicationRepository, DuplicateRepository
from app.services.applications import ApplicationService
from app.services.deduplication import DEDUPLICATION_VERSION
from app.services.deduplication import DeduplicationService
from app.services.pipeline import PipelineRunRequest, PipelineService
from tests.integration.test_pipeline import _rules, _seed_stored_job, _service


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
