from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.cli as cli
from app.config import settings_from_mapping
from app.db.connection import Database
from app.db.repositories import JobDescriptionRepository, JobRepository
from app.domain.enums import JobSource
from app.services.collection import CollectionService
from app.sources.base import CollectionRequest
from app.sources.englishjobs.adapter import EnglishJobsAdapter
from app.sources.englishjobs.client import FixtureEnglishJobsClient


FIXTURES = Path(__file__).parents[1] / "fixtures" / "englishjobs"


def _adapter(settings):
    return EnglishJobsAdapter(
        settings,
        FixtureEnglishJobsClient(FIXTURES, base_url=settings.englishjobs_base_url),
    )


def _state_request():
    return CollectionRequest(states=("bayern",), max_pages=2, page_size=20)


def _query_request():
    return CollectionRequest(
        queries=("Data Analyst",),
        location="Germany",
        max_pages=1,
        page_size=20,
    )


def test_first_insert_and_repeated_run_are_idempotent(settings, database):
    service = CollectionService(database)
    first = service.execute(
        _adapter(settings), _state_request(), source=JobSource.ENGLISHJOBS
    )
    assert first.jobs_inserted == 2
    assert first.jobs_updated == 0

    with database.read_connection() as connection:
        original = JobRepository(connection).get_by_source_identity(
            JobSource.ENGLISHJOBS, "listing_id:listing-100"
        )
        original_id = original.id
        original_first_seen = original.first_seen_at

    second = service.execute(
        _adapter(settings), _state_request(), source=JobSource.ENGLISHJOBS
    )
    assert second.jobs_inserted == 0
    assert second.jobs_updated == 2
    with database.read_connection() as connection:
        stored = JobRepository(connection).get_by_source_identity(
            JobSource.ENGLISHJOBS, "listing_id:listing-100"
        )
        assert stored.id == original_id
        assert stored.first_seen_at == original_first_seen


def test_query_run_adds_new_job_and_versions_descriptions(settings, database):
    service = CollectionService(database)
    service.execute(_adapter(settings), _state_request(), source=JobSource.ENGLISHJOBS)
    report = service.execute(
        _adapter(settings), _query_request(), source=JobSource.ENGLISHJOBS
    )
    assert report.jobs_inserted == 1
    with database.read_connection() as connection:
        job = JobRepository(connection).get_by_source_identity(
            JobSource.ENGLISHJOBS, "listing_id:listing-200"
        )
        latest = JobDescriptionRepository(connection).latest_for_job(job.id)
        assert latest.completeness.value == "snippet"


def test_cli_fixture_dry_run_is_safe(monkeypatch, tmp_path, capsys):
    settings = settings_from_mapping(
        {"JOBHUNT_DATABASE_PATH": "englishjobs-cli.sqlite3"},
        root=tmp_path,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    exit_code = cli.main(
        [
            "collect",
            "englishjobs",
            "--dry-run",
            "--fixture-dir",
            str(FIXTURES),
            "--state",
            "bayern",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["mode"] == "dry-run"
    assert output["jobs_collected"] == 2
    assert output["full_descriptions"] == 1
    assert output["snippet_descriptions"] == 1
    assert output["missing_descriptions"] == 0
    assert output["detail_requests_attempted"] == 2
    assert output["external_redirects_seen"] == 1
    assert output["database_modified"] is False
    assert not settings.database_path.exists()


def test_cli_fixture_query_dry_run_is_safe(monkeypatch, tmp_path, capsys):
    settings = settings_from_mapping(
        {"JOBHUNT_DATABASE_PATH": "englishjobs-query-cli.sqlite3"},
        root=tmp_path,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    exit_code = cli.main(
        [
            "collect",
            "englishjobs",
            "--dry-run",
            "--fixture-dir",
            str(FIXTURES),
            "--query",
            "Data Analyst",
            "--location",
            "Germany",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["mode"] == "dry-run"
    assert output["jobs_collected"] == 2
    assert output["full_descriptions"] == 1
    assert output["snippet_descriptions"] == 1
    assert output["missing_descriptions"] == 0
    assert output["detail_requests_attempted"] == 2
    assert output["database_modified"] is False
    assert not settings.database_path.exists()
