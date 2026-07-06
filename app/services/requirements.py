"""Deterministic extraction of typed requirements from stored descriptions."""

from __future__ import annotations

import hashlib
import re

from app.domain.analysis import JobRequirement, RequirementCategory
from app.services.normalization import normalize_text


TOOL_RULES = {
    "SQL": ("sql",),
    "Python": ("python",),
    "Power BI": ("power bi",),
    "Excel": ("excel",),
    "Tableau": ("tableau",),
    "SAP": ("sap",),
    "SAP S/4HANA migration ownership": (
        "s 4hana migration", "s4hana migration", "sap s 4hana implementation",
    ),
}
ROLE_RULES = {
    "Data Analyst": ("data analyst", "data analytics"),
    "Business Analyst": ("business analyst", "requirements analysis"),
    "Risk Analyst": ("risk analyst",),
    "Compliance Analyst": ("compliance analyst", "aml analyst"),
    "Operations Analyst": ("operations analyst",),
    "Software Tester": ("software tester", "qa tester", "test analyst"),
}
DOMAIN_RULES = {
    "Finance and controlling direct experience": (
        "controlling experience", "finance experience", "financial controlling",
        "central reporting and controlling",
    ),
}
OPTIONAL_MARKERS = ("optional", "preferred", "nice to have", "advantage", "plus")
def _requirement_id(category: RequirementCategory, name: str, required: bool) -> str:
    key = f"{category.value}|{normalize_text(name)}|{int(required)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _sentence_for(text: str, phrase: str) -> str:
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text):
        if phrase.casefold() in sentence.casefold():
            return " ".join(sentence.split())[:500]
    return phrase


def _is_required(context: str) -> bool:
    lowered = context.casefold()
    if any(marker in lowered for marker in OPTIONAL_MARKERS):
        return False
    return True


class RequirementsAnalyzer:
    def analyze(self, description: str, *, title: str = "") -> tuple[JobRequirement, ...]:
        normalized = normalize_text(description) or ""
        combined = normalize_text(f"{title} {description}") or ""
        requirements: list[JobRequirement] = []

        for name, phrases in ROLE_RULES.items():
            phrase = next((item for item in phrases if item in combined), None)
            if phrase:
                requirements.append(self._make(name, RequirementCategory.ROLE, True, phrase, title or _sentence_for(description, phrase)))
                break

        seniority_match = re.search(r"\b(senior|lead|professional)\b", normalized)
        if seniority_match:
            context = _sentence_for(description, seniority_match.group(1))
            requirements.append(self._make(
                f"{seniority_match.group(1).title()} professional experience",
                RequirementCategory.SENIORITY, True, seniority_match.group(1), context,
            ))

        for name, phrases in TOOL_RULES.items():
            phrase = next((item for item in phrases if item in normalized), None)
            if phrase:
                context = _sentence_for(description, phrase)
                requirements.append(self._make(name, RequirementCategory.TOOL, _is_required(context), None, context))

        for name, phrases in DOMAIN_RULES.items():
            phrase = next((item for item in phrases if item in normalized), None)
            if phrase:
                context = _sentence_for(description, phrase)
                requirements.append(self._make(name, RequirementCategory.DOMAIN, _is_required(context), None, context))

        for language in ("German", "English", "French"):
            match = re.search(
                rf"\b(excellent|fluent|professional|business|basic|a[1-2]|b[1-2]|c[1-2])?\s*{language.casefold()}\b",
                normalized,
            )
            if match:
                level = (match.group(1) or "mentioned").upper()
                context = _sentence_for(description, language)
                requirements.append(self._make(
                    f"{language} {level}", RequirementCategory.LANGUAGE,
                    _is_required(context), level, context,
                ))

        unique = {item.requirement_id: item for item in requirements}
        return tuple(unique[key] for key in sorted(unique))

    @staticmethod
    def _make(name, category, required, level, context):
        return JobRequirement(
            requirement_id=_requirement_id(category, name, required),
            name=name, category=category, required=required, level=level,
            source_text=context,
        )
