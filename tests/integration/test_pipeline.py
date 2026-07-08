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
from app.services.pipeline import PipelineRunRequest, PipelineService

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
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["profile_id"] == str(profile.id)


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


def test_pipeline_source_parser_rejects_invalid_source() -> None:
    with pytest.raises(ValueError, match="Invalid pipeline source"):
        cli._pipeline_sources(["arbeitsagentur,bad-source"])
