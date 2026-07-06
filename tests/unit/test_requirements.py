from pathlib import Path

from app.domain.analysis import RequirementCategory
from app.services.requirements import RequirementsAnalyzer


FIXTURES = Path(__file__).parents[1] / "fixtures" / "fit_analysis"


def test_extracts_typed_required_and_optional_requirements() -> None:
    requirements = RequirementsAnalyzer().analyze(
        (FIXTURES / "full_data_analyst.txt").read_text(encoding="utf-8"),
        title="Data Analyst",
    )
    by_name = {item.name: item for item in requirements}

    assert by_name["Data Analyst"].category is RequirementCategory.ROLE
    assert by_name["SQL"].required is True
    assert by_name["Power BI"].required is True
    assert by_name["Python"].required is False
    assert by_name["English FLUENT"].level == "FLUENT"


def test_requirement_ids_and_output_are_deterministic() -> None:
    text = (FIXTURES / "risk_german_sap_senior_finance.txt").read_text(encoding="utf-8")
    analyzer = RequirementsAnalyzer()
    assert analyzer.analyze(text, title="Senior Data Analyst") == analyzer.analyze(
        text, title="Senior Data Analyst"
    )
