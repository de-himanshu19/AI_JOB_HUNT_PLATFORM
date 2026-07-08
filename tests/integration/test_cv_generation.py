from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings_from_mapping
from app.db.connection import Database
from app.db.migrations import migrate
from app.db.repositories import CandidateProfileRepository, JobDescriptionRepository, JobRepository
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.services.analysis_rules import AnalysisRules
import app.services.cv_generation as cv_generation
from app.services.cv_generation import CVGenerationService
from app.services.deduplication import DeduplicationService
from app.db.repositories import CVGenerationArtifactRepository
import app.cli as cli


ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests/fixtures/fit_analysis"


class FakeProvider:
    name = "fake_ollama"
    model = "fake-model"

    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def polish(self, prompt: str) -> str:
        self.calls += 1
        assert "Return only the complete CV text" in prompt
        return self.response


class FailingProvider(FakeProvider):
    def __init__(self, error):
        super().__init__("")
        self.error = error

    def polish(self, prompt: str) -> str:
        self.calls += 1
        raise self.error


def _setup(tmp_path):
    settings = settings_from_mapping({
        "JOBHUNT_DATABASE_PATH": "runtime/m7.sqlite3",
        "CV_ARTIFACT_ROOT": "private/cv",
        "FIT_RULES_PATH": str(ROOT / "config/fit_rules.json"),
        "DEDUP_COMPANY_ALIASES_PATH": str(ROOT / "config/company_aliases.json"),
    }, root=tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    payload = json.loads((FIXTURES / "candidate_profile.json").read_text(encoding="utf-8"))
    with database.transaction() as connection:
        profile = CandidateProfileRepository(connection).create_version(payload, profile_key="m7")
    rules = AnalysisRules.from_json(ROOT / "config/fit_rules.json")
    return settings, database, profile, rules


def _job(database, completeness=DescriptionCompleteness.FULL):
    job = Job(
        source=JobSource.MANUAL, source_job_id=f"m7-{completeness.value}",
        title_raw="Data Analyst", title_normalized="data analyst",
        company_raw="Example Company", company_normalized="example company",
    )
    text = (FIXTURES / "full_data_analyst.txt").read_text(encoding="utf-8")
    description = JobDescription(
        job_id=job.id, raw_text=text if completeness is not DescriptionCompleteness.MISSING else None,
        normalized_text=text if completeness is not DescriptionCompleteness.MISSING else None,
        completeness=completeness,
        content_hash=("f" if completeness is DescriptionCompleteness.FULL else "a") * 64,
        fetched_at=datetime.now(UTC),
    )
    with database.transaction() as connection:
        JobRepository(connection).create(job)
        JobDescriptionRepository(connection).create(description)
    return job


def test_stored_generation_is_validated_persisted_and_cached(tmp_path) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    job = _job(database)
    DeduplicationService(database).backfill()
    service = CVGenerationService(database, settings, rules)
    first = service.generate_for_job(job.id, profile.id)
    second = service.generate_for_job(job.id, profile.id)
    assert not first.cache_hit
    assert second.cache_hit
    assert second.rule_based_artifact.id == first.rule_based_artifact.id
    artifact = first.rule_based_artifact
    assert artifact.job_id == job.id
    assert artifact.logical_cluster_id is not None
    assert artifact.analysis_id is not None
    assert artifact.validated
    assert artifact.artifact_path.is_file()
    assert artifact.evidence_report_path.is_file()
    assert service.artifact_details(artifact.id)[0] == artifact


def test_changed_description_and_profile_create_new_artifacts_without_overwrite(tmp_path) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    job = _job(database)
    service = CVGenerationService(database, settings, rules)
    original = service.generate_for_job(job.id, profile.id).rule_based_artifact

    changed_text = (FIXTURES / "required_missing.txt").read_text(encoding="utf-8")
    changed_description = JobDescription(
        job_id=job.id, raw_text=changed_text, normalized_text=changed_text,
        completeness=DescriptionCompleteness.FULL, content_hash="e" * 64,
        fetched_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    with database.transaction() as connection:
        JobDescriptionRepository(connection).create(changed_description)
    changed = service.generate_for_job(job.id, profile.id).rule_based_artifact
    assert changed.id != original.id
    assert changed.analysis_id != original.analysis_id
    assert original.artifact_path.is_file()

    payload = json.loads((FIXTURES / "candidate_profile.json").read_text(encoding="utf-8"))
    payload["domains"].append("new-domain")
    with database.transaction() as connection:
        profile_v2 = CandidateProfileRepository(connection).create_version(
            payload, profile_key="m7"
        )
    profile_changed = service.generate_for_job(
        job.id, profile_v2.id
    ).rule_based_artifact
    assert profile_changed.id not in {original.id, changed.id}
    assert profile_changed.profile_version == 2
    assert service.artifact_details(original.id)[0] == original


def test_builder_content_version_changes_rule_based_artifact_identity(
    tmp_path, monkeypatch,
) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    job = _job(database)
    service = CVGenerationService(database, settings, rules)
    original = service.generate_for_job(job.id, profile.id).rule_based_artifact

    monkeypatch.setattr(
        cv_generation,
        "CV_BUILDER_CONTENT_VERSION",
        "test-builder-content-next",
    )
    changed = service.generate_for_job(job.id, profile.id)

    assert not changed.cache_hit
    assert changed.rule_based_artifact.id != original.id
    assert changed.rule_based_artifact.generation_identity != original.generation_identity
    assert original.artifact_path.is_file()
    assert service.artifact_details(original.id)[0] == original
    assert (
        "builder_content_version: test-builder-content-next"
        in changed.rule_based_artifact.evidence_report_path.read_text(encoding="utf-8")
    )


def test_snippet_and_missing_stored_descriptions_require_manual_fallback(tmp_path) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    service = CVGenerationService(database, settings, rules)
    for completeness in (DescriptionCompleteness.SNIPPET, DescriptionCompleteness.MISSING):
        job = _job(database, completeness)
        try:
            service.generate_for_job(job.id, profile.id)
        except ValueError as error:
            assert "generate-manual" in str(error)
        else:
            raise AssertionError("Incomplete stored description generated a CV")


def test_manual_generation_has_stable_hash_no_job_and_validates_input_file(tmp_path) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    path = tmp_path / "manual Ünicode.md"
    path.write_text((FIXTURES / "full_data_analyst.txt").read_text(encoding="utf-8"), encoding="utf-8")
    service = CVGenerationService(database, settings, rules)
    first = service.generate_manual_file(path, profile.id)
    second = service.generate_manual_file(path, profile.id)
    artifact = first.rule_based_artifact
    assert artifact.job_id is None
    assert artifact.description_id is None
    assert artifact.analysis_id is None
    assert second.cache_hit and second.rule_based_artifact.id == artifact.id
    assert str(path) not in artifact.evidence_report_path.read_text(encoding="utf-8")


def test_ai_derivative_is_separate_and_invalid_output_records_safe_failure(tmp_path) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    job = _job(database)
    base_service = CVGenerationService(database, settings, rules)
    base = base_service.generate_for_job(job.id, profile.id).rule_based_artifact
    rule_text = base.artifact_path.read_text(encoding="utf-8")

    provider = FakeProvider(rule_text)
    success = CVGenerationService(
        database, settings, rules, provider=provider
    ).generate_for_job(job.id, profile.id, ai_polish=True, live_ai=True)
    assert success.ai_status == "succeeded"
    assert success.ai_artifact.parent_rule_based_artifact_id == base.id
    assert success.ai_artifact.id != base.id
    assert base.artifact_path.read_text(encoding="utf-8") == rule_text

    failed = CVGenerationService(
        database, settings, rules, provider=FakeProvider("malformed")
    ).generate_for_job(job.id, profile.id, ai_polish=True, live_ai=True)
    assert failed.ai_status == "failed"
    assert failed.ai_failure_category == "validation_failed"
    artifact, attempts = base_service.artifact_details(base.id)
    assert artifact == base
    assert {attempt.status.value for attempt in attempts} == {"succeeded", "failed"}
    assert all(attempt.evidence_report_path.is_file() for attempt in attempts)


def test_ai_timeout_and_provider_errors_are_safe_and_rule_file_survives(tmp_path) -> None:
    import requests

    settings, database, profile, rules = _setup(tmp_path)
    job = _job(database)
    for error, category in (
        (requests.Timeout("slow"), "timeout"),
        (RuntimeError("secret response must not escape"), "provider_error"),
        (ValueError("invalid JSON"), "malformed_content"),
    ):
        result = CVGenerationService(
            database, settings, rules, provider=FailingProvider(error)
        ).generate_for_job(job.id, profile.id, ai_polish=True, live_ai=True)
        assert result.ai_status == "failed"
        assert result.ai_failure_category == category
        assert result.rule_based_artifact.artifact_path.is_file()
    _, attempts = CVGenerationService(database, settings, rules).artifact_details(
        result.rule_based_artifact.id
    )
    assert {attempt.failure_category for attempt in attempts} >= {
        "timeout", "provider_error", "malformed_content",
    }
    assert all("secret response" not in json.dumps(attempt.validation_result) for attempt in attempts)
    assert all(attempt.evidence_report_path.is_file() for attempt in attempts)


def test_ai_requires_both_explicit_flags_and_never_calls_provider_otherwise(tmp_path) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    job = _job(database)
    provider = FakeProvider("unused")
    service = CVGenerationService(database, settings, rules, provider=provider)
    for flags in ((True, False), (False, True)):
        try:
            service.generate_for_job(
                job.id, profile.id, ai_polish=flags[0], live_ai=flags[1]
            )
        except ValueError as error:
            assert "both --ai-polish and --live-ai" in str(error)
        else:
            raise AssertionError("A single AI opt-in flag was accepted")
    assert provider.calls == 0


def test_unconfigured_ai_records_failure_after_authoritative_generation(tmp_path) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    job = _job(database)
    result = CVGenerationService(database, settings, rules).generate_for_job(
        job.id, profile.id, ai_polish=True, live_ai=True
    )
    assert result.rule_based_artifact.artifact_path.is_file()
    assert result.ai_status == "failed"
    assert result.ai_failure_category == "configuration_error"
    _, attempts = CVGenerationService(database, settings, rules).artifact_details(
        result.rule_based_artifact.id
    )
    assert attempts[0].provider == "unconfigured"
    assert "configuration_error" in attempts[0].evidence_report_path.read_text(
        encoding="utf-8"
    )


def test_manual_file_rejects_empty_large_non_utf8_and_non_text_inputs(tmp_path) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    service = CVGenerationService(database, settings, rules)
    cases = {
        "empty.txt": b"",
        "binary.txt": b"\xff\xfe\xff",
        "wrong.pdf": b"description",
        "large.txt": b"x" * (settings.cv_manual_max_bytes + 1),
    }
    for name, content in cases.items():
        path = tmp_path / name
        path.write_bytes(content)
        try:
            service.generate_manual_file(path, profile.id)
        except (ValueError, UnicodeDecodeError):
            pass
        else:
            raise AssertionError(f"Unsafe manual input was accepted: {name}")


def test_artifact_files_are_removed_when_database_persistence_fails(
    tmp_path, monkeypatch,
) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    service = CVGenerationService(database, settings, rules)

    def fail_create(self, artifact):
        raise RuntimeError("forced persistence failure")

    monkeypatch.setattr(CVGenerationArtifactRepository, "create", fail_create)
    try:
        service.generate_manual_text("Data Analyst requires SQL", profile.id)
    except RuntimeError as error:
        assert "forced persistence failure" in str(error)
    else:
        raise AssertionError("Forced database failure did not propagate")
    assert list(settings.cv_artifact_root.glob("*")) == []


def test_cv_cli_generate_list_show_and_manual_are_offline_and_do_not_change_status(
    tmp_path, monkeypatch, capsys,
) -> None:
    settings, database, profile, rules = _setup(tmp_path)
    job = _job(database)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main([
        "cv", "generate", "--job-id", str(job.id),
        "--profile-id", str(profile.id),
    ]) == 0
    generated = json.loads(capsys.readouterr().out)
    artifact_id = generated["authoritative_rule_based_artifact"]["artifact_id"]
    assert generated["application_status_changed"] is False
    assert generated["ai_status"] == "not_requested"
    assert generated["builder_content_version"] == cv_generation.CV_BUILDER_CONTENT_VERSION

    assert cli.main(["cv", "list", "--job-id", str(job.id)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["artifact_id"] == artifact_id
    assert cli.main(["cv", "show", artifact_id]) == 0
    assert json.loads(capsys.readouterr().out)["artifact_id"] == artifact_id

    assert cli.main([
        "cv", "generate", "--job-id", str(job.id),
        "--profile-id", str(profile.id), "--force-regenerate",
    ]) == 0
    forced = json.loads(capsys.readouterr().out)
    forced_artifact_id = forced["authoritative_rule_based_artifact"]["artifact_id"]
    assert forced["cached_artifact_reused"] is False
    assert forced["force_regenerate_requested"] is True
    assert forced_artifact_id != artifact_id
    with database.read_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM cv_generation_artifacts WHERE source = 'rule_based'"
        ).fetchone()[0] == 2

    manual = tmp_path / "manual.txt"
    manual.write_text("Data Analyst requires SQL and Python", encoding="utf-8")
    assert cli.main([
        "cv", "generate-manual", "--description-file", str(manual),
        "--profile-id", str(profile.id),
    ]) == 0
    manual_output = json.loads(capsys.readouterr().out)
    assert manual_output["authoritative_rule_based_artifact"]["job_id"] is None
    with database.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0
