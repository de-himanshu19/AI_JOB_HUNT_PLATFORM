import json
from pathlib import Path

from app.domain.analysis import EvidenceType
from app.domain.candidate import CandidateEvidenceProfile, CandidateProfile
from app.services.evidence import EvidenceMatcher
from app.services.requirements import RequirementsAnalyzer


FIXTURES = Path(__file__).parents[1] / "fixtures" / "fit_analysis"


def _profile() -> CandidateEvidenceProfile:
    payload = json.loads((FIXTURES / "candidate_profile.json").read_text(encoding="utf-8"))
    return CandidateEvidenceProfile.from_candidate_profile(
        CandidateProfile.from_master_cv(payload, version=1)
    )


def test_generic_profile_contract_preserves_evidence_categories() -> None:
    profile = _profile()
    assert profile.work_experience[0].label == "Reporting Analyst"
    assert profile.projects[0].label == "BI Dashboard Project"
    assert profile.education_training
    assert profile.languages[1].proficiency == "A2"
    assert profile.preferences.target_role_families == (
        "Data Analyst", "Reporting Analyst"
    )


def test_risk_gaps_do_not_promote_weak_evidence() -> None:
    text = (FIXTURES / "risk_german_sap_senior_finance.txt").read_text(encoding="utf-8")
    requirements = RequirementsAnalyzer().analyze(text, title="Senior Data Analyst")
    references, risks = EvidenceMatcher().match(requirements, _profile())
    by_id = {item.requirement_id: item for item in references}
    by_name = {item.name: by_id[item.requirement_id] for item in requirements}

    assert by_name["German EXCELLENT"].evidence_type is EvidenceType.NO_EVIDENCE
    assert by_name["SAP S/4HANA migration ownership"].evidence_type is EvidenceType.NO_EVIDENCE
    assert by_name["Senior professional experience"].evidence_type is EvidenceType.NO_EVIDENCE
    assert by_name["Finance and controlling direct experience"].evidence_type is EvidenceType.PROFESSIONAL_TRANSFERABLE
    assert {item.split(":", 1)[0] for item in risks} == {
        "language_mismatch", "erp_ownership_gap", "seniority_gap",
        "finance_direct_experience_gap",
    }


def test_evidence_precedence_and_optional_missing_are_explicit() -> None:
    text = (FIXTURES / "required_missing.txt").read_text(encoding="utf-8")
    requirements = RequirementsAnalyzer().analyze(text, title="Data Analyst")
    references, _ = EvidenceMatcher().match(requirements, _profile())
    by_name = {
        requirement.name: next(
            item for item in references
            if item.requirement_id == requirement.requirement_id
        )
        for requirement in requirements
    }
    assert by_name["Python"].evidence_type is EvidenceType.PROJECT
    assert by_name["Tableau"].evidence_type is EvidenceType.NO_EVIDENCE


def test_explicitly_required_missing_skill_remains_unsupported() -> None:
    requirements = RequirementsAnalyzer().analyze(
        "Tableau is required. Python is optional.", title="Data Analyst"
    )
    references, _ = EvidenceMatcher().match(requirements, _profile())
    tableau = next(item for item in requirements if item.name == "Tableau")
    reference = next(
        item for item in references if item.requirement_id == tableau.requirement_id
    )
    assert tableau.required is True
    assert reference.evidence_type is EvidenceType.NO_EVIDENCE
