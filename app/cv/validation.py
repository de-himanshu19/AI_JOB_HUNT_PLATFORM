"""Conservative deterministic validators for CV text and AI derivatives."""

from __future__ import annotations

import re
from dataclasses import dataclass


REQUIRED_SECTIONS = (
    "CANDIDATE HEADER", "PROFESSIONAL HEADLINE", "PROFESSIONAL SUMMARY",
    "KEY SKILLS", "PROFESSIONAL EXPERIENCE",
)
INTERNAL_LABELS = (
    "evidence type", "official roles included", "selected evidence",
    "risk calculation", "rule ids", "profile hashes", "database ids",
)
TECHNOLOGIES = {
    "sql", "python", "power bi", "tableau", "excel", "sap", "s/4hana",
    "java", "javascript", "typescript", "aws", "azure", "gcp", "docker",
    "kubernetes", "salesforce", "servicenow", "pandas", "spark", "snowflake",
}
OWNERSHIP_TERMS = ("led", "owned", "managed", "architected", "expert", "fluent")
SENIORITY_TERMS = ("senior", "lead", "manager", "head", "director", "principal")
SENSITIVE_CLAIMS = (
    "work authorized", "work authorisation", "no visa required", "citizen",
    "immediately available", "s/4hana migration", "sap customization",
)
LANGUAGES = ("german", "english", "french", "spanish", "italian")
LANGUAGE_LEVELS = (
    "basic", "a1", "a2", "b1", "b2", "c1", "c2", "business",
    "professional", "fluent", "excellent", "native",
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {"valid": self.valid, "errors": list(self.errors)}


class CVValidator:
    def validate_rule_based(
        self, text: str, protected_facts: tuple[str, ...]
    ) -> ValidationResult:
        errors = self._structure(text)
        source = "\n".join(protected_facts)
        new_numbers = self._numbers(text) - self._numbers(source)
        if new_numbers:
            errors.append("unsupported numbers: " + ", ".join(sorted(new_numbers)))
        name = protected_facts[0] if protected_facts else None
        if name and name not in text:
            errors.append("candidate name is missing or changed")
        return ValidationResult(not errors, tuple(errors))

    def validate_ai(
        self, text: str, rule_text: str, protected_facts: tuple[str, ...]
    ) -> ValidationResult:
        errors = self._structure(text)
        source = "\n".join(protected_facts)
        for fact in protected_facts:
            if fact in rule_text and fact not in text:
                errors.append(f"protected fact removed or changed: {fact[:80]}")
        new_numbers = self._numbers(text) - self._numbers(source)
        if new_numbers:
            errors.append("unsupported numbers: " + ", ".join(sorted(new_numbers)))
        source_lower = source.casefold()
        text_lower = text.casefold()
        new_tools = sorted(term for term in TECHNOLOGIES if term in text_lower and term not in source_lower)
        if new_tools:
            errors.append("unsupported tools or technologies: " + ", ".join(new_tools))
        for term in OWNERSHIP_TERMS:
            if term in text_lower and term not in rule_text.casefold():
                errors.append(f"unsupported stronger wording: {term}")
        for term in (*SENIORITY_TERMS, *SENSITIVE_CLAIMS):
            if term in text_lower and term not in rule_text.casefold():
                errors.append(f"unsupported sensitive claim: {term}")
        for language in LANGUAGES:
            for level in LANGUAGE_LEVELS:
                pattern = rf"\b{language}\b[^\n]{{0,30}}\b{level}\b"
                if re.search(pattern, text_lower) and not re.search(
                    pattern, rule_text.casefold()
                ):
                    errors.append(
                        f"unsupported language proficiency: {language} {level}"
                    )
        allowed = (source + "\n" + rule_text).casefold()
        for phrase in self._proper_nouns(text):
            if phrase.casefold() not in allowed:
                errors.append(f"unsupported named fact: {phrase}")
        return ValidationResult(not errors, tuple(errors))

    @staticmethod
    def _structure(text: str) -> list[str]:
        if not isinstance(text, str) or not text.strip():
            return ["output is empty or malformed"]
        headings = {line.strip().upper() for line in text.splitlines()}
        errors = [f"missing section: {section}" for section in REQUIRED_SECTIONS if section not in headings]
        lowered = text.casefold()
        errors.extend(f"internal label exposed: {label}" for label in INTERNAL_LABELS if label in lowered)
        return errors

    @staticmethod
    def _numbers(text: str) -> set[str]:
        return set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?%?\+?(?!\w)", text))

    @staticmethod
    def _proper_nouns(text: str) -> set[str]:
        phrases = set(re.findall(
            r"\b[A-Z][A-Za-z0-9&+./-]+(?:\s+[A-Z][A-Za-z0-9&+./-]+)+\b",
            text,
        ))
        return {phrase for phrase in phrases if not phrase.isupper()}
