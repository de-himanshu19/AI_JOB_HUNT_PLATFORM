from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import app.cli as cli
from app.config import settings_from_mapping
from app.db.connection import Database
from app.db.repositories import (
    ApplicationRepository,
    CandidateProfileRepository,
    CollectionRunRepository,
    JobDescriptionRepository,
    JobRepository,
)
from app.domain.enums import ApplicationStatus, CollectionRunStatus, JobSource
from app.services.applications import ApplicationService
from app.services.collection import CollectionService
from app.sources.arbeitsagentur.adapter import ArbeitsagenturAdapter
from app.sources.arbeitsagentur.client import (
    ArbeitsagenturClientError,
    FixtureArbeitsagenturClient,
)
from app.sources.base import CollectionRequest


FIXTURES = Path(__file__).parents[1] / "fixtures" / "arbeitsagentur"


def _request():
    return CollectionRequest(
        queries=("Data Analyst",), max_pages=2, page_size=25
    )


def _adapter(settings, client=None):
    return ArbeitsagenturAdapter(
        settings, client or FixtureArbeitsagenturClient(FIXTURES)
    )


def test_first_insert_and_repeated_run_are_idempotent(settings, database):
    service = CollectionService(database)
    first = service.execute(
        _adapter(settings), _request(), source=JobSource.ARBEITSAGENTUR
    )
    assert first.jobs_inserted == 2
    assert first.jobs_updated == 0
    assert first.description_versions_inserted == 2

    with database.read_connection() as connection:
        repository = JobRepository(connection)
        original = repository.get_by_source_identity(
            JobSource.ARBEITSAGENTUR, "REF-100"
        )
        original_id = original.id
        original_first_seen = original.first_seen_at
        original_last_seen = original.last_seen_at

    second = service.execute(
        _adapter(settings), _request(), source=JobSource.ARBEITSAGENTUR
    )
    assert second.jobs_inserted == 0
    assert second.jobs_updated == 2
    assert second.description_versions_inserted == 0
    with database.read_connection() as connection:
        stored = JobRepository(connection).get_by_source_identity(
            JobSource.ARBEITSAGENTUR, "REF-100"
        )
        assert stored.id == original_id
        assert stored.first_seen_at == original_first_seen
        assert stored.last_seen_at >= original_last_seen


class MutableClient:
    def __init__(self, company="First GmbH", description="Initial full description " * 3):
        self.company = company
        self.description = description

    def search(self, query, **kwargs):
        return {
            "maxErgebnisse": 1,
            "ergebnisliste": [
                {
                    "referenznummer": "MUTABLE-1",
                    "stellenangebotsTitel": "Data Analyst",
                    "firma": self.company,
                }
            ],
        }

    def fetch_details(self, source_job_id, url=None):
        return {"stellenbeschreibung": self.description}


def test_mutable_fields_update_and_description_versions(settings, database):
    service = CollectionService(database)
    client = MutableClient()
    service.execute(_adapter(settings, client), _request(), source=JobSource.ARBEITSAGENTUR)
    client.company = "Renamed GmbH"
    client.description = "Changed and complete job description " * 3
    report = service.execute(
        _adapter(settings, client), _request(), source=JobSource.ARBEITSAGENTUR
    )
    assert report.jobs_updated == 1
    assert report.description_versions_inserted == 1
    with database.read_connection() as connection:
        job = JobRepository(connection).get_by_source_identity(
            JobSource.ARBEITSAGENTUR, "MUTABLE-1"
        )
        assert job.company_raw == "Renamed GmbH"
        count = connection.execute(
            "SELECT COUNT(*) FROM job_descriptions WHERE job_id = ?", (str(job.id),)
        ).fetchone()[0]
        assert count == 2
        assert "Changed" in JobDescriptionRepository(connection).latest_for_job(job.id).raw_text


class PartialFixtureClient(FixtureArbeitsagenturClient):
    def fetch_details(self, source_job_id, url=None):
        if source_job_id == "REF-200":
            raise ArbeitsagenturClientError("fixture detail failure", retriable=True)
        return super().fetch_details(source_job_id, url)


def test_partial_run_is_finalized_with_useful_jobs(settings, database):
    report = CollectionService(database).execute(
        _adapter(settings, PartialFixtureClient(FIXTURES)),
        _request(),
        source=JobSource.ARBEITSAGENTUR,
    )
    with database.read_connection() as connection:
        run = CollectionRunRepository(connection).get(report.run_id)
        assert run.status is CollectionRunStatus.PARTIAL
        assert run.jobs_stored == 2
        assert run.detail_requests_failed == 1


class FailingPersistenceService(CollectionService):
    def _persist_result(self, result, run_id, observed_at):
        with self.database.transaction() as connection:
            JobRepository(connection).create(result.jobs[0].job)
            raise RuntimeError("forced persistence rollback")


def test_persistence_transaction_rolls_back_and_run_finalizes_failed(
    settings, database
):
    report = FailingPersistenceService(database).execute(
        _adapter(settings), _request(), source=JobSource.ARBEITSAGENTUR
    )
    with database.read_connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        run = CollectionRunRepository(connection).get(report.run_id)
        assert count == 0
        assert run.status is CollectionRunStatus.FAILED
        assert "forced persistence rollback" in run.error_summary


def test_collection_update_does_not_change_application_status(
    settings, database, master_cv_data
):
    service = CollectionService(database)
    service.execute(_adapter(settings), _request(), source=JobSource.ARBEITSAGENTUR)
    with database.transaction() as connection:
        job = JobRepository(connection).get_by_source_identity(
            JobSource.ARBEITSAGENTUR, "REF-100"
        )
        profile = CandidateProfileRepository(connection).create_version(
            master_cv_data, profile_key="candidate"
        )
    applications = ApplicationService(database)
    application = applications.create(job.id, profile.id)
    applications.transition(application.id, ApplicationStatus.SHORTLISTED)

    service.execute(_adapter(settings), _request(), source=JobSource.ARBEITSAGENTUR)
    with database.read_connection() as connection:
        stored = ApplicationRepository(connection).get(application.id)
        assert stored.status is ApplicationStatus.SHORTLISTED


def test_dry_run_uses_fixtures_and_does_not_create_database(tmp_path):
    settings = settings_from_mapping(
        {"JOBHUNT_DATABASE_PATH": "dry-run.sqlite3"}, root=tmp_path
    )
    database = Database.from_settings(settings)
    report = CollectionService(database).execute(
        _adapter(settings), _request(),
        source=JobSource.ARBEITSAGENTUR,
        dry_run=True,
    )
    assert report.dry_run is True
    assert report.jobs_inserted == 2
    assert not database.path.exists()


def test_dry_run_reports_updates_against_existing_database_without_writing(
    settings, database
):
    service = CollectionService(database)
    service.execute(_adapter(settings), _request(), source=JobSource.ARBEITSAGENTUR)
    with database.read_connection() as connection:
        before_jobs = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        before_runs = connection.execute(
            "SELECT COUNT(*) FROM collection_runs"
        ).fetchone()[0]
    before_modified = database.path.stat().st_mtime_ns

    report = service.execute(
        _adapter(settings), _request(),
        source=JobSource.ARBEITSAGENTUR,
        dry_run=True,
    )
    assert report.jobs_inserted == 0
    assert report.jobs_updated == 2
    uri = database.path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == before_jobs
        assert connection.execute(
            "SELECT COUNT(*) FROM collection_runs"
        ).fetchone()[0] == before_runs
    assert database.path.stat().st_mtime_ns == before_modified


def test_cli_fixture_dry_run_is_safe(monkeypatch, tmp_path, capsys):
    settings = settings_from_mapping(
        {"JOBHUNT_DATABASE_PATH": "cli-dry.sqlite3"}, root=tmp_path
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    exit_code = cli.main(
        [
            "collect", "arbeitsagentur", "--dry-run",
            "--fixture-dir", str(FIXTURES), "--query", "Data Analyst",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["mode"] == "dry-run"
    assert output["jobs_collected"] == 2
    assert output["database_modified"] is False
    assert not settings.database_path.exists()
