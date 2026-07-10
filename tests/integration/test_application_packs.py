from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import requests

import app.cli as cli
from app.dashboard.query_service import DashboardQueryService
from app.domain.enums import DescriptionCompleteness
from app.services.application_pack import (
    REQUIRED_APPLICATION_PACK_FILES,
    ApplicationPackService,
)
from app.services.applications import ApplicationService
from app.services.cv_generation import CVGenerationService
from app.services.fit_analysis import FitAnalysisService

from tests.integration.test_fit_analysis_persistence import _job, _profile, _rules
from tests.integration.test_prep_packs import _database, _seed_description


def _pack_service(database, tmp_path: Path) -> ApplicationPackService:
    return ApplicationPackService(
        database,
        default_output_dir=tmp_path / "application_packs",
        prep_pack_dir=tmp_path / "prep_packs",
        now=lambda: datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
    )


def test_application_pack_created_for_job_with_attached_cv(tmp_path: Path) -> None:
    settings, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="app-pack-with-cv", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)
    artifact = CVGenerationService(
        database, settings, _rules()
    ).generate_for_job(job.id, profile.id, force_regenerate=True).rule_based_artifact
    ApplicationService(database).mark_cv_ready(
        profile.id,
        job.id,
        cv_artifact_id=artifact.id,
        note="CV reviewed",
    )

    result = _pack_service(database, tmp_path).create_pack(
        profile_id=profile.id,
        job_id=job.id,
    )
    folder = Path(result.output_path)

    assert result.cv_artifact_id == str(artifact.id)
    assert set(REQUIRED_APPLICATION_PACK_FILES) <= set(result.files)
    assert all((folder / name).is_file() for name in REQUIRED_APPLICATION_PACK_FILES)
    assert not (folder / "cv_text.md").exists()
    assert str(artifact.id) in (folder / "cv_reference.md").read_text(encoding="utf-8")
    assert "Nothing has been submitted" in (
        folder / "README_CHECKLIST.md"
    ).read_text(encoding="utf-8")


def test_application_pack_created_without_cv_has_warning(tmp_path: Path) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="app-pack-no-cv", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.FULL, hash_char="b"
    )
    FitAnalysisService(database, _rules()).analyze_job(job.id, profile.id)

    result = _pack_service(database, tmp_path).create_pack(
        profile_id=profile.id,
        job_id=job.id,
    )
    cv_reference = Path(result.output_path, "cv_reference.md").read_text(
        encoding="utf-8"
    )

    assert result.cv_artifact_id is None
    assert "No CV artifact found" in " ".join(result.warnings)
    assert "python -m app.cli cv generate" in cv_reference


def test_application_pack_reuses_provided_prep_pack_cover_letter(
    tmp_path: Path,
) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="app-pack-prep", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.FULL, hash_char="c"
    )
    prep = tmp_path / "prep.md"
    prep.write_text(
        "# Application Prep Pack\n\n"
        "## Cover Letter Draft\n\n"
        "CUSTOM COVER LETTER FROM PREP PACK\n\n"
        "## Interview Talking Points\n\n- one\n",
        encoding="utf-8",
    )

    result = _pack_service(database, tmp_path).create_pack(
        profile_id=profile.id,
        job_id=job.id,
        prep_pack_path=prep,
    )
    cover_letter = Path(result.output_path, "cover_letter_draft.md").read_text(
        encoding="utf-8"
    )

    assert result.prep_pack_path == str(prep.resolve(strict=False))
    assert "CUSTOM COVER LETTER FROM PREP PACK" in cover_letter


def test_application_pack_conservative_cover_letter_and_redirected_output(
    tmp_path: Path,
) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="app-pack-conservative", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.SNIPPET, hash_char="d"
    )
    output_dir = tmp_path / "custom output"

    result = _pack_service(database, tmp_path).create_pack(
        profile_id=profile.id,
        job_id=job.id,
        output_dir=output_dir,
    )
    cover_letter = Path(result.output_path, "cover_letter_draft.md").read_text(
        encoding="utf-8"
    )

    assert Path(result.output_path).parent == output_dir
    assert "Based on stored profile evidence" in cover_letter
    assert "Review and edit this draft before sending" in cover_letter
    assert "senior leader" not in cover_letter.casefold()
    assert any("incomplete" in warning for warning in result.warnings)


def test_include_cv_text_copies_only_when_explicit(tmp_path: Path) -> None:
    settings, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="app-pack-copy-cv", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.FULL, hash_char="e"
    )
    artifact = CVGenerationService(
        database, settings, _rules()
    ).generate_for_job(job.id, profile.id, force_regenerate=True).rule_based_artifact
    service = _pack_service(database, tmp_path)

    default = service.create_pack(
        profile_id=profile.id,
        job_id=job.id,
        cv_artifact_id=artifact.id,
        output_dir=tmp_path / "default-pack",
    )
    included = service.create_pack(
        profile_id=profile.id,
        job_id=job.id,
        cv_artifact_id=artifact.id,
        output_dir=tmp_path / "included-pack",
        include_cv_text=True,
    )

    assert not Path(default.output_path, "cv_text.md").exists()
    assert Path(included.output_path, "cv_text.md").is_file()


def test_application_pack_cli_returns_json(monkeypatch, tmp_path: Path, capsys) -> None:
    settings, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="app-pack-cli", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.FULL, hash_char="f"
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main([
        "application-pack",
        "create",
        "--profile-id",
        str(profile.id),
        "--job-id",
        str(job.id),
        "--output-dir",
        str(tmp_path / "cli packs"),
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "created"
    assert payload["job_id"] == str(job.id)
    assert Path(payload["output_path"], "README_CHECKLIST.md").is_file()


def test_submit_manual_sets_status_note_followup_and_event(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    settings, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="submit-manual", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.FULL, hash_char="g"
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main([
        "applications",
        "submit-manual",
        "--profile-id",
        str(profile.id),
        "--job-id",
        str(job.id),
        "--note",
        "Applied manually via company website",
        "--follow-up-date",
        "2026-07-17",
        "--applied-date",
        "2026-07-10",
        "--channel",
        "company website",
        "--reference",
        "ABC123",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["current_status"] == "applied"
    assert payload["follow_up_date"] == "2026-07-17"
    assert payload["manual_submission_recorded"] is True
    assert payload["network_requested"] is False
    with database.read_connection() as connection:
        events = connection.execute(
            """SELECT event_type, note FROM application_events
            WHERE application_id = ? ORDER BY created_at, id""",
            (payload["id"],),
        ).fetchall()
    assert any(row["event_type"] == "status_changed" for row in events)
    assert any("ABC123" in (row["note"] or "") for row in events)


def test_submit_manual_and_dashboard_helpers_do_not_call_live_network(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fail_network(*args, **kwargs):
        raise AssertionError("manual application workflow must not make live requests")

    monkeypatch.setattr(requests.Session, "request", fail_network)
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="app-pack-dashboard", title="Data Analyst")
    _seed_description(
        database, job, completeness=DescriptionCompleteness.FULL, hash_char="h"
    )
    service = _pack_service(database, tmp_path)
    result = service.create_pack(profile_id=profile.id, job_id=job.id)

    query = DashboardQueryService(database)

    assert query.application_pack_command(profile.id, job.id).startswith(
        "python -m app.cli application-pack create"
    )
    assert query.manual_submit_command(profile.id, job.id).startswith(
        "python -m app.cli applications submit-manual"
    )
    assert query.latest_application_packs(
        tmp_path / "application_packs",
        job_id=job.id,
    )[0]["path"] == result.output_path


def test_application_pack_output_path_is_gitignored() -> None:
    assert "data/application_packs/" in Path(".gitignore").read_text(
        encoding="utf-8"
    )
