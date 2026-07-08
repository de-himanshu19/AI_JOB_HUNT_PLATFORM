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


def _section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(heading) + 1
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].isupper() and lines[index]:
            end = index
            break
    return lines[start:end]


def _noisy_profile() -> CandidateProfile:
    payload = {
        "personal_info": {
            "full_name": "Example Candidate",
            "professional_title": "Data Analyst",
        },
        "professional_summary": (
            "Data analyst profile with SQL, Excel, Python, reporting, validation, "
            "and reconciliation evidence across banking and technical operations. "
            "This extra sentence should keep the summary controlled for FlowCV. "
            "Another long sentence keeps testing line wrapping without expanding "
            "into a four page resume.\ufffe"
        ),
        "work_experience": {
            "items": [
                {
                    "id": "gd-1",
                    "role": "Technical Reporting Analyst",
                    "company": "G+D GmbH",
                    "start_date": "Oct 2022",
                    "end_date": "Jul 2025",
                    "bullet_bank": [
                        "Prepared SQL validation reports for technical review.",
                        "Prepared SQL validation reports for technical review.",
                        "Maintained dashboard documentation for stakeholders.",
                        "Coordinated service documentation in regulated operations.",
                        "Supported reconciliation and data quality checks.",
                        "Handled unrelated administrative scheduling.",
                    ],
                    "skills": ["SQL", "validation", "dashboard documentation"],
                    "tools": ["SAP"],
                },
                {
                    "id": "gd-2",
                    "role": "Service Documentation Specialist",
                    "company": "G+D GmbH",
                    "start_date": "Oct 2023",
                    "end_date": "Jul 2025",
                    "bullet_bank": [
                        "Used Excel to reconcile service records.",
                        "Tracked quality findings for reporting handovers.",
                    ],
                    "skills": ["Excel", "reconciliation", "reporting"],
                },
                {
                    "id": "pnb",
                    "role": "Banking Associate",
                    "company": "Punjab National Bank",
                    "bullet_bank": [
                        "Performed data validation for branch reporting.",
                        "Coordinated stakeholder updates for banking operations.",
                    ],
                    "skills": ["data validation", "stakeholder coordination"],
                    "tools": ["Salesforce CRM", "ServiceNow"],
                    "domains": ["banking operations", "compliance"],
                },
            ]
        },
        "projects": {
            "items": [
                {
                    "id": "platform",
                    "name": "AI Job Hunt Platform",
                    "bullet_bank": [
                        "Built SQLite-backed job data workflows.",
                        "Implemented rule-based ranking and reconciliation.",
                        "Created dashboard views for review.",
                        "Documented deployment notes that should be capped.",
                    ],
                    "skills": ["SQLite", "SQLAlchemy", "APIs", "ETL"],
                    "tools": ["GitHub"],
                },
                {
                    "id": "bi",
                    "name": "BI Dashboard",
                    "bullet_bank": [
                        "Created Power BI KPI dashboards.",
                        "Cleaned data with Python and Pandas.",
                        "Validated dashboard inputs.",
                    ],
                    "skills": ["Power BI", "KPI reporting", "Python", "Pandas"],
                },
                {
                    "id": "etl",
                    "name": "ETL Project",
                    "bullet_bank": [
                        "Loaded API data into MySQL.",
                        "Validated ETL outputs.",
                        "Prepared reporting tables.",
                    ],
                    "skills": ["MySQL", "APIs", "ETL"],
                },
                {
                    "id": "extra",
                    "name": "Extra Project",
                    "bullet_bank": ["This lower-priority project should not be emitted."],
                },
            ]
        },
        "education": {"items": [{"degree": "Business degree"}]},
        "skills_and_tools": {
            "data": ["SQL", "Excel", "Python", "Pandas", "data cleaning", "validation", "reconciliation"],
            "bi": ["Power BI", "Tableau", "KPI reporting", "dashboards"],
            "database": ["MySQL", "SQLite", "SQLAlchemy", "APIs", "ETL"],
            "business": ["banking operations", "compliance", "stakeholder coordination"],
            "tools": ["SAP", "Salesforce CRM", "ServiceNow", "GitHub"],
            "languages": ["German A2", "English fluent"],
        },
        "languages": [
            {"name": "English", "proficiency": "fluent"},
            {"name": "German", "proficiency": "A2 and actively improving"},
        ],
    }
    return CandidateProfile.from_master_cv(payload, version=1, profile_key="noisy")


def _noisy_build():
    requirements = (
        JobRequirement(
            requirement_id="role", name="Data Analyst",
            category=RequirementCategory.ROLE,
        ),
        JobRequirement(
            requirement_id="sql", name="SQL",
            category=RequirementCategory.TOOL,
        ),
        JobRequirement(
            requirement_id="dashboards", name="Power BI dashboards",
            category=RequirementCategory.SKILL,
        ),
    )
    evidence = (
        EvidenceReference(
            requirement_id="sql",
            evidence_type=EvidenceType.DIRECT_PROFESSIONAL,
            evidence_id="gd-1",
            label="Technical Reporting Analyst",
            reason="Stored evidence",
        ),
        EvidenceReference(
            requirement_id="dashboards",
            evidence_type=EvidenceType.PROJECT,
            evidence_id="bi",
            label="BI Dashboard",
            reason="Stored evidence",
        ),
    )
    return CVBuilder().build(
        _noisy_profile(), requirements, evidence, missing_requirements=(),
        risk_flags=(), description_completeness="full",
        provenance={"generation_mode": "manual_jd"},
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


def test_rule_builder_keeps_flowcv_output_concise_and_sections_clean() -> None:
    build = _noisy_build()
    text = build.cv_text
    assert "\ufffe" not in text
    assert "\x00" not in text
    assert len(text.splitlines()) <= 90
    assert text.count("Prepared SQL validation reports for technical review.") == 1
    assert text.count("G+D GmbH") == 1
    assert "Extra Project" not in text

    summary_lines = [line for line in _section(text, "PROFESSIONAL SUMMARY") if line]
    assert 1 <= len(summary_lines) <= 5

    skills = "\n".join(_section(text, "KEY SKILLS"))
    assert "Data Analysis:" in skills
    assert "BI & Reporting:" in skills
    assert "Databases & ETL:" in skills
    assert "Business/Domain:" in skills
    assert "Tools:" in skills
    assert "German" not in skills
    assert "A2" not in skills

    languages = "\n".join(_section(text, "LANGUAGES"))
    assert "German: A2 and actively improving" in languages
    assert "English: fluent" in languages

    experience_bullets = [
        line for line in _section(text, "PROFESSIONAL EXPERIENCE")
        if line.startswith("- ")
    ]
    assert len(experience_bullets) <= 8
    assert "Prepared SQL validation reports for technical review." in experience_bullets[0]


def test_rule_builder_limits_projects_to_job_relevant_short_blocks() -> None:
    text = _noisy_build().cv_text
    project_lines = _section(text, "PROJECTS")
    project_headers = [
        line for line in project_lines
        if line and not line.startswith("- ") and "|" not in line
    ]
    assert len(project_headers) <= 3
    assert "BI Dashboard" in project_headers
    assert "AI Job Hunt Platform" in project_headers
    for header in project_headers:
        start = project_lines.index(header) + 1
        following = []
        for line in project_lines[start:]:
            if line and not line.startswith("- "):
                break
            if line.startswith("- "):
                following.append(line)
        assert len(following) <= 3


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
