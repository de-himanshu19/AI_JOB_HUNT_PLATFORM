"""Milestone 7 orchestration for authoritative and optional AI CV artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from uuid import UUID, uuid4

import requests

from app.config import Settings
from app.cv.builder import (
    CV_BUILDER_CONTENT_VERSION,
    FORMATTER_VERSION,
    GENERATOR_VERSION,
    CVBuilder,
)
from app.cv.storage import ArtifactStore
from app.cv.validation import CVValidator
from app.db.connection import Database
from app.db.repositories import (
    CVGenerationArtifactRepository,
    CandidateProfileRepository,
    JobDescriptionRepository,
    JobRepository,
)
from app.domain.analysis import EvidenceType
from app.domain.candidate import CandidateEvidenceProfile
from app.domain.cv import (
    AIAttemptStatus,
    CVAIAttempt,
    CVGenerationArtifact,
    GenerationMode,
)
from app.domain.enums import ArtifactSource, DescriptionCompleteness
from app.integrations.ai.base import AIProvider
from app.services.analysis_rules import AnalysisRules
from app.services.evidence import EvidenceMatcher
from app.services.fit_analysis import FitAnalysisService
from app.services.requirements import RequirementsAnalyzer


PROMPT_VERSION = "m7-cv-polish-v1"


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CVGenerationResult:
    rule_based_artifact: CVGenerationArtifact
    cache_hit: bool
    ai_status: str = "not_requested"
    ai_artifact: CVGenerationArtifact | None = None
    ai_failure_category: str | None = None


class CVGenerationService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        rules: AnalysisRules,
        *,
        provider: AIProvider | None = None,
    ):
        self.database = database
        self.settings = settings
        self.rules = rules
        self.provider = provider
        self.builder = CVBuilder()
        self.validator = CVValidator()
        self.store = ArtifactStore(settings.cv_artifact_root)

    def generate_for_job(
        self,
        job_id: UUID | str,
        profile_id: UUID | str,
        *,
        ai_polish: bool = False,
        live_ai: bool = False,
        force_regenerate: bool = False,
    ) -> CVGenerationResult:
        self._validate_ai_flags(ai_polish, live_ai)
        with self.database.read_connection() as connection:
            job = JobRepository(connection).get(job_id)
            profile = CandidateProfileRepository(connection).get(profile_id)
            if job is None:
                raise KeyError(f"Job not found: {job_id}")
            if profile is None:
                raise KeyError(f"Candidate profile not found: {profile_id}")
            description = JobDescriptionRepository(connection).latest_for_job(job.id)
        if description is None or description.completeness is not DescriptionCompleteness.FULL:
            completeness = description.completeness.value if description else "missing"
            raise ValueError(
                f"Stored-job CV generation requires a full description; found {completeness}. "
                "Use cv generate-manual --description-file <path>."
            )

        execution = FitAnalysisService(self.database, self.rules).analyze_job(
            job.id, profile.id
        )
        analysis = execution.analysis
        if (
            analysis.description_id != description.id
            or analysis.description_content_hash != description.content_hash
            or analysis.profile_version != profile.version
            or analysis.analyzer_version != self.rules.analyzer_version
            or analysis.rules_version != self.rules.rules_version
            or analysis.description_completeness != "full"
        ):
            raise RuntimeError("Deterministic analysis did not match the selected inputs")

        with self.database.read_connection() as connection:
            row = connection.execute(
                """SELECT cluster_id FROM job_duplicate_links WHERE job_id = ?
                ORDER BY created_at DESC, id LIMIT 1""",
                (str(job.id),),
            ).fetchone()
        cluster_id = UUID(row["cluster_id"]) if row else None
        provenance = {
            "generation_mode": "stored_job", "job_id": str(job.id),
            "logical_cluster_id": str(cluster_id) if cluster_id else None,
            "description_id": str(description.id),
            "description_hash": description.content_hash,
            "profile_id": str(profile.id), "profile_version": str(profile.version),
            "profile_hash": profile.content_hash, "analysis_id": str(analysis.id),
            "analyzer_version": analysis.analyzer_version,
            "rules_version": analysis.rules_version,
            "generator_version": GENERATOR_VERSION,
            "formatter_version": FORMATTER_VERSION,
            "builder_content_version": CV_BUILDER_CONTENT_VERSION,
        }
        build = self.builder.build(
            profile, tuple(analysis.requirements), tuple(analysis.evidence),
            missing_requirements=analysis.missing_skills,
            risk_flags=analysis.risk_flags,
            description_completeness="full", provenance=provenance,
        )
        identity = self._identity(
            mode=GenerationMode.STORED_JOB,
            description_hash=description.content_hash,
            description_id=str(description.id), profile=profile,
            analysis_id=str(analysis.id), analyzer_version=analysis.analyzer_version,
            rules_version=analysis.rules_version,
            force_regeneration_id=str(uuid4()) if force_regenerate else None,
        )
        artifact, cache_hit = self._authoritative_artifact(
            build, identity=identity, profile=profile,
            mode=GenerationMode.STORED_JOB, description_hash=description.content_hash,
            job_id=job.id, cluster_id=cluster_id, description_id=description.id,
            analysis_id=analysis.id, analyzer_version=analysis.analyzer_version,
            rules_version=analysis.rules_version,
        )
        return self._maybe_polish(
            artifact, build.cv_text, build.evidence_report_text,
            build.protected_facts, cache_hit, ai_polish,
        )

    def generate_manual_file(
        self,
        path: Path,
        profile_id: UUID | str,
        *,
        ai_polish: bool = False,
        live_ai: bool = False,
        force_regenerate: bool = False,
    ) -> CVGenerationResult:
        resolved = path.expanduser().resolve(strict=False)
        if resolved.suffix.casefold() not in {".txt", ".md"}:
            raise ValueError("Manual JD must be a readable .txt or .md file")
        if not resolved.is_file():
            raise FileNotFoundError(f"Manual JD file not found: {resolved}")
        size = resolved.stat().st_size
        if size == 0 or size > self.settings.cv_manual_max_bytes:
            raise ValueError(
                f"Manual JD must contain 1-{self.settings.cv_manual_max_bytes} bytes"
            )
        try:
            text = resolved.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("Manual JD must use UTF-8 text encoding") from error
        return self.generate_manual_text(
            text, profile_id, ai_polish=ai_polish, live_ai=live_ai,
            force_regenerate=force_regenerate,
        )

    def generate_manual_text(
        self,
        text: str,
        profile_id: UUID | str,
        *,
        ai_polish: bool = False,
        live_ai: bool = False,
        force_regenerate: bool = False,
    ) -> CVGenerationResult:
        self._validate_ai_flags(ai_polish, live_ai)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Manual JD text must not be empty")
        if len(text.encode("utf-8")) > self.settings.cv_manual_max_bytes:
            raise ValueError("Manual JD exceeds CV_MANUAL_MAX_BYTES")
        text = text.strip()
        description_hash = _hash_text(text)
        with self.database.read_connection() as connection:
            profile = CandidateProfileRepository(connection).get(profile_id)
        if profile is None:
            raise KeyError(f"Candidate profile not found: {profile_id}")
        requirements = RequirementsAnalyzer().analyze(text)
        evidence, risks = EvidenceMatcher().match(
            requirements, CandidateEvidenceProfile.from_candidate_profile(profile)
        )
        missing = tuple(
            requirement.name for requirement in requirements
            if next(
                item for item in evidence
                if item.requirement_id == requirement.requirement_id
            ).evidence_type is EvidenceType.NO_EVIDENCE
        )
        provenance = {
            "generation_mode": "manual_jd", "job_id": None,
            "logical_cluster_id": None, "description_id": None,
            "description_hash": description_hash,
            "profile_id": str(profile.id), "profile_version": str(profile.version),
            "profile_hash": profile.content_hash, "analysis_id": None,
            "analyzer_version": self.rules.analyzer_version,
            "rules_version": self.rules.rules_version,
            "generator_version": GENERATOR_VERSION,
            "formatter_version": FORMATTER_VERSION,
            "builder_content_version": CV_BUILDER_CONTENT_VERSION,
        }
        build = self.builder.build(
            profile, requirements, evidence, missing_requirements=missing,
            risk_flags=risks, description_completeness="full", provenance=provenance,
        )
        identity = self._identity(
            mode=GenerationMode.MANUAL_JD, description_hash=description_hash,
            description_id=None, profile=profile, analysis_id=None,
            analyzer_version=self.rules.analyzer_version,
            rules_version=self.rules.rules_version,
            force_regeneration_id=str(uuid4()) if force_regenerate else None,
        )
        artifact, cache_hit = self._authoritative_artifact(
            build, identity=identity, profile=profile,
            mode=GenerationMode.MANUAL_JD, description_hash=description_hash,
            analyzer_version=self.rules.analyzer_version,
            rules_version=self.rules.rules_version,
        )
        return self._maybe_polish(
            artifact, build.cv_text, build.evidence_report_text,
            build.protected_facts, cache_hit, ai_polish,
        )

    def list_artifacts(self, job_id: UUID | str | None = None):
        with self.database.read_connection() as connection:
            return CVGenerationArtifactRepository(connection).list(job_id=job_id)

    def artifact_details(self, artifact_id: UUID | str):
        with self.database.read_connection() as connection:
            repository = CVGenerationArtifactRepository(connection)
            artifact = repository.get(artifact_id)
            if artifact is None:
                raise KeyError(f"CV artifact not found: {artifact_id}")
            attempts = repository.list_ai_attempts(
                artifact.id if artifact.source is ArtifactSource.RULE_BASED
                else artifact.parent_rule_based_artifact_id
            )
        return artifact, attempts

    def _identity(self, **values) -> str:
        profile = values.pop("profile")
        return _stable_hash({
            **values, "profile_id": str(profile.id),
            "profile_version": profile.version, "profile_hash": profile.content_hash,
            "generator_version": GENERATOR_VERSION,
            "formatter_version": FORMATTER_VERSION,
            "builder_content_version": CV_BUILDER_CONTENT_VERSION,
            "rules_configuration_hash": _stable_hash(self.rules.model_dump(mode="json")),
        })

    def _authoritative_artifact(
        self, build, *, identity, profile, mode, description_hash,
        analyzer_version, rules_version, job_id=None, cluster_id=None,
        description_id=None, analysis_id=None,
    ):
        with self.database.read_connection() as connection:
            cached = CVGenerationArtifactRepository(connection).get_rule_based_by_identity(identity)
        if cached is not None:
            self._verify_cached(cached)
            return cached, True
        validation = self.validator.validate_rule_based(build.cv_text, build.protected_facts)
        if not validation.valid:
            raise ValueError("Rule-based CV failed validation: " + "; ".join(validation.errors))
        artifact_id = uuid4()
        cv_path, report_path = self.store.write_bundle(
            artifact_id, build.cv_text, build.evidence_report_text
        )
        artifact = CVGenerationArtifact(
            id=artifact_id, job_id=job_id, logical_cluster_id=cluster_id,
            description_id=description_id, description_content_hash=description_hash,
            profile_id=profile.id, profile_version=profile.version,
            profile_content_hash=profile.content_hash, analysis_id=analysis_id,
            analyzer_version=analyzer_version, rules_version=rules_version,
            generator_version=GENERATOR_VERSION, formatter_version=FORMATTER_VERSION,
            generation_mode=mode, generation_identity=identity,
            artifact_path=cv_path, evidence_report_path=report_path,
            content_hash=_hash_text(build.cv_text),
            evidence_report_hash=_hash_text(build.evidence_report_text),
            validated=True, validation_result=validation.as_dict(),
        )
        try:
            with self.database.transaction() as connection:
                CVGenerationArtifactRepository(connection).create(artifact)
        except sqlite3.IntegrityError:
            self.store.cleanup(cv_path, report_path)
            with self.database.read_connection() as connection:
                winner = CVGenerationArtifactRepository(connection).get_rule_based_by_identity(identity)
            if winner is None:
                raise
            self._verify_cached(winner)
            return winner, True
        except BaseException:
            self.store.cleanup(cv_path, report_path)
            raise
        return artifact, False

    def _maybe_polish(self, artifact, rule_text, report_text, facts, cache_hit, requested):
        if not requested:
            return CVGenerationResult(artifact, cache_hit)
        provider = self.provider
        if provider is None:
            return self._record_ai_failure(
                artifact,
                SimpleNamespace(name="unconfigured", model="unconfigured"),
                datetime.now(UTC),
                "configuration_error",
                {"valid": False, "errors": ["configured AI provider required"]},
                cache_hit,
            )
        generated_at = datetime.now(UTC)
        prompt = self._prompt(rule_text)
        try:
            polished = provider.polish(prompt)
            if not isinstance(polished, str):
                raise ValueError("AI provider returned malformed content")
            validation = self.validator.validate_ai(polished, rule_text, facts)
            if not validation.valid:
                return self._record_ai_failure(
                    artifact, provider, generated_at, "validation_failed",
                    validation.as_dict(), cache_hit,
                )
            derivative_report = report_text + (
                "\nAI DERIVATIVE RESULT\nAI used: yes\n"
                f"Provider: {provider.name}\nModel: {provider.model}\n"
                "AI validation/fallback: validated derivative stored\n"
            )
            derivative_id = uuid4()
            cv_path, report_path = self.store.write_bundle(
                derivative_id, polished, derivative_report
            )
            derivative = artifact.model_copy(update={
                "id": derivative_id, "source": ArtifactSource.AI_POLISHED,
                "parent_rule_based_artifact_id": artifact.id,
                "generation_identity": _stable_hash({
                    "parent": str(artifact.id), "provider": provider.name,
                    "model": provider.model, "prompt": PROMPT_VERSION,
                    "content": _hash_text(polished),
                }),
                "artifact_path": cv_path, "evidence_report_path": report_path,
                "content_hash": _hash_text(polished),
                "evidence_report_hash": _hash_text(derivative_report),
                "provider": provider.name, "model": provider.model,
                "prompt_version": PROMPT_VERSION, "ai_generated_at": generated_at,
                "validation_result": validation.as_dict(), "created_at": generated_at,
            })
            attempt = CVAIAttempt(
                parent_rule_based_artifact_id=artifact.id,
                derivative_artifact_id=derivative.id, provider=provider.name,
                model=provider.model, prompt_version=PROMPT_VERSION,
                status=AIAttemptStatus.SUCCEEDED,
                evidence_report_path=report_path,
                validation_result=validation.as_dict(), generated_at=generated_at,
            )
            try:
                with self.database.transaction() as connection:
                    repository = CVGenerationArtifactRepository(connection)
                    repository.create(derivative)
                    repository.create_ai_attempt(attempt)
            except BaseException:
                self.store.cleanup(cv_path, report_path)
                raise
            return CVGenerationResult(
                artifact, cache_hit, ai_status="succeeded", ai_artifact=derivative
            )
        except requests.Timeout:
            return self._record_ai_failure(
                artifact, provider, generated_at, "timeout",
                {"valid": False, "errors": ["provider timeout"]}, cache_hit,
            )
        except (requests.RequestException, ValueError) as error:
            category = "malformed_content" if isinstance(error, ValueError) else "provider_error"
            return self._record_ai_failure(
                artifact, provider, generated_at, category,
                {"valid": False, "errors": [category]}, cache_hit,
            )
        except Exception:
            return self._record_ai_failure(
                artifact, provider, generated_at, "provider_error",
                {"valid": False, "errors": ["provider_error"]}, cache_hit,
            )

    def _record_ai_failure(self, artifact, provider, generated_at, category, result, cache_hit):
        attempt_id = uuid4()
        report_text = "\n".join((
            "PRIVATE AI ATTEMPT REPORT - NOT RECRUITER-FACING",
            f"Parent rule-based artifact: {artifact.id}",
            f"Provider: {provider.name}",
            f"Model: {provider.model}",
            f"Prompt version: {PROMPT_VERSION}",
            f"Generated at: {generated_at.isoformat()}",
            "Status: failed",
            f"Failure category: {category}",
            "Validation/fallback: authoritative rule-based artifact retained",
            *[f"- {error}" for error in result.get("errors", [])],
            "",
        ))
        report_path = self.store.write_attempt_report(attempt_id, report_text)
        attempt = CVAIAttempt(
            id=attempt_id,
            parent_rule_based_artifact_id=artifact.id, provider=provider.name,
            model=provider.model, prompt_version=PROMPT_VERSION,
            status=AIAttemptStatus.FAILED, failure_category=category,
            evidence_report_path=report_path,
            validation_result=result, generated_at=generated_at,
        )
        try:
            with self.database.transaction() as connection:
                CVGenerationArtifactRepository(connection).create_ai_attempt(attempt)
        except BaseException:
            self.store.cleanup(report_path)
            raise
        return CVGenerationResult(
            artifact, cache_hit, ai_status="failed", ai_failure_category=category
        )

    def _verify_cached(self, artifact):
        if not artifact.validated:
            raise RuntimeError("Cached artifact is not validated")
        for path, expected in (
            (artifact.artifact_path, artifact.content_hash),
            (artifact.evidence_report_path, artifact.evidence_report_hash),
        ):
            resolved = path.resolve(strict=False)
            if self.settings.cv_artifact_root.resolve(strict=False) != resolved.parent:
                raise RuntimeError("Cached artifact path is outside the configured root")
            if not resolved.is_file() or _hash_text(resolved.read_text(encoding="utf-8")) != expected:
                raise RuntimeError("Cached artifact file is missing or has changed")

    @staticmethod
    def _validate_ai_flags(ai_polish, live_ai):
        if ai_polish != live_ai:
            raise ValueError("AI polishing requires both --ai-polish and --live-ai")

    @staticmethod
    def _prompt(rule_text):
        return (
            "Polish the following plain-text CV without adding, removing, or changing "
            "facts, numbers, tools, employers, titles, dates, language levels, projects, "
            "or section headings. Return only the complete CV text.\n\n" + rule_text
        )
