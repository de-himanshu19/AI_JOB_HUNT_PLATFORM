"""Candidate-generalized deterministic FlowCV and evidence-report builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.domain.analysis import EvidenceReference, EvidenceType, JobRequirement
from app.domain.candidate import CandidateProfile


GENERATOR_VERSION = "m7-generator-v1"
FORMATTER_VERSION = "flowcv-text-v1"


def _items(data: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = data.get(name, [])
    value = value.get("items", []) if isinstance(value, dict) else value
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    return []


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = " ".join(value.casefold().split())
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _field(item: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = item.get(name)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return None


@dataclass(frozen=True)
class CVBuildResult:
    cv_text: str
    evidence_report_text: str
    protected_facts: tuple[str, ...]


class CVBuilder:
    """Select only stored evidence and render stable ATS-friendly plain text."""

    def build(
        self,
        profile: CandidateProfile,
        requirements: tuple[JobRequirement, ...],
        evidence: tuple[EvidenceReference, ...],
        *,
        missing_requirements: tuple[str, ...],
        risk_flags: tuple[str, ...],
        description_completeness: str,
        provenance: dict[str, str | None],
    ) -> CVBuildResult:
        data = profile.profile_data
        personal = data.get("personal_info", {})
        personal = personal if isinstance(personal, dict) else {}
        detected_role = next(
            (item.name for item in requirements if item.category.value == "role"),
            None,
        )
        headline = str(
            personal.get("professional_title")
            or detected_role
            or "Professional Candidate"
        ).strip()

        lines: list[str] = ["CANDIDATE HEADER"]
        lines.extend(self._header(personal))
        lines.extend(["", "PROFESSIONAL HEADLINE", headline])
        lines.extend(["", "PROFESSIONAL SUMMARY"])
        lines.append(self._summary(data, headline))

        metrics = _unique(_strings(data.get("verified_metrics", data.get("metrics_and_achievements", []))))
        if metrics:
            lines.extend(["", "ACHIEVEMENTS", *[f"- {item}" for item in metrics]])

        skills = self._skills(data, requirements, evidence)
        if skills:
            lines.extend(["", "KEY SKILLS", " | ".join(skills)])

        self._add_items(lines, "PROFESSIONAL EXPERIENCE", _items(data, "work_experience"), "role", "company")
        self._add_items(lines, "PROJECTS", _items(data, "projects"), "name", "project_name", "title")
        courses = [
            *_items(data, "certifications"), *_items(data, "courses"),
            *_items(data, "training_and_courses"),
        ]
        self._add_items(lines, "CERTIFICATIONS AND COURSES", courses, "name", "title", "certificate")
        self._add_items(lines, "EDUCATION", _items(data, "education"), "degree", "name", "institution")

        languages = self._languages(data.get("languages", []))
        if languages:
            lines.extend(["", "LANGUAGES", *[f"- {item}" for item in languages]])

        additional = _unique(_strings(data.get("additional_information", [])))
        for key in ("work_authorization", "availability"):
            additional.extend(_strings(personal.get(key)))
        if additional:
            lines.extend(["", "ADDITIONAL INFORMATION", *[f"- {item}" for item in _unique(additional)]])

        cv_text = "\n".join(lines).strip() + "\n"
        report = self._report(
            detected_role, requirements, evidence, missing_requirements,
            risk_flags, metrics, description_completeness, provenance, data,
        )
        return CVBuildResult(
            cv_text=cv_text,
            evidence_report_text=report,
            protected_facts=tuple(self._protected_facts(data)),
        )

    @staticmethod
    def _header(personal: dict[str, Any]) -> list[str]:
        ordered = (
            "full_name", "location", "phone", "email", "linkedin", "github"
        )
        values = [str(personal[key]).strip() for key in ordered if personal.get(key)]
        return values or ["Candidate"]

    @staticmethod
    def _summary(data: dict[str, Any], headline: str) -> str:
        for key in ("professional_summary", "summary"):
            values = _strings(data.get(key))
            if values:
                return values[0]
        skills = _strings(data.get("skills_and_tools", data.get("skills_bank", {})))
        if skills:
            return f"{headline} with verified evidence in {', '.join(_unique(skills)[:4])}."
        return headline

    @staticmethod
    def _skills(data, requirements, evidence) -> list[str]:
        all_skills = _unique(_strings(data.get("skills_and_tools", data.get("skills_bank", {}))))
        supported_ids = {
            item.requirement_id for item in evidence
            if item.evidence_type is not EvidenceType.NO_EVIDENCE
        }
        preferred = [
            item.name for item in requirements
            if item.requirement_id in supported_ids
            and item.category.value in {"skill", "tool"}
        ]
        return _unique([*preferred, *all_skills])[:24]

    @staticmethod
    def _add_items(lines, heading, items, *label_fields):
        if not items:
            return
        lines.extend(["", heading])
        for item in items:
            label = _field(item, *label_fields) or "Stored evidence"
            company = _field(item, "company", "provider", "institution", "school")
            dates = _field(item, "dates", "date", "period")
            if dates is None:
                start = _field(item, "start_date", "start")
                end = _field(item, "end_date", "end")
                dates = " - ".join(value for value in (start, end) if value) or None
            header = " | ".join(value for value in (label, company, dates) if value)
            lines.append(header)
            details = _unique([
                *_strings(item.get("summary")), *_strings(item.get("role_summary")),
                *_strings(item.get("description")), *_strings(item.get("bullet_bank")),
                *_strings(item.get("bullets")),
            ])
            lines.extend(f"- {detail}" for detail in details)

    @staticmethod
    def _languages(value: Any) -> list[str]:
        if isinstance(value, dict):
            value = value.get("items", value)
            if isinstance(value, dict):
                return [f"{name}: {level}" for name, level in value.items()]
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict) and item.get("name"):
                level = item.get("proficiency") or item.get("level") or "mentioned"
                result.append(f"{item['name']}: {level}")
        return result

    @staticmethod
    def _protected_facts(data: dict[str, Any]) -> list[str]:
        values: list[str] = []
        personal = data.get("personal_info", {})
        if isinstance(personal, dict):
            values.extend(_strings(personal.get("full_name")))
            values.extend(
                text for key, value in personal.items()
                if key != "full_name" for text in _strings(value)
            )
        for section in (
            "work_experience", "projects", "education", "certifications",
            "courses", "training_and_courses", "languages", "verified_metrics",
            "metrics_and_achievements", "skills_and_tools", "skills_bank",
        ):
            values.extend(_strings(data.get(section, [])))
        return _unique(value for value in values if len(value) >= 2)

    @staticmethod
    def _report(role, requirements, evidence, missing, risks, metrics, completeness, provenance, data):
        requirement_by_id = {item.requirement_id: item for item in requirements}
        groups = {kind: [] for kind in EvidenceType}
        for item in evidence:
            requirement = requirement_by_id.get(item.requirement_id)
            groups[item.evidence_type].append(
                f"{requirement.name if requirement else item.requirement_id}: "
                f"{item.label or 'none'} - {item.reason}"
            )
        lines = [
            "PRIVATE EVIDENCE REPORT - NOT RECRUITER-FACING",
            f"Detected role and JD focus: {role or 'No supported role rule detected'}",
            "Selected CV strategy: deterministic evidence-first FlowCV tailoring",
            f"Description completeness: {completeness}",
            "",
            "EVIDENCE USED BY HIERARCHY",
        ]
        labels = {
            EvidenceType.DIRECT_PROFESSIONAL: "Direct professional evidence",
            EvidenceType.PROFESSIONAL_TRANSFERABLE: "Transferable professional evidence",
            EvidenceType.PROJECT: "Project evidence",
            EvidenceType.EDUCATION_TRAINING: "Education/training/certification evidence",
            EvidenceType.NO_EVIDENCE: "Missing evidence",
        }
        for kind in EvidenceType:
            lines.append(labels[kind])
            lines.extend(f"- {value}" for value in groups[kind])
            if not groups[kind]:
                lines.append("- None")
        lines.extend(["", "CV SECTION EVIDENCE"])
        section_sources = (
            ("Professional experience", _items(data, "work_experience")),
            ("Projects", _items(data, "projects")),
            ("Education", _items(data, "education")),
            ("Certifications and courses", [
                *_items(data, "certifications"), *_items(data, "courses"),
                *_items(data, "training_and_courses"),
            ]),
        )
        for section, items in section_sources:
            labels = [
                _field(item, "role", "name", "project_name", "title", "degree", "institution")
                or "Stored evidence"
                for item in items
            ]
            lines.append(f"{section}: {', '.join(labels) if labels else 'None'}")
        lines.append("Key skills: exact stored skills plus supported analyzed requirements")
        lines.append("Achievements: exact verified metrics only")
        lines.extend(["", "QUANTIFIED EVIDENCE USED"])
        lines.extend(f"- {value}" for value in metrics or ["None"])
        lines.extend(["", "MISSING REQUIREMENTS"])
        lines.extend(f"- {value}" for value in missing or ["None"])
        lines.extend(["", "RISK FLAGS"])
        lines.extend(f"- {value}" for value in risks or ["None"])
        lines.extend([
            "", "UNSUPPORTED CLAIMS INTENTIONALLY EXCLUDED",
            *[f"- {value}" for value in missing or ["None identified by deterministic analysis"]],
            "", "PROVENANCE",
        ])
        lines.extend(f"{key}: {value or 'none'}" for key, value in provenance.items())
        lines.extend([
            "AI used: no for this authoritative artifact",
            "AI validation/fallback: derivative attempts are recorded separately",
        ])
        return "\n".join(lines).strip() + "\n"
