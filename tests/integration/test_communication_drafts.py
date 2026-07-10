from __future__ import annotations

import json
from pathlib import Path

import requests

import app.cli as cli
from app.dashboard.query_service import DashboardQueryService
from app.domain.enums import DescriptionCompleteness
from app.services.applications import ApplicationService
from app.services.communications import (
    SUPPORTED_DRAFT_TYPES,
    CommunicationDraftService,
)

from tests.integration.test_fit_analysis_persistence import _job, _profile
from tests.integration.test_prep_packs import _database, _seed_description


def _service(database, tmp_path: Path) -> CommunicationDraftService:
    return CommunicationDraftService(
        database,
        default_output_dir=tmp_path / "communication_drafts",
        prep_pack_dir=tmp_path / "prep_packs",
        application_pack_dir=tmp_path / "application_packs",
    )


def test_each_communication_draft_type_creates_markdown(tmp_path: Path) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="comm-all", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)
    service = _service(database, tmp_path)

    for draft_type in SUPPORTED_DRAFT_TYPES:
        result = service.create_draft(
            profile_id=profile.id,
            job_id=job.id,
            draft_type=draft_type,
            output_dir=tmp_path / draft_type,
        )
        text = Path(result.output_path).read_text(encoding="utf-8")
        assert result.status == "created"
        assert result.draft_type == draft_type
        assert "# Communication Draft:" in text
        assert "Nothing has been sent" in text
        assert "Data Analyst" in text
        assert "Example Company" in text


def test_drafts_use_placeholders_when_data_is_missing(tmp_path: Path) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="comm-placeholders", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)
    service = _service(database, tmp_path)

    follow_up = service.create_draft(
        profile_id=profile.id, job_id=job.id, draft_type="follow_up"
    )
    interview = service.create_draft(
        profile_id=profile.id,
        job_id=job.id,
        draft_type="interview_thank_you",
        output_dir=tmp_path / "thanks",
    )
    status = service.create_draft(
        profile_id=profile.id,
        job_id=job.id,
        draft_type="status_update",
        output_dir=tmp_path / "status",
    )

    assert "[Recruiter Name]" in Path(follow_up.output_path).read_text(encoding="utf-8")
    assert "[Application Date]" in Path(follow_up.output_path).read_text(encoding="utf-8")
    assert "[Interview Date]" in Path(interview.output_path).read_text(encoding="utf-8")
    assert "[Portal/Reference Number]" in Path(status.output_path).read_text(encoding="utf-8")


def test_communication_draft_is_conservative_and_evidence_backed(
    tmp_path: Path,
) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="comm-conservative", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)

    result = _service(database, tmp_path).create_draft(
        profile_id=profile.id,
        job_id=job.id,
        draft_type="recruiter_reply",
    )
    text = Path(result.output_path).read_text(encoding="utf-8")

    assert "Stored skills to reference carefully" in text
    assert "fluent German" not in text.casefold()
    assert "senior leader" not in text.casefold()
    assert "[Recruiter Name]" in text


def test_output_dir_redirect_and_no_live_network(tmp_path: Path, monkeypatch) -> None:
    def fail_network(*args, **kwargs):
        raise AssertionError("communication drafts must not make live requests")

    monkeypatch.setattr(requests.Session, "request", fail_network)
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="comm-offline", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)
    output_dir = tmp_path / "draft output"

    result = _service(database, tmp_path).create_draft(
        profile_id=profile.id,
        job_id=job.id,
        draft_type="follow_up",
        output_dir=output_dir,
    )

    assert Path(result.output_path).parent == output_dir


def test_communication_draft_cli_returns_json(monkeypatch, tmp_path: Path, capsys) -> None:
    settings, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="comm-cli", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main([
        "communications",
        "draft",
        "--profile-id",
        str(profile.id),
        "--job-id",
        str(job.id),
        "--type",
        "follow_up",
        "--output-dir",
        str(tmp_path / "cli drafts"),
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "created"
    assert payload["draft_type"] == "follow_up"
    assert payload["job_id"] == str(job.id)
    assert Path(payload["output_path"]).is_file()


def test_record_event_adds_note_without_changing_status(tmp_path: Path) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="comm-event", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)
    application = ApplicationService(database).shortlist_job(
        profile.id, job.id, priority="high", note="Shortlisted"
    )

    result = _service(database, tmp_path).create_draft(
        profile_id=profile.id,
        job_id=job.id,
        draft_type="follow_up",
        record_event=True,
    )

    assert result.event_recorded is True
    with database.read_connection() as connection:
        stored = connection.execute(
            "SELECT current_status FROM applications WHERE id = ?",
            (str(application.id),),
        ).fetchone()
        events = connection.execute(
            """SELECT event_type, note FROM application_events
            WHERE application_id = ? ORDER BY created_at, id""",
            (str(application.id),),
        ).fetchall()
    assert stored["current_status"] == "shortlisted"
    assert any(row["event_type"] == "note_added" for row in events)
    assert any("Communication draft generated" in (row["note"] or "") for row in events)


def test_dashboard_communication_helpers_are_passive(tmp_path: Path) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="comm-dashboard", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)
    result = _service(database, tmp_path).create_draft(
        profile_id=profile.id,
        job_id=job.id,
        draft_type="follow_up",
    )

    query = DashboardQueryService(database)
    commands = query.communication_draft_commands(profile.id, job.id)
    drafts = query.latest_communication_drafts(
        tmp_path / "communication_drafts",
        job_id=job.id,
    )

    assert len(commands) == len(SUPPORTED_DRAFT_TYPES)
    assert all("communications draft" in row["command"] for row in commands)
    assert drafts[0]["path"] == result.output_path


def test_communication_draft_output_path_is_gitignored() -> None:
    assert "data/communication_drafts/" in Path(".gitignore").read_text(
        encoding="utf-8"
    )
