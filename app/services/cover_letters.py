"""Local, evidence-backed cover-letter drafts with optional validated AI polish."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Any
from uuid import UUID, uuid4

from app.db.connection import Database
from app.db.repositories import CandidateProfileRepository
from app.domain.candidate import CandidateEvidenceProfile
from app.domain.enums import DescriptionCompleteness
from app.integrations.ai.base import AIProvider


COVER_LETTER_VERSION = "m24-cover-letter-v1"
DEFAULT_TEMPLATE = """${candidate_name}

Dear Hiring Team,

I am applying for the ${job_title} position at ${company}${location_phrase}. ${relevant_experience}

My relevant skills include ${relevant_skills}. I would welcome the opportunity to discuss how this evidence could support your team.

${availability}${work_authorization}

${closing}
${candidate_name}
"""
STRONGER_WORDS = ("led", "owned", "managed", "expert", "senior", "advanced", "architected", "directed")


@dataclass(frozen=True)
class CoverLetterResult:
    artifact_id: str
    source: str
    text: str
    output_path: str
    metadata_path: str
    profile_id: str
    job_id: str
    template_name: str
    validated: bool
    created_at: str
    warnings: tuple[str, ...] = ()
    parent_artifact_id: str | None = None
    validation_errors: tuple[str, ...] = ()

    def as_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        payload["validation_errors"] = list(self.validation_errors)
        return payload


class CoverLetterService:
    """Generate local drafts; never submit, upload, or send them."""

    def __init__(
        self,
        database: Database,
        *,
        output_dir: Path,
        template_dir: Path,
        provider: AIProvider | None = None,
        now: Any | None = None,
    ) -> None:
        self.database = database
        self.output_dir = output_dir
        self.template_dir = template_dir
        self.provider = provider
        self.now = now or (lambda: datetime.now(UTC))

    def templates(self) -> tuple[str, ...]:
        names = [path.name for path in self.template_dir.glob("*.md") if path.is_file()]
        return tuple(sorted(names)) or ("Built-in conservative",)

    def generate(
        self,
        *,
        profile_id: UUID | str,
        job_id: UUID | str,
        template_name: str | None = None,
        manual_description: str | None = None,
    ) -> CoverLetterResult:
        context = self._context(profile_id, job_id)
        completeness = context["completeness"]
        warnings: list[str] = []
        if manual_description and manual_description.strip():
            description = manual_description.strip()
            description_source = "pasted_full_description"
        else:
            description = context["description"] or ""
            description_source = f"stored_{completeness}"
            if completeness != DescriptionCompleteness.FULL.value:
                warnings.append(
                    "The stored description is incomplete; this draft is conservative and must be reviewed."
                )
        template_label, template_text = self._load_template(template_name)
        values = self._template_values(context, description)
        text = Template(template_text).safe_substitute(values).strip() + "\n"
        errors = self.validate(text, context["protected_facts"], original_text=None)
        if errors:
            raise ValueError("Cover-letter validation failed: " + "; ".join(errors))
        return self._store(
            text=text,
            source="rule_based",
            profile_id=str(profile_id),
            job_id=str(job_id),
            template_name=template_label,
            warnings=tuple(warnings),
            metadata={"description_source": description_source, "version": COVER_LETTER_VERSION},
        )

    def polish(self, artifact_id: str) -> CoverLetterResult:
        parent = self.get(artifact_id)
        if parent.source != "rule_based":
            raise ValueError("AI polish requires a rule-based cover letter")
        if self.provider is None:
            raise ValueError("AI is not configured for live cover-letter polish")
        context = self._context(parent.profile_id, parent.job_id)
        prompt = self._polish_prompt(parent.text, context["protected_facts"])
        polished = self._clean_ai_output(self.provider.polish(prompt))
        errors = self.validate(
            polished, context["protected_facts"], original_text=parent.text
        )
        if errors:
            return CoverLetterResult(
                artifact_id=parent.artifact_id,
                source=parent.source,
                text=parent.text,
                output_path=parent.output_path,
                metadata_path=parent.metadata_path,
                profile_id=parent.profile_id,
                job_id=parent.job_id,
                template_name=parent.template_name,
                validated=False,
                created_at=parent.created_at,
                warnings=parent.warnings,
                validation_errors=errors,
            )
        return self._store(
            text=polished,
            source="ai_polished",
            profile_id=parent.profile_id,
            job_id=parent.job_id,
            template_name=parent.template_name,
            parent_artifact_id=parent.artifact_id,
            metadata={
                "version": COVER_LETTER_VERSION,
                "provider": self.provider.name,
                "model": self.provider.model,
            },
        )

    def latest(self, profile_id: UUID | str, job_id: UUID | str) -> CoverLetterResult | None:
        matches = self.list(profile_id=profile_id, job_id=job_id)
        return matches[0] if matches else None

    def list(
        self, *, profile_id: UUID | str | None = None, job_id: UUID | str | None = None
    ) -> tuple[CoverLetterResult, ...]:
        if not self.output_dir.is_dir():
            return ()
        results: list[CoverLetterResult] = []
        for path in self.output_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                result = self._from_metadata(payload, path)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            if profile_id and result.profile_id != str(profile_id):
                continue
            if job_id and result.job_id != str(job_id):
                continue
            results.append(result)
        return tuple(sorted(results, key=lambda item: (item.created_at, item.artifact_id), reverse=True))

    def get(self, artifact_id: str) -> CoverLetterResult:
        path = self.output_dir / f"{artifact_id}.json"
        if not path.is_file():
            raise KeyError(f"Cover-letter artifact not found: {artifact_id}")
        return self._from_metadata(json.loads(path.read_text(encoding="utf-8")), path)

    def _context(self, profile_id: UUID | str, job_id: UUID | str) -> dict[str, Any]:
        with self.database.read_connection() as connection:
            profile = CandidateProfileRepository(connection).get(profile_id)
            job = connection.execute("SELECT * FROM jobs WHERE id = ?", (str(job_id),)).fetchone()
            description = connection.execute(
                """SELECT raw_text, completeness FROM job_descriptions
                WHERE job_id = ? ORDER BY fetched_at DESC, created_at DESC, id DESC LIMIT 1""",
                (str(job_id),),
            ).fetchone()
        if profile is None:
            raise KeyError(f"Candidate profile not found: {profile_id}")
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        evidence = CandidateEvidenceProfile.from_candidate_profile(profile)
        personal = profile.profile_data.get("personal_info", {})
        protected = tuple(
            str(value).strip()
            for key in ("full_name", "email", "phone", "linkedin", "github", "location", "work_authorization", "availability")
            if (value := personal.get(key)) and str(value).strip()
        )
        return {
            "profile": profile,
            "evidence": evidence,
            "personal": personal,
            "job": dict(job),
            "description": description["raw_text"] if description else None,
            "completeness": description["completeness"] if description else "missing",
            "protected_facts": protected,
        }

    @staticmethod
    def _template_values(context: dict[str, Any], description: str) -> dict[str, str]:
        job, evidence, personal = context["job"], context["evidence"], context["personal"]
        terms = set(re.findall(r"[a-zA-Z][a-zA-Z+#.-]{1,}", description.casefold()))
        skills = [item for item in (*evidence.skills, *evidence.tools) if item.casefold() in terms]
        if not skills:
            skills = list((*evidence.skills, *evidence.tools)[:5])
        experience = next((item.summary for item in evidence.work_experience if item.summary), "My background includes evidence-backed analytical and operational work.")
        location = str(job.get("location_raw") or "").strip()
        availability = str(personal.get("availability") or "").strip()
        authorization = str(personal.get("work_authorization") or "").strip()
        return {
            "candidate_name": str(personal.get("full_name") or context["profile"].display_name),
            "company": str(job.get("company_raw") or "your organization"),
            "job_title": str(job.get("title_raw") or "the advertised role"),
            "location": location,
            "location_phrase": f" in {location}" if location else "",
            "relevant_experience": experience,
            "relevant_skills": ", ".join(dict.fromkeys(skills)) or "careful analysis, validation, and reporting",
            "availability": f"Availability: {availability}. " if availability else "",
            "work_authorization": f"Work authorization: {authorization}." if authorization else "",
            "closing": "Kind regards,",
        }

    def _load_template(self, template_name: str | None) -> tuple[str, str]:
        if not template_name or template_name == "Built-in conservative":
            return "Built-in conservative", DEFAULT_TEMPLATE
        safe_name = Path(template_name).name
        path = self.template_dir / safe_name
        if not path.is_file() or path.suffix.casefold() != ".md":
            raise ValueError("Selected cover-letter template was not found")
        return safe_name, path.read_text(encoding="utf-8")

    def _store(self, *, text: str, source: str, profile_id: str, job_id: str, template_name: str, warnings: tuple[str, ...] = (), parent_artifact_id: str | None = None, metadata: dict[str, object] | None = None) -> CoverLetterResult:
        artifact_id = str(uuid4())
        created_at = self.now().isoformat()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        text_path = self.output_dir / f"{artifact_id}.txt"
        metadata_path = self.output_dir / f"{artifact_id}.json"
        text_path.write_text(text, encoding="utf-8")
        payload = {
            "artifact_id": artifact_id, "source": source, "profile_id": profile_id,
            "job_id": job_id, "template_name": template_name, "validated": True,
            "created_at": created_at, "warnings": list(warnings),
            "parent_artifact_id": parent_artifact_id, "text_path": str(text_path.resolve(strict=False)),
            **(metadata or {}),
        }
        try:
            metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except BaseException:
            text_path.unlink(missing_ok=True)
            raise
        return CoverLetterResult(
            artifact_id=artifact_id, source=source, text=text,
            output_path=str(text_path.resolve(strict=False)), metadata_path=str(metadata_path.resolve(strict=False)),
            profile_id=profile_id, job_id=job_id, template_name=template_name,
            validated=True, created_at=created_at, warnings=warnings,
            parent_artifact_id=parent_artifact_id,
        )

    def _from_metadata(self, payload: dict[str, Any], path: Path) -> CoverLetterResult:
        text_path = Path(payload["text_path"])
        text = text_path.read_text(encoding="utf-8")
        return CoverLetterResult(
            artifact_id=str(payload["artifact_id"]), source=str(payload["source"]), text=text,
            output_path=str(text_path), metadata_path=str(path.resolve(strict=False)),
            profile_id=str(payload["profile_id"]), job_id=str(payload["job_id"]),
            template_name=str(payload["template_name"]), validated=bool(payload["validated"]),
            created_at=str(payload["created_at"]), warnings=tuple(payload.get("warnings", ())),
            parent_artifact_id=payload.get("parent_artifact_id"),
        )

    @staticmethod
    def validate(text: str, protected_facts: tuple[str, ...], *, original_text: str | None) -> tuple[str, ...]:
        errors: list[str] = []
        salutations = tuple(
            line.strip() for line in text.splitlines() if line.strip().startswith("Dear ")
        )
        if not text.strip() or salutations != ("Dear Hiring Team,",):
            errors.append("required conservative greeting is missing")
        for fact in protected_facts:
            if original_text and fact in original_text and fact not in text:
                errors.append(f"protected fact removed or changed: {fact}")
        if original_text:
            original_words = original_text.casefold()
            candidate_words = text.casefold()
            for word in STRONGER_WORDS:
                if re.search(rf"\b{re.escape(word)}\b", candidate_words) and not re.search(rf"\b{re.escape(word)}\b", original_words):
                    errors.append(f"unsupported stronger wording: {word}")
            date_pattern = r"\b(?:\d{1,2}[./-])?\d{1,2}[./-]\d{2,4}|\b20\d{2}\b"
            original_dates = set(re.findall(date_pattern, original_text))
            if original_dates != set(re.findall(date_pattern, text)):
                errors.append("protected date removed or changed")
            introduced_names = (
                CoverLetterService._named_tokens(text)
                - CoverLetterService._named_tokens(original_text)
            )
            if introduced_names:
                errors.append(
                    "unsupported named facts: " + ", ".join(sorted(introduced_names))
                )
        return tuple(errors)

    @staticmethod
    def _named_tokens(text: str) -> set[str]:
        allowed_editorial = {
            "Availability", "Authorization", "Dear", "Hiring", "I", "Kind",
            "My", "Regards", "Team", "Work",
        }
        return {
            token
            for token in re.findall(r"\b(?:[A-Z][A-Za-z0-9+#.-]{1,}|[A-Z]{2,})\b", text)
            if token not in allowed_editorial
        }

    @staticmethod
    def _clean_ai_output(text: str) -> str:
        value = text.strip()
        if value.startswith("```"):
            lines = value.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines.pop()
            value = "\n".join(lines).strip()
        return value + "\n"

    @staticmethod
    def _polish_prompt(text: str, protected_facts: tuple[str, ...]) -> str:
        facts = "\n".join(f"- {fact}" for fact in protected_facts) or "- None provided"
        return (
            "Conservatively polish this cover letter in English. Return only the letter text. "
            "Do not use markdown fences. Keep 'Dear Hiring Team' and do not invent a recruiter. "
            "Do not add or change employers, job titles, dates, metrics, degrees, tools, language "
            "levels, contact details, work authorization, availability, or company facts. Do not "
            "add stronger wording such as led, owned, managed, expert, senior, or advanced. "
            "If unsure, preserve the original wording. Protected facts must remain unchanged:\n"
            f"{facts}\n\nRULE-BASED COVER LETTER\n{text}"
        )
