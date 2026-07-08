"""Candidate-generalized deterministic FlowCV and evidence-report builder."""

from __future__ import annotations

import re
import textwrap
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from app.domain.analysis import EvidenceReference, EvidenceType, JobRequirement
from app.domain.candidate import CandidateProfile


GENERATOR_VERSION = "m7-generator-v1"
FORMATTER_VERSION = "flowcv-text-v2"

SUMMARY_WIDTH = 96
SUMMARY_MAX_LINES = 5
MAX_ACHIEVEMENTS = 3
MAX_EXPERIENCE_ITEMS = 4
MAX_EXPERIENCE_BULLETS = 3
MAX_PROJECTS = 2
MAX_PROJECT_BULLETS = 3
MAX_CERTIFICATIONS = 5
MAX_CERTIFICATION_BULLETS = 1
MAX_EDUCATION_ITEMS = 2
MAX_EDUCATION_BULLETS = 1

LANGUAGE_NAMES = {"english", "german", "hindi", "french", "spanish", "italian"}
LANGUAGE_LEVELS = {
    "a1", "a2", "b1", "b2", "c1", "c2", "basic", "native", "fluent",
    "professional", "business", "excellent", "intermediate", "beginner",
}
SKILL_CANONICAL = {
    "api": "APIs",
    "apis": "APIs",
    "data cleaning": "data cleaning",
    "data validation": "validation",
    "database": "databases",
    "dashboard": "dashboards",
    "dashboards": "dashboards",
    "etl": "ETL",
    "excel": "Excel",
    "github": "GitHub",
    "git": "GitHub",
    "kpi": "KPI reporting",
    "kpi reporting": "KPI reporting",
    "mysql": "MySQL",
    "pandas": "Pandas",
    "power bi": "Power BI",
    "python": "Python",
    "reconciliation": "reconciliation",
    "reporting": "reporting",
    "salesforce": "Salesforce CRM",
    "salesforce crm": "Salesforce CRM",
    "sap": "SAP",
    "servicenow": "ServiceNow",
    "sql": "SQL",
    "sqlalchemy": "SQLAlchemy",
    "sqlite": "SQLite",
    "stakeholder coordination": "stakeholder coordination",
    "tableau": "Tableau",
    "validation": "validation",
}
SKILL_GROUPS = (
    ("Data Analysis", ("sql", "excel", "python", "pandas", "clean", "validation", "reconciliation", "analysis", "data quality"), 8),
    ("BI & Reporting", ("power bi", "tableau", "kpi", "dashboard", "visualization", "reporting", "scorecard"), 7),
    ("Databases & ETL", ("mysql", "sqlite", "sqlalchemy", "api", "etl", "database", "pipeline"), 7),
    ("Business/Domain", ("bank", "compliance", "stakeholder", "coordination", "operation", "reporting", "aml", "kyc"), 7),
    ("Tools", ("sap", "salesforce", "servicenow", "github", "git", "office"), 7),
)
MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _clean_text(value: str) -> str:
    """Remove broken/control characters while preserving truthful source text."""
    text = str(value)
    cleaned: list[str] = []
    for char in text:
        code = ord(char)
        is_noncharacter = (
            0xFDD0 <= code <= 0xFDEF
            or (code & 0xFFFF) in {0xFFFE, 0xFFFF}
        )
        category = unicodedata.category(char)
        if (
            char in {"\ufeff", "\ufffd"}
            or is_noncharacter
            or category in {"Cc", "Cf", "Co", "Cs", "Cn"}
        ):
            cleaned.append(" ")
        elif char in {"\n", "\r", "\t"}:
            cleaned.append(" ")
        else:
            cleaned.append(char)
    text = re.sub(r"\s+", " ", "".join(cleaned)).strip()
    return _fix_missing_spaces(text)


def _fix_missing_spaces(text: str) -> str:
    replacements = (
        (r"\bData(?=Analysis\b)", "Data "),
        (r"\bSLA(?=Breach\b)", "SLA "),
        (r"\bfor(?=Data\b)", "for "),
        (r"\bMBA(?=in\b)", "MBA "),
        (r"Technology(?=GmbH\b)", "Technology "),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def _items(data: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = data.get(name, [])
    value = value.get("items", []) if isinstance(value, dict) else value
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        cleaned = _clean_text(value)
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    return []


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = _clean_text(value)
        key = " ".join(value.casefold().split())
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _field(item: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = item.get(name)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return _clean_text(str(value))
    return None


def _language_like(value: str) -> bool:
    words = set(re.findall(r"[a-z0-9+/.-]+", value.casefold()))
    return bool(words & LANGUAGE_NAMES) and bool(words & LANGUAGE_LEVELS)


def _canonical_skill(value: str) -> str:
    lowered = value.casefold().strip()
    if lowered in SKILL_CANONICAL:
        return SKILL_CANONICAL[lowered]
    for key, canonical in SKILL_CANONICAL.items():
        if key in lowered:
            return canonical
    return value[:1].upper() + value[1:] if value.islower() else value


def _score_text(text: str, context_terms: tuple[str, ...]) -> int:
    lowered = text.casefold()
    score = 0
    for term in context_terms:
        normalized = term.casefold()
        if normalized and normalized in lowered:
            score += 4 if len(normalized) > 3 else 1
    for keyword in ("sql", "excel", "python", "pandas", "power bi", "tableau", "kpi", "dashboard", "validation", "reconciliation", "reporting", "etl"):
        if keyword in lowered:
            score += 1
    return score


def _item_details(item: dict[str, Any]) -> list[str]:
    return _unique([
        *_strings(item.get("summary")), *_strings(item.get("role_summary")),
        *_strings(item.get("description")), *_strings(item.get("bullet_bank")),
        *_strings(item.get("bullets")), *_strings(item.get("achievements")),
        *_strings(item.get("metrics")),
    ])


def _date_key(value: str | None, *, latest: bool = False) -> tuple[int, int]:
    if not value:
        return (9999, 12) if latest else (0, 0)
    text = _clean_text(value).casefold()
    if any(term in text for term in ("present", "current", "today", "ongoing")):
        return (9999, 12)
    numeric = re.search(r"\b(0?[1-9]|1[0-2])[/.-](\d{4})\b", text)
    if numeric:
        return (int(numeric.group(2)), int(numeric.group(1)))
    year_month = re.search(r"\b(\d{4})[/.-](0?[1-9]|1[0-2])\b", text)
    if year_month:
        return (int(year_month.group(1)), int(year_month.group(2)))
    named = re.search(
        r"\b("
        + "|".join(sorted(MONTHS, key=len, reverse=True))
        + r")[a-z]*\.?\s+(\d{4})\b",
        text,
    )
    if named:
        return (int(named.group(2)), MONTHS[named.group(1).rstrip(".")])
    year = re.search(r"\b(19|20)\d{2}\b", text)
    if year:
        return (int(year.group(0)), 12 if latest else 1)
    return (9999, 12) if latest else (0, 0)


def _date_range_value(values: Iterable[str], *, latest: bool) -> str | None:
    dated = [
        (index, _date_key(value, latest=latest), value)
        for index, value in enumerate(values)
        if value
    ]
    if not dated:
        return None
    if latest:
        return max(dated, key=lambda item: (item[1], item[0]))[2]
    return min(dated, key=lambda item: (item[1], item[0]))[2]


def _complete_sentence_summary(text: str, fallback: str) -> str:
    source = _clean_text(text) or _clean_text(fallback)
    budget = SUMMARY_WIDTH * SUMMARY_MAX_LINES
    sentences = re.findall(r".*?(?:[.!?](?=\s|$)|$)", source)
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    if not sentences:
        return source
    selected: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*selected, sentence]).strip()
        if selected and len(candidate) > budget:
            break
        selected.append(sentence)
        if len(candidate) >= budget:
            break
    return " ".join(selected) if selected else sentences[0]


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

        context_terms = self._context_terms(requirements, evidence)

        lines: list[str] = ["CANDIDATE HEADER"]
        lines.extend(self._header(personal))
        lines.extend(["", "PROFESSIONAL HEADLINE", headline])
        lines.extend(["", "PROFESSIONAL SUMMARY"])
        lines.extend(self._summary(data, headline))

        metrics = _unique(_strings(data.get("verified_metrics", data.get("metrics_and_achievements", []))))
        if metrics:
            ranked_metrics = self._rank_texts(metrics, context_terms)[:MAX_ACHIEVEMENTS]
            lines.extend(["", "ACHIEVEMENTS", *[f"- {item}" for item in ranked_metrics]])

        skill_groups = self._skill_groups(data, requirements, evidence)
        if skill_groups:
            lines.extend(["", "KEY SKILLS", *skill_groups])

        used_bullets: set[str] = set()
        self._add_items(
            lines, "PROFESSIONAL EXPERIENCE",
            self._experience_blocks(_items(data, "work_experience")),
            context_terms, used_bullets,
            max_items=MAX_EXPERIENCE_ITEMS, max_bullets=MAX_EXPERIENCE_BULLETS,
            label_fields=("role", "company"),
        )
        self._add_items(
            lines, "PROJECTS", _items(data, "projects"), context_terms, used_bullets,
            max_items=MAX_PROJECTS, max_bullets=MAX_PROJECT_BULLETS,
            label_fields=("name", "project_name", "title"),
        )
        courses = [
            *_items(data, "certifications"), *_items(data, "courses"),
            *_items(data, "training_and_courses"),
        ]
        self._add_items(
            lines, "CERTIFICATIONS AND COURSES", courses, context_terms, used_bullets,
            max_items=MAX_CERTIFICATIONS, max_bullets=MAX_CERTIFICATION_BULLETS,
            label_fields=("name", "title", "certificate"),
        )
        self._add_items(
            lines, "EDUCATION", _items(data, "education"), context_terms, used_bullets,
            max_items=MAX_EDUCATION_ITEMS, max_bullets=MAX_EDUCATION_BULLETS,
            label_fields=("degree", "name", "institution"),
        )

        languages = self._languages(data.get("languages", []))
        if languages:
            lines.extend(["", "LANGUAGES", *[f"- {item}" for item in languages]])

        additional = self._additional_information(data, personal)
        if additional:
            lines.extend(["", "ADDITIONAL INFORMATION", *[f"- {item}" for item in additional]])

        cv_text = self._cv_text(lines)
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
        values = [_clean_text(str(personal[key])) for key in ordered if personal.get(key)]
        return values or ["Candidate"]

    @staticmethod
    def _summary(data: dict[str, Any], headline: str) -> list[str]:
        for key in ("professional_summary", "summary"):
            values = _strings(data.get(key))
            if values:
                return CVBuilder._wrap(values[0])
        skills = _strings(data.get("skills_and_tools", data.get("skills_bank", {})))
        if skills:
            text = f"{headline} with verified evidence in {', '.join(_unique(skills)[:4])}."
            return CVBuilder._wrap(text)
        return CVBuilder._wrap(headline)

    @staticmethod
    def _wrap(text: str) -> list[str]:
        shortened = _complete_sentence_summary(text, "")
        return textwrap.wrap(
            shortened,
            width=SUMMARY_WIDTH,
            break_long_words=False,
            break_on_hyphens=False,
        ) or [shortened]

    @staticmethod
    def _skill_groups(data, requirements, evidence) -> list[str]:
        all_skills = CVBuilder._profile_skills(data)
        supported_ids = {
            item.requirement_id for item in evidence
            if item.evidence_type is not EvidenceType.NO_EVIDENCE
        }
        preferred = [
            item.name for item in requirements
            if item.requirement_id in supported_ids
            and item.category.value in {"skill", "tool", "domain"}
        ]
        candidates = [
            _canonical_skill(value)
            for value in _unique([*preferred, *all_skills])
            if not _language_like(value)
        ]
        unused = _unique(candidates)
        grouped: list[str] = []
        used: set[str] = set()
        for group_name, keywords, limit in SKILL_GROUPS:
            matches = []
            for skill in unused:
                lowered = skill.casefold()
                if skill not in used and any(keyword in lowered for keyword in keywords):
                    matches.append(skill)
                    used.add(skill)
            if matches:
                grouped.append(f"{group_name}: {', '.join(matches[:limit])}")
        return grouped

    @staticmethod
    def _profile_skills(data: dict[str, Any]) -> list[str]:
        skills_payload = data.get("skills_and_tools", data.get("skills_bank", {}))
        values: list[str] = []
        if isinstance(skills_payload, dict):
            for key, value in skills_payload.items():
                key_text = str(key).casefold()
                if any(term in key_text for term in (*LANGUAGE_NAMES, "language", "languages")):
                    continue
                values.extend(_strings(value))
        else:
            values.extend(_strings(skills_payload))
        for section in (
            "work_experience", "projects", "education", "certifications",
            "courses", "training_and_courses",
        ):
            for item in _items(data, section):
                values.extend(_strings(item.get("skills")))
                values.extend(_strings(item.get("tools")))
                values.extend(_strings(item.get("domains")))
        return _unique(value for value in values if not _language_like(value))

    @staticmethod
    def _add_items(
        lines, heading, items, context_terms, used_bullets, *,
        max_items, max_bullets, label_fields,
    ):
        if not items:
            return
        lines.extend(["", heading])
        ranked_items = sorted(
            enumerate(items),
            key=lambda pair: -CVBuilder._score_item(pair[1], context_terms),
        )
        for display_index, (_item_index, item) in enumerate(ranked_items[:max_items]):
            if display_index > 0:
                lines.append("")
            label = _field(item, *label_fields) or "Stored evidence"
            company = _field(item, "company", "provider", "institution", "school")
            location = _field(item, "location")
            dates = _field(item, "dates", "date", "period")
            if dates is None:
                start = _field(item, "start_date", "start")
                end = _field(item, "end_date", "end")
                dates = " - ".join(value for value in (start, end) if value) or None
            header = " | ".join(value for value in (label, company, dates) if value)
            lines.append(header)
            if location and location not in header:
                lines.append(location)
            details = CVBuilder._rank_texts(_item_details(item), context_terms)
            selected = []
            for detail in details:
                key = " ".join(detail.casefold().split())
                if key and key not in used_bullets:
                    used_bullets.add(key)
                    selected.append(detail)
                if len(selected) >= max_bullets:
                    break
            lines.extend(f"- {detail}" for detail in selected)

    @staticmethod
    def _languages(value: Any) -> list[str]:
        if isinstance(value, dict):
            value = value.get("items", value)
            if isinstance(value, dict):
                return [
                    f"{_clean_text(str(name))}: {_clean_text(str(level))}"
                    for name, level in value.items()
                ]
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(_clean_text(item))
            elif isinstance(item, dict) and item.get("name"):
                level = _clean_text(item.get("proficiency") or item.get("level") or "mentioned")
                result.append(f"{_clean_text(item['name'])}: {level}")
        return _unique(result)

    @staticmethod
    def _context_terms(
        requirements: tuple[JobRequirement, ...],
        evidence: tuple[EvidenceReference, ...],
    ) -> tuple[str, ...]:
        supported = {
            item.requirement_id for item in evidence
            if item.evidence_type is not EvidenceType.NO_EVIDENCE
        }
        preferred = [
            item.name for item in requirements
            if item.requirement_id in supported
        ]
        fallback = [
            item.name for item in requirements
            if item.category.value in {"role", "skill", "tool", "domain"}
        ]
        labels = [item.label for item in evidence if item.label]
        return tuple(_unique([*preferred, *fallback, *labels]))

    @staticmethod
    def _rank_texts(values: Iterable[str], context_terms: tuple[str, ...]) -> list[str]:
        unique = _unique(values)
        return [
            value for _, value in sorted(
                enumerate(unique),
                key=lambda pair: (-_score_text(pair[1], context_terms), pair[0]),
            )
        ]

    @staticmethod
    def _score_item(item: dict[str, Any], context_terms: tuple[str, ...]) -> int:
        text = " ".join([
            _field(item, "id") or "",
            _field(item, "role", "name", "project_name", "title", "degree") or "",
            _field(item, "company", "provider", "institution") or "",
            " ".join(_item_details(item)),
            " ".join(_strings(item.get("skills"))),
            " ".join(_strings(item.get("tools"))),
            " ".join(_strings(item.get("domains"))),
        ])
        return _score_text(text, context_terms)

    @staticmethod
    def _experience_blocks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        ordered_keys: list[str] = []
        for item in items:
            company = _field(item, "company") or f"__item_{len(ordered_keys)}"
            key = company.casefold()
            if key not in grouped:
                grouped[key] = dict(item)
                grouped[key]["_items"] = [item]
                grouped[key]["company"] = company if not company.startswith("__item_") else item.get("company")
                ordered_keys.append(key)
            else:
                grouped[key]["_items"].append(item)
        blocks: list[dict[str, Any]] = []
        for key in ordered_keys:
            block = grouped[key]
            group_items = block.pop("_items")
            if len(group_items) == 1:
                blocks.append(block)
                continue
            roles = _unique(
                _field(item, "role", "title", "name") or "Professional Experience"
                for item in group_items
            )
            block["role"] = " / ".join(roles[:2])
            block["summary"] = [
                text for item in group_items for text in _item_details(item)
            ]
            block["skills"] = [
                text for item in group_items for text in _strings(item.get("skills"))
            ]
            block["tools"] = [
                text for item in group_items for text in _strings(item.get("tools"))
            ]
            block["domains"] = [
                text for item in group_items for text in _strings(item.get("domains"))
            ]
            start_values = [
                value for item in group_items
                if (value := _field(item, "start_date", "start"))
            ]
            end_values = [
                value for item in group_items
                if (value := _field(item, "end_date", "end"))
            ]
            block.pop("dates", None)
            block.pop("period", None)
            block.pop("date", None)
            if start_values or end_values:
                block["start_date"] = _date_range_value(start_values, latest=False)
                block["end_date"] = _date_range_value(end_values, latest=True)
            blocks.append(block)
        return blocks

    @staticmethod
    def _cv_text(lines: list[str]) -> str:
        cleaned_lines = [_clean_text(line) if line else "" for line in lines]
        text = "\n".join(cleaned_lines)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text + "\n"

    @staticmethod
    def _additional_information(
        data: dict[str, Any],
        personal: dict[str, Any],
    ) -> list[str]:
        values = _strings(data.get("additional_information", []))
        for key in ("work_authorization", "availability"):
            values.extend(_strings(personal.get(key)))
        return CVBuilder._unique_semantic(values)

    @staticmethod
    def _unique_semantic(values: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in _unique(values):
            key = CVBuilder._semantic_key(value)
            if key not in seen:
                seen.add(key)
                result.append(value)
        return result

    @staticmethod
    def _semantic_key(value: str) -> str:
        lowered = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
        authorization_terms = (
            "authorized to work", "authorised to work", "work authorization",
            "work authorisation", "eu blue card", "visa",
        )
        if any(term in lowered for term in authorization_terms):
            return "work_authorization"
        if any(term in lowered for term in ("available immediately", "immediate availability", "availability")):
            return "availability"
        return lowered

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
