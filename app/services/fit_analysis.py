"""Offline deterministic fit analysis with immutable cache identities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from app.db.connection import Database
from app.db.repositories import (
    CandidateProfileRepository,
    JobAnalysisRepository,
    JobDescriptionRepository,
    JobRepository,
)
from app.domain.analysis import (
    AnalysisAuthority,
    EvidenceType,
    JobAnalysis,
    ScoreCap,
    ScoreComponent,
)
from app.domain.candidate import CandidateEvidenceProfile
from app.domain.enums import DescriptionCompleteness
from app.services.analysis_rules import AnalysisRules
from app.services.evidence import EvidenceMatcher
from app.services.prefilter import PrefilterService
from app.services.requirements import RequirementsAnalyzer


@dataclass(frozen=True)
class AnalysisExecutionResult:
    analysis: JobAnalysis
    cache_hit: bool


def _stable_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class FitAnalysisService:
    def __init__(self, database: Database, rules: AnalysisRules):
        self.database = database
        self.rules = rules
        self.requirements = RequirementsAnalyzer()
        self.evidence = EvidenceMatcher()
        self.prefilter = PrefilterService()

    def analyze_job(
        self, job_id: UUID | str, profile_id: UUID | str
    ) -> AnalysisExecutionResult:
        with self.database.transaction() as connection:
            job = JobRepository(connection).get(job_id)
            profile = CandidateProfileRepository(connection).get(profile_id)
            if job is None:
                raise KeyError(f"Job not found: {job_id}")
            if profile is None:
                raise KeyError(f"Candidate profile not found: {profile_id}")
            description = JobDescriptionRepository(connection).latest_for_job(job.id)
            evidence_profile = CandidateEvidenceProfile.from_candidate_profile(profile)
            completeness = (
                description.completeness
                if description else DescriptionCompleteness.MISSING
            )
            input_hash = _stable_hash({
                "job_id": str(job.id),
                "description_hash": description.content_hash if description else "missing",
                "profile_hash": profile.content_hash,
                "profile_version": profile.version,
                "analyzer_version": self.rules.analyzer_version,
                "rules_version": self.rules.rules_version,
                "ranking_version": self.rules.ranking_version,
                "completeness": completeness.value,
            })
            analyses = JobAnalysisRepository(connection)
            cached = analyses.get_by_input_hash(input_hash)
            if cached is not None:
                return AnalysisExecutionResult(cached, True)

            prefilter_score, prefilter_components = self.prefilter.score(
                job, description, evidence_profile
            )
            if completeness is not DescriptionCompleteness.FULL:
                warning = (
                    f"{completeness.value} description: result is prefilter-only; "
                    "no authoritative fit score was calculated."
                )
                analysis = JobAnalysis(
                    job_id=job.id,
                    description_id=description.id if description else None,
                    description_content_hash=(description.content_hash if description else None),
                    profile_id=profile.id,
                    profile_version=profile.version,
                    analyzer_version=self.rules.analyzer_version,
                    rules_version=self.rules.rules_version,
                    ranking_version=self.rules.ranking_version,
                    analysis_input_hash=input_hash,
                    description_completeness=completeness.value,
                    authority=AnalysisAuthority.PREFILTER_ONLY,
                    completeness_warning=warning,
                    prefilter_score=prefilter_score,
                    positive_components=prefilter_components,
                    fit_reasons=(warning,),
                )
                return AnalysisExecutionResult(analyses.create(analysis), False)

            requirements = self.requirements.analyze(
                description.normalized_text or description.raw_text or "",
                title=job.title_raw,
            )
            references, risk_flags = self.evidence.match(requirements, evidence_profile)
            scored = self._score(requirements, references, risk_flags, evidence_profile)
            missing = tuple(
                requirement.name
                for requirement in requirements
                if next(
                    item for item in references
                    if item.requirement_id == requirement.requirement_id
                ).evidence_type is EvidenceType.NO_EVIDENCE
            )
            analysis = JobAnalysis(
                job_id=job.id,
                description_id=description.id,
                description_content_hash=description.content_hash,
                profile_id=profile.id,
                profile_version=profile.version,
                analyzer_version=self.rules.analyzer_version,
                rules_version=self.rules.rules_version,
                ranking_version=self.rules.ranking_version,
                analysis_input_hash=input_hash,
                description_completeness=completeness.value,
                authority=AnalysisAuthority.AUTHORITATIVE,
                requirements=requirements,
                evidence=references,
                missing_skills=missing,
                risk_flags=risk_flags,
                prefilter_score=prefilter_score,
                fit_score=scored[0],
                fit_reasons=scored[4],
                positive_components=scored[1],
                penalties=scored[2],
                score_caps=scored[3],
                language_risk_penalty=sum(
                    -item.points for item in scored[2]
                    if item.name == "language_mismatch"
                ),
            )
            return AnalysisExecutionResult(analyses.create(analysis), False)

    def get_analysis(self, analysis_id: UUID | str) -> JobAnalysis:
        with self.database.read_connection() as connection:
            analysis = JobAnalysisRepository(connection).get(analysis_id)
        if analysis is None:
            raise KeyError(f"Analysis not found: {analysis_id}")
        return analysis

    def _score(self, requirements, references, risks, profile):
        reference_by_id = {item.requirement_id: item for item in references}
        total_weight = 0.0
        earned_weight = 0.0
        for requirement in requirements:
            weight = (
                self.rules.required_requirement_weight
                if requirement.required else self.rules.optional_requirement_weight
            )
            total_weight += weight
            evidence_type = reference_by_id[requirement.requirement_id].evidence_type.value
            earned_weight += weight * self.rules.evidence_weights[evidence_type]
        evidence_score = round(100 * earned_weight / total_weight, 2) if total_weight else 0.0
        positive = [ScoreComponent(
            name="verified_evidence_coverage", points=evidence_score,
            reason=f"Weighted verified evidence coverage is {evidence_score:.2f}%.",
        )]
        role_names = {
            requirement.name.casefold() for requirement in requirements
            if requirement.category.value == "role"
        }
        target_roles = {item.casefold() for item in profile.preferences.target_role_families}
        if role_names & target_roles:
            positive.append(ScoreComponent(
                name="target_role_family", points=self.rules.target_role_bonus,
                reason="The detected role is explicitly listed in profile preferences.",
            ))

        required_missing = sum(
            1 for requirement in requirements
            if requirement.required
            and reference_by_id[requirement.requirement_id].evidence_type is EvidenceType.NO_EVIDENCE
        )
        penalties = []
        missing_penalty = min(
            self.rules.maximum_missing_penalty,
            required_missing * self.rules.required_missing_penalty,
        )
        if missing_penalty:
            penalties.append(ScoreComponent(
                name="required_missing", points=-missing_penalty,
                reason=f"{required_missing} explicitly required requirements have no evidence.",
            ))
        risk_names = []
        for risk in risks:
            risk_name = risk.split(":", 1)[0]
            if risk_name in risk_names:
                continue
            risk_names.append(risk_name)
            points = self.rules.risk_penalties.get(risk_name, 0)
            if points:
                penalties.append(ScoreComponent(name=risk_name, points=-points, reason=risk))
        caps = tuple(
            ScoreCap(name=name, maximum=self.rules.score_caps[name], reason=risk)
            for risk in risks
            for name in [risk.split(":", 1)[0]]
            if name in self.rules.score_caps
        )
        raw = sum(item.points for item in positive) + sum(item.points for item in penalties)
        final = max(0.0, min(100.0, raw))
        for cap in caps:
            final = min(final, cap.maximum)
        reasons = tuple(
            [item.reason for item in positive]
            + [item.reason for item in penalties]
            + [f"Score capped at {item.maximum:.0f}: {item.reason}" for item in caps]
            + [f"Final authoritative fit score: {final:.2f}."]
        )
        return round(final, 2), tuple(positive), tuple(penalties), caps, reasons
