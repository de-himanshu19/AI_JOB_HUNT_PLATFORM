from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

import app.cli as cli
from app.config import settings_from_mapping
from app.db.connection import Database
from app.db.migrations import migrate
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.services.applications import ApplicationService
from app.services.pipeline import PipelineRunRequest, PipelineService
from app.sources.base import CollectedJob, CollectionResult, SourceRunStatus

from tests.integration.test_fit_analysis_persistence import (
    _description,
    _job,
    _profile,
    _rules,
)


ROOT = Path(__file__).parents[2]


def _settings(tmp_path):
    return settings_from_mapping(
        {
            "JOBHUNT_DATABASE_PATH": "pipeline.sqlite3",
            "FIT_RULES_PATH": str(ROOT / "config" / "fit_rules.json"),
            "DEDUP_COMPANY_ALIASES_PATH": str(ROOT / "config" / "company_aliases.json"),
        },
        root=tmp_path,
    )


def _service(tmp_path):
    settings = _settings(tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    return settings, database, PipelineService(
        database,
        settings,
        _rules(),
        now=lambda: datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
    )


def _seed_stored_job(database: Database):
    profile = _profile(database)
    job = _job(database, source_id="pipeline-job", title="Data Analyst")
    _description(database, job, "full_data_analyst.txt", DescriptionCompleteness.FULL)
    return profile, job


def test_pipeline_without_live_collect_uses_stored_jobs_and_no_external_collection(
    tmp_path,
) -> None:
    settings, database, _ = _service(tmp_path)
    profile, _ = _seed_stored_job(database)
    calls = []

    def fail_if_called(source):
        calls.append(source)
        raise AssertionError("collector factory must not be called")

    service = PipelineService(
        database,
        settings,
        _rules(),
        collector_factory=fail_if_called,
        now=lambda: datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
    )
    output = tmp_path / "summary.json"
    summary = service.run(PipelineRunRequest(
        profile_id=profile.id,
        output_path=output,
        preview_notification=True,
    ))

    assert calls == []
    assert summary["collection"]["arbeitsagentur"]["status"] == "skipped"
    assert summary["deduplication"]["status"] == "completed"
    assert summary["analysis"]["status"] == "completed"
    assert summary["ranking"]["status"] == "completed"
    assert summary["notification_preview"]["network_requested"] is False
    assert summary["notification_preview"]["database_modified"] is False
    assert summary["top_jobs"][0]["title"] == "Data Analyst"
    assert summary["top_jobs"][0]["application_status"] is None
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["profile_id"] == str(profile.id)
    with database.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0


def test_pipeline_top_jobs_include_existing_application_status(tmp_path) -> None:
    settings, database, _ = _service(tmp_path)
    profile, job = _seed_stored_job(database)
    ApplicationService(database).shortlist_job(profile.id, job.id, priority="high")

    service = PipelineService(
        database,
        settings,
        _rules(),
        now=lambda: datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
    )
    summary = service.run(PipelineRunRequest(profile_id=profile.id))

    assert summary["top_jobs"][0]["application_status"] == "shortlisted"
    assert any(
        "applications shortlist" in action
        for action in summary["next_actions"]
    )


def test_pipeline_validates_profile_id(tmp_path) -> None:
    _, _, service = _service(tmp_path)
    with pytest.raises(KeyError, match="Candidate profile not found"):
        service.run(PipelineRunRequest(profile_id=uuid4()))


def test_pipeline_without_live_collect_and_without_jobs_fails_clearly(tmp_path) -> None:
    _, database, service = _service(tmp_path)
    profile = _profile(database)
    with pytest.raises(ValueError, match="No stored jobs available"):
        service.run(PipelineRunRequest(profile_id=profile.id))


def test_pipeline_invalid_source_fails_clearly(tmp_path) -> None:
    _, database, service = _service(tmp_path)
    profile, _ = _seed_stored_job(database)
    with pytest.raises(ValueError, match="Unsupported pipeline source"):
        service.run(PipelineRunRequest(
            profile_id=profile.id,
            sources=(JobSource.MANUAL,),
        ))


def test_pipeline_cli_writes_output_and_parses_comma_sources(
    monkeypatch, tmp_path, capsys,
) -> None:
    settings = _settings(tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    profile, _ = _seed_stored_job(database)
    output = tmp_path / "cli summary.json"
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main([
        "pipeline", "run",
        "--profile-id", str(profile.id),
        "--source", "arbeitsagentur,englishjobs",
        "--output", str(output),
        "--preview-notification",
        "--no-dashboard-hint",
    ]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["sources_requested"] == ["arbeitsagentur", "englishjobs"]
    assert summary["output_path"] == str(output.resolve(strict=False))
    assert summary["notification_preview"]["created"] is True
    assert all(
        value["network_requested"] is False
        for value in summary["collection"].values()
    )
    assert output.is_file()


def test_pipeline_englishjobs_live_collect_summary_includes_detail_diagnostics(
    tmp_path,
) -> None:
    settings, database, _ = _service(tmp_path)
    profile, _ = _seed_stored_job(database)

    class FakeEnglishJobsCollector:
        def collect(self, request):
            job = Job(
                source=JobSource.ENGLISHJOBS,
                source_job_id="pipeline-englishjobs-detail",
                title_raw="Data Analyst",
                title_normalized="data analyst",
                company_raw="Insight GmbH",
                company_normalized="insight gmbh",
                location_raw="Berlin",
            )
            description = JobDescription(
                job_id=job.id,
                raw_text="SQL reporting responsibilities requirements benefits " * 30,
                normalized_text="SQL reporting responsibilities requirements benefits " * 30,
                completeness=DescriptionCompleteness.FULL,
                content_hash="d" * 64,
            )
            return CollectionResult(
                jobs=[CollectedJob(job=job, description=description)],
                jobs_parsed=1,
                search_requests_succeeded=1,
                detail_requests_attempted=1,
                detail_requests_succeeded=1,
                external_redirects_seen=0,
                status=SourceRunStatus.COMPLETED,
            )

    def collector_factory(source):
        assert source is JobSource.ENGLISHJOBS
        return FakeEnglishJobsCollector()

    service = PipelineService(
        database,
        settings,
        _rules(),
        collector_factory=collector_factory,
        now=lambda: datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
    )
    summary = service.run(PipelineRunRequest(
        profile_id=profile.id,
        sources=(JobSource.ENGLISHJOBS,),
        live_collect=True,
    ))

    collection = summary["collection"]["englishjobs"]
    assert collection["status"] == "completed"
    assert collection["jobs_collected"] == 1
    assert collection["full_descriptions"] == 1
    assert collection["detail_requests_attempted"] == 1
    assert collection["detail_requests_succeeded"] == 1
    assert collection["detail_requests_failed"] == 0
    assert collection["parsing_errors"] == 0
    assert summary["top_jobs"][0]["application_status"] is None


def test_pipeline_source_parser_rejects_invalid_source() -> None:
    with pytest.raises(ValueError, match="Invalid pipeline source"):
        cli._pipeline_sources(["arbeitsagentur,bad-source"])
