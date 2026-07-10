from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import requests

import app.cli as cli
from app.config import settings_from_mapping
from app.dashboard.query_service import DashboardQueryService
from app.db.connection import Database
from app.db.migrations import migrate
from app.db.repositories import JobDescriptionRepository
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import JobDescription
from app.services.applications import ApplicationService
from app.services.cv_generation import CVGenerationService
from app.services.fit_analysis import FitAnalysisService
from app.services.prep_pack import REQUIRED_PREP_PACK_SECTIONS, PrepPackService

from tests.integration.test_fit_analysis_persistence import (
    FIXTURES,
    ROOT,
    _job,
    _profile,
    _rules,
)


def _settings(tmp_path: Path):
    return settings_from_mapping(
        {
            "JOBHUNT_DATABASE_PATH": "prep.sqlite3",
            "FIT_RULES_PATH": str(ROOT / "config" / "fit_rules.json"),
            "DEDUP_COMPANY_ALIASES_PATH": str(ROOT / "config" / "company_aliases.json"),
            "CV_ARTIFACT_ROOT": str(tmp_path / "cv_artifacts"),
        },
        root=tmp_path,
    )


def _database(tmp_path: Path) -> tuple[object, Database]:
    settings = _settings(tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    return settings, database


def _service(database: Database, output_dir: Path) -> PrepPackService:
    return PrepPackService(
        database,
        default_output_dir=output_dir,
        now=lambda: datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
    )


def _seed_description(
    database: Database,
    job,
    *,
    completeness: DescriptionCompleteness,
    filename: str = "full_data_analyst.txt",
    hash_char: str = "a",
) -> None:
    text = (FIXTURES / filename).read_text(encoding="utf-8")
    with database.transaction() as connection:
        JobDescriptionRepository(connection).create(JobDescription(
            job_id=job.id,
            raw_text=text,
            normalized_text=text,
            completeness=completeness,
            content_hash=hash_char * 64,
        ))


def test_prep_pack_generated_for_authoritative_job_with_attached_cv(
    tmp_path: Path,
) -> None:
    settings, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="prep-authoritative", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)
    artifact = CVGenerationService(
        database, settings, _rules()
    ).generate_for_job(job.id, profile.id, force_regenerate=True).rule_based_artifact
    ApplicationService(database).mark_cv_ready(
        profile.id,
        job.id,
        cv_artifact_id=artifact.id,
        note="Reviewed CV for prep pack",
    )

    result = _service(database, tmp_path / "packs").create_pack(
        profile_id=profile.id,
        job_id=job.id,
    )
    text = Path(result.output_path).read_text(encoding="utf-8")

    assert result.status == "created"
    assert result.authority == "authoritative"
    assert result.cv_artifact_id == str(artifact.id)
    for section in REQUIRED_PREP_PACK_SECTIONS:
        assert section in text
    assert f"CV artifact: {artifact.id}" in text
    assert "Based on stored profile evidence" in text
    assert not re.search(r"\bled\b", text, flags=re.IGNORECASE)
    assert "Apply manually outside this system." in text


def test_prep_pack_generated_for_prefilter_snippet_job_with_warning(
    tmp_path: Path,
) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(
        database,
        source=JobSource.ENGLISHJOBS,
        source_id="prep-snippet",
        title="Data Analyst",
    )
    _seed_description(
        database, job, completeness=DescriptionCompleteness.SNIPPET
    )
    FitAnalysisService(database, _rules()).analyze_job(job.id, profile.id)

    result = _service(database, tmp_path / "packs").create_pack(
        profile_id=profile.id,
        job_id=job.id,
    )
    text = Path(result.output_path).read_text(encoding="utf-8")

    assert result.authority == "prefilter_only"
    assert any("incomplete" in warning for warning in result.warnings)
    assert "prefilter-only" in text
    assert "open the original vacancy before applying" in text
    assert "do not treat this prep pack as a final fit assessment" in text


def test_missing_cv_artifact_is_handled_safely(tmp_path: Path) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="prep-no-cv", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.FULL, hash_char="b"
    )
    FitAnalysisService(database, _rules()).analyze_job(job.id, profile.id)

    result = _service(database, tmp_path / "packs").create_pack(
        profile_id=profile.id,
        job_id=job.id,
    )
    text = Path(result.output_path).read_text(encoding="utf-8")

    assert result.cv_artifact_id is None
    assert "No matching CV artifact was found." in result.warnings
    assert "python -m app.cli cv generate" in text


def test_explicit_output_dir_and_no_network(tmp_path: Path, monkeypatch) -> None:
    def fail_network(*args, **kwargs):
        raise AssertionError("prep pack must not make live requests")

    monkeypatch.setattr(requests.Session, "request", fail_network)
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="prep-offline", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.FULL, hash_char="c"
    )
    FitAnalysisService(database, _rules()).analyze_job(job.id, profile.id)
    output_dir = tmp_path / "custom prep packs"

    result = _service(database, tmp_path / "default").create_pack(
        profile_id=profile.id,
        job_id=job.id,
        output_dir=output_dir,
    )

    assert Path(result.output_path).parent == output_dir
    assert Path(result.output_path).is_file()


def test_prep_pack_cli_returns_json(monkeypatch, tmp_path: Path, capsys) -> None:
    settings, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="prep-cli", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.FULL, hash_char="d"
    )
    FitAnalysisService(database, _rules()).analyze_job(job.id, profile.id)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    output_dir = tmp_path / "cli packs"

    assert cli.main([
        "prep",
        "pack",
        "--profile-id",
        str(profile.id),
        "--job-id",
        str(job.id),
        "--output-dir",
        str(output_dir),
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "created"
    assert payload["job_id"] == str(job.id)
    assert payload["profile_id"] == str(profile.id)
    assert Path(payload["output_path"]).is_file()


def test_dashboard_prep_pack_helpers_are_read_only(tmp_path: Path) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="prep-dashboard", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.FULL, hash_char="e"
    )
    output_dir = tmp_path / "packs"
    result = _service(database, output_dir).create_pack(
        profile_id=profile.id,
        job_id=job.id,
    )

    query = DashboardQueryService(database)
    command = query.prep_pack_command(profile.id, job.id)
    packs = query.latest_prep_packs(output_dir, job_id=job.id)

    assert command == (
        f"python -m app.cli prep pack --profile-id {profile.id} --job-id {job.id}"
    )
    assert packs[0]["path"] == result.output_path


def test_prep_pack_output_path_is_gitignored() -> None:
    assert "data/prep_packs/" in Path(".gitignore").read_text(encoding="utf-8")
