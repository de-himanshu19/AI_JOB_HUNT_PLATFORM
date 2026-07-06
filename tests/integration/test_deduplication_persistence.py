from __future__ import annotations

from datetime import UTC, datetime

import pytest

import app.cli as cli
from app.config import settings_from_mapping
from app.db.connection import Database
from app.db.migrations import migrate
from app.db.repositories import DuplicateRepository, JobDescriptionRepository, JobRepository
from app.domain.duplicates import ReviewStatus
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.services.deduplication import DEDUPLICATION_VERSION, DeduplicationService


def _seed(database: Database) -> list[Job]:
    published = datetime(2026, 7, 1, tzinfo=UTC)
    jobs = [
        Job(source=JobSource.ARBEITSAGENTUR, source_job_id="aa-1", source_url="https://arbeitsagentur.test/1", title_raw="Data Analyst", title_normalized="Data Analyst", company_raw="Acme GmbH", company_normalized="Acme GmbH", location_raw="München", city="München", country="Deutschland", published_at=published),
        Job(source=JobSource.ENGLISHJOBS, source_job_id="ej-1", source_url="https://englishjobs.test/1", title_raw="Data Analyst (m/w/d)", title_normalized="Data Analyst (m/w/d)", company_raw="Acme AG", company_normalized="Acme AG", location_raw="Munich", city="Munich", country="Germany", published_at=published),
        Job(source=JobSource.ENGLISHJOBS, source_job_id="ej-2", source_url="https://englishjobs.test/2", title_raw="Senior Data Analyst", title_normalized="Senior Data Analyst", company_raw="Acme AG", company_normalized="Acme AG", location_raw="Munich", city="Munich", country="Germany", published_at=published),
    ]
    with database.transaction() as connection:
        job_repository = JobRepository(connection)
        description_repository = JobDescriptionRepository(connection)
        for index, job in enumerate(jobs):
            job_repository.create(job)
            description_repository.create(JobDescription(job_id=job.id, raw_text="Build SQL reports and Power BI dashboards", completeness=DescriptionCompleteness.FULL, content_hash=f"hash-{index}"))
    return jobs


def _snapshot(database: Database):
    with database.read_connection() as connection:
        clusters = [tuple(row) for row in connection.execute("SELECT id, representative_job_id FROM duplicate_clusters ORDER BY id")]
        links = [tuple(row) for row in connection.execute("SELECT id, job_id, cluster_id FROM job_duplicate_links ORDER BY id")]
        candidates = [tuple(row) for row in connection.execute("SELECT id, left_job_id, right_job_id, status FROM duplicate_candidates ORDER BY id")]
    return clusters, links, candidates


def test_backfill_is_versioned_idempotent_and_preserves_source_rows(database: Database) -> None:
    jobs = _seed(database)
    service = DeduplicationService(database)
    first = service.backfill()
    first_snapshot = _snapshot(database)
    second = service.backfill()

    assert first.jobs_normalized == 3
    assert first.clusters_created == 2
    assert first.links_created == 3
    assert first.review_candidates_created == 1
    assert second.jobs_normalized == 0
    assert _snapshot(database) == first_snapshot
    with database.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == len(jobs)


def test_review_merge_rolls_back_on_failure_then_split_is_reversible(database: Database, monkeypatch) -> None:
    jobs = _seed(database)
    service = DeduplicationService(database)
    service.backfill()
    with database.read_connection() as connection:
        candidate_id = connection.execute("SELECT id FROM duplicate_candidates").fetchone()[0]

    original = DuplicateRepository.set_candidate_status
    monkeypatch.setattr(DuplicateRepository, "set_candidate_status", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("forced review failure")))
    with pytest.raises(RuntimeError, match="forced review failure"):
        service.review_candidate(candidate_id, ReviewStatus.APPROVED)
    assert len(_snapshot(database)[0]) == 2

    monkeypatch.setattr(DuplicateRepository, "set_candidate_status", original)
    service.review_candidate(candidate_id, ReviewStatus.APPROVED)
    assert len(_snapshot(database)[0]) == 1
    service.backfill()
    assert len(_snapshot(database)[0]) == 1
    with database.transaction() as connection:
        assert DuplicateRepository(connection).get_candidate(candidate_id).status is ReviewStatus.APPROVED
    new_cluster = service.split_job(jobs[2].id, DEDUPLICATION_VERSION)
    assert new_cluster is not None
    assert len(_snapshot(database)[0]) == 2


def test_rejected_candidate_remains_separate_and_reviewed(database: Database) -> None:
    _seed(database)
    service = DeduplicationService(database)
    service.backfill()
    with database.transaction() as connection:
        candidate = DuplicateRepository(connection).list_candidates(
            DEDUPLICATION_VERSION, status=ReviewStatus.PENDING
        )[0]
    service.review_candidate(candidate.id, ReviewStatus.REJECTED)
    with database.transaction() as connection:
        rejected = DuplicateRepository(connection).get_candidate(candidate.id)
    assert rejected.status is ReviewStatus.REJECTED
    assert len(_snapshot(database)[0]) == 2


def test_offline_backfill_and_review_list_cli(monkeypatch, tmp_path, capsys) -> None:
    alias_path = tmp_path / "aliases.json"
    alias_path.write_text("{}", encoding="utf-8")
    settings = settings_from_mapping(
        {
            "JOBHUNT_DATABASE_PATH": "dedup-cli.sqlite3",
            "DEDUP_COMPANY_ALIASES_PATH": str(alias_path),
        },
        root=tmp_path,
    )
    database = Database.from_settings(settings)
    migrate(database)
    _seed(database)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main(["deduplicate", "backfill"]) == 0
    backfill_output = capsys.readouterr().out
    assert '"clusters_created": 2' in backfill_output
    assert cli.main(["deduplicate", "review-list"]) == 0
    review_output = capsys.readouterr().out
    assert '"status": "pending"' in review_output
