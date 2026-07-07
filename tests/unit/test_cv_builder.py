from __future__ import annotations

import json
from pathlib import Path

from app.cv.builder import CVBuilder
from app.cv.storage import ArtifactStore
from app.cv.validation import CVValidator
from app.domain.analysis import EvidenceReference, EvidenceType, JobRequirement, RequirementCategory
from app.domain.candidate import CandidateProfile


ROOT = Path(__file__).parents[2]


def _profile() -> CandidateProfile:
    payload = json.loads(
        (ROOT / "tests/fixtures/fit_analysis/candidate_profile.json").read_text(
            encoding="utf-8"
        )
    )
    return CandidateProfile.from_master_cv(payload, version=1, profile_key="example")


def _build():
    requirement = JobRequirement(
        requirement_id="sql", name="SQL", category=RequirementCategory.TOOL
    )
    evidence = EvidenceReference(
        requirement_id="sql", evidence_type=EvidenceType.DIRECT_PROFESSIONAL,
        evidence_id="work-reporting", label="Reporting Analyst", reason="Stored evidence",
    )
    provenance = {
        "generation_mode": "manual_jd", "description_hash": "a" * 64,
        "profile_version": "1", "analyzer_version": "test",
        "rules_version": "test", "generator_version": "test",
        "formatter_version": "test",
    }
    return CVBuilder().build(
        _profile(), (requirement,), (evidence,), missing_requirements=(),
        risk_flags=(), description_completeness="full", provenance=provenance,
    )


def test_rule_builder_is_deterministic_ats_friendly_and_keeps_private_labels_out() -> None:
    first = _build()
    second = _build()
    assert first.cv_text == second.cv_text
    assert first.evidence_report_text == second.evidence_report_text
    assert "Example Candidate" in first.cv_text
    assert "Reporting Analyst" in first.cv_text
    assert "German: A2" in first.cv_text
    assert "evidence type" not in first.cv_text.casefold()
    assert "PRIVATE EVIDENCE REPORT" in first.evidence_report_text
    assert "CV SECTION EVIDENCE" in first.evidence_report_text


def test_ai_validator_rejects_changed_facts_numbers_tools_and_incomplete_output() -> None:
    build = _build()
    validator = CVValidator()
    assert validator.validate_rule_based(build.cv_text, build.protected_facts).valid
    changed = build.cv_text.replace("Example Candidate", "Different Candidate")
    changed += "\nKubernetes expert with 99% improvement\n"
    result = validator.validate_ai(changed, build.cv_text, build.protected_facts)
    assert not result.valid
    assert any("protected fact" in error for error in result.errors)
    assert any("unsupported numbers" in error for error in result.errors)
    assert any("kubernetes" in error for error in result.errors)
    invented = build.cv_text.replace(
        "Reporting Analyst", "Reporting Analyst at Invented Corporation", 1
    ).replace("German: A2", "German: fluent")
    invented_result = validator.validate_ai(
        invented, build.cv_text, build.protected_facts
    )
    assert any("Invented Corporation" in error for error in invented_result.errors)
    assert any("german fluent" in error for error in invented_result.errors)
    assert not validator.validate_ai("incomplete", build.cv_text, build.protected_facts).valid


def test_artifact_store_uses_uuid_names_atomic_files_and_never_overwrites(tmp_path) -> None:
    from uuid import uuid4

    store = ArtifactStore(tmp_path / "Ünicode artifacts")
    artifact_id = uuid4()
    cv_path, report_path = store.write_bundle(artifact_id, "cv", "report")
    assert cv_path.parent == store.root
    assert cv_path.name == f"{artifact_id}.flowcv.txt"
    assert report_path.read_text(encoding="utf-8") == "report"
    try:
        store.write_bundle(artifact_id, "other", "other")
    except FileExistsError:
        pass
    else:
        raise AssertionError("Existing artifact files were overwritten")
    assert cv_path.read_text(encoding="utf-8") == "cv"
