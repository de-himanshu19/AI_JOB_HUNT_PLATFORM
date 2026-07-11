from __future__ import annotations

from pathlib import Path

import requests

from app.domain.enums import DescriptionCompleteness
from app.services.cover_letters import CoverLetterService
from tests.integration.test_fit_analysis_persistence import _job, _profile
from tests.integration.test_prep_packs import _database, _seed_description


class FakeProvider:
    name = "fake"
    model = "conservative-test"

    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def polish(self, prompt: str) -> str:
        self.calls += 1
        assert "Protected facts must remain unchanged" in prompt
        return self.response


def _service(database, tmp_path: Path, provider=None) -> CoverLetterService:
    return CoverLetterService(
        database,
        output_dir=tmp_path / "cover_letters",
        template_dir=Path("config/cover_letter_templates"),
        provider=provider,
    )


def test_rule_based_cover_letter_is_local_evidence_backed_and_reusable(tmp_path) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="cover-full", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)

    result = _service(database, tmp_path).generate(
        profile_id=profile.id,
        job_id=job.id,
        template_name="example_english.md",
    )

    assert result.validated
    assert result.source == "rule_based"
    assert "Dear Hiring Team" in result.text
    assert "Data Analyst" in result.text
    assert "Example Company" in result.text
    assert "fluent German" not in result.text
    assert Path(result.output_path).is_file()
    assert _service(database, tmp_path).latest(profile.id, job.id).artifact_id == result.artifact_id


def test_snippet_cover_letter_warns_and_manual_description_is_not_persisted(tmp_path) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="cover-snippet", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.SNIPPET)
    service = _service(database, tmp_path)

    conservative = service.generate(profile_id=profile.id, job_id=job.id)
    manual = service.generate(
        profile_id=profile.id,
        job_id=job.id,
        manual_description="Full vacancy asks for SQL, reporting, and data validation.",
    )

    assert conservative.warnings
    assert not manual.warnings
    with database.read_connection() as connection:
        stored = connection.execute(
            "SELECT completeness FROM job_descriptions WHERE job_id = ?",
            (str(job.id),),
        ).fetchone()
    assert stored["completeness"] == "snippet"


def test_ai_polish_is_explicit_and_invalid_output_preserves_rule_based_draft(tmp_path) -> None:
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="cover-ai", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)
    base_service = _service(database, tmp_path)
    rule = base_service.generate(profile_id=profile.id, job_id=job.id)
    assert base_service.provider is None

    invalid_provider = FakeProvider(
        rule.text.replace("Dear Hiring Team", "Dear Anna Schmidt").replace(
            "My relevant skills", "I led teams and my relevant skills"
        )
    )
    result = _service(database, tmp_path, invalid_provider).polish(rule.artifact_id)

    assert invalid_provider.calls == 1
    assert not result.validated
    assert result.text == rule.text
    assert result.source == "rule_based"
    assert any("greeting" in error or "stronger wording" in error for error in result.validation_errors)
    assert len(base_service.list(profile_id=profile.id, job_id=job.id)) == 1


def test_valid_ai_polish_creates_separate_derivative_without_network(tmp_path, monkeypatch) -> None:
    def fail_network(*args, **kwargs):
        raise AssertionError("rule-based and fake-provider tests must remain offline")

    monkeypatch.setattr(requests.Session, "request", fail_network)
    _, database = _database(tmp_path)
    profile = _profile(database)
    job = _job(database, source_id="cover-valid-ai", title="Data Analyst")
    _seed_description(database, job, completeness=DescriptionCompleteness.FULL)
    rule = _service(database, tmp_path).generate(profile_id=profile.id, job_id=job.id)
    provider = FakeProvider(rule.text.replace("I would welcome", "I welcome"))

    polished = _service(database, tmp_path, provider).polish(rule.artifact_id)

    assert polished.validated
    assert polished.source == "ai_polished"
    assert polished.parent_artifact_id == rule.artifact_id
    assert polished.artifact_id != rule.artifact_id
    assert Path(rule.output_path).read_text(encoding="utf-8") == rule.text
    assert len(_service(database, tmp_path).list(profile_id=profile.id, job_id=job.id)) == 2


def test_cover_letter_validation_rejects_unsupported_stronger_wording() -> None:
    original = "Dear Hiring Team,\nI support reporting work.\n"
    candidate = "Dear Hiring Team,\nI led reporting work.\n"

    errors = CoverLetterService.validate(candidate, (), original_text=original)

    assert "unsupported stronger wording: led" in errors


def test_cover_letter_validation_rejects_invented_names_tools_and_dates() -> None:
    original = "Dear Hiring Team,\nI support reporting work.\nKind regards,\nCandidate\n"
    candidate = (
        "Dear Hiring Team,\nDear Anna Schmidt,\nI support Tableau reporting work "
        "from 2025.\nKind regards,\nCandidate\n"
    )

    errors = CoverLetterService.validate(candidate, (), original_text=original)

    assert any("greeting" in error for error in errors)
    assert any("unsupported named facts" in error for error in errors)
    assert any("date" in error for error in errors)
