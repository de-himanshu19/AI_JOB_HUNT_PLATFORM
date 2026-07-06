import json
from pathlib import Path

from app.db.connection import Database
from app.domain.analysis import EvidenceReference, EvidenceType
from app.domain.candidate import CandidateEvidenceProfile, CandidateProfile
from app.services.analysis_rules import AnalysisRules
from app.services.fit_analysis import FitAnalysisService
from app.services.requirements import RequirementsAnalyzer


ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "fit_analysis"


def _profile():
    payload = json.loads((FIXTURES / "candidate_profile.json").read_text(encoding="utf-8"))
    return CandidateEvidenceProfile.from_candidate_profile(
        CandidateProfile.from_master_cv(payload, version=1)
    )


def test_required_missing_penalty_is_visible_but_optional_missing_is_not_penalized(tmp_path) -> None:
    rules = AnalysisRules.from_json(ROOT / "config" / "fit_rules.json")
    requirements = RequirementsAnalyzer().analyze(
        "Tableau is required. Python is optional.", title="Data Analyst"
    )
    references = tuple(
        EvidenceReference(
            requirement_id=item.requirement_id,
            evidence_type=EvidenceType.NO_EVIDENCE,
            reason="fixture has no evidence",
        )
        for item in requirements
    )
    service = FitAnalysisService(Database(tmp_path / "unused.sqlite3"), rules)
    _, _, penalties, _, _ = service._score(
        requirements, references, (), _profile()
    )
    missing = next(item for item in penalties if item.name == "required_missing")
    required_count = sum(item.required for item in requirements)
    assert missing.points == -min(
        rules.maximum_missing_penalty,
        required_count * rules.required_missing_penalty,
    )


def test_risk_caps_are_explicit_and_reduce_final_score(tmp_path) -> None:
    rules = AnalysisRules.from_json(ROOT / "config" / "fit_rules.json")
    requirements = RequirementsAnalyzer().analyze("SQL is required.", title="Data Analyst")
    references = tuple(
        EvidenceReference(
            requirement_id=item.requirement_id,
            evidence_type=EvidenceType.DIRECT_PROFESSIONAL,
            evidence_id="work-reporting",
            label="Reporting Analyst",
            reason="direct fixture evidence",
        )
        for item in requirements
    )
    service = FitAnalysisService(Database(tmp_path / "unused.sqlite3"), rules)
    score, _, penalties, caps, _ = service._score(
        requirements,
        references,
        ("erp_ownership_gap: generic SAP exposure only",),
        _profile(),
    )
    assert any(item.name == "erp_ownership_gap" for item in penalties)
    assert any(item.name == "erp_ownership_gap" for item in caps)
    assert score <= rules.score_caps["erp_ownership_gap"]
