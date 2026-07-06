"""Deterministic ranking of Milestone 4 logical vacancies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.db.connection import Database
from app.db.repositories import (
    CandidateProfileRepository,
    JobRankingRepository,
    JobRepository,
)
from app.domain.analysis import AnalysisAuthority, JobRanking, ScoreComponent
from app.domain.candidate import CandidateEvidenceProfile
from app.domain.job import Job
from app.services.analysis_rules import AnalysisRules
from app.services.fit_analysis import FitAnalysisService, _stable_hash
from app.services.normalization import normalize_text


@dataclass(frozen=True)
class RankedVacancy:
    job: Job
    ranking: JobRanking
    fit_score: float | None
    analysis_cache_hit: bool
    ranking_cache_hit: bool


class RankingService:
    def __init__(self, database: Database, rules: AnalysisRules):
        self.database = database
        self.rules = rules
        self.analysis_service = FitAnalysisService(database, rules)

    def rank(
        self,
        profile_id: UUID | str,
        duplicate_algorithm_version: str,
        *,
        as_of: datetime,
        include_prefilter_only: bool = False,
    ) -> list[RankedVacancy]:
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        as_of = as_of.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        with self.database.read_connection() as connection:
            profile = CandidateProfileRepository(connection).get(profile_id)
            logical_jobs = JobRepository(connection).list_logical_representatives(
                duplicate_algorithm_version
            )
        if profile is None:
            raise KeyError(f"Candidate profile not found: {profile_id}")
        evidence_profile = CandidateEvidenceProfile.from_candidate_profile(profile)
        ranked: list[RankedVacancy] = []
        for job, cluster_id in logical_jobs:
            execution = self.analysis_service.analyze_job(job.id, profile.id)
            analysis = execution.analysis
            if (
                analysis.authority is AnalysisAuthority.PREFILTER_ONLY
                and not include_prefilter_only
            ):
                continue
            components = self._components(job, analysis, evidence_profile, as_of)
            base_score = (
                analysis.fit_score
                if analysis.authority is AnalysisAuthority.AUTHORITATIVE
                else analysis.prefilter_score
            ) or 0.0
            score = round(sum(item.points for item in components), 4)
            input_hash = _stable_hash({
                "analysis_id": str(analysis.id),
                "cluster_id": str(cluster_id),
                "ranking_version": self.rules.ranking_version,
                "rules_version": self.rules.rules_version,
                "as_of": as_of.isoformat(),
                "components": [item.model_dump(mode="json") for item in components],
            })
            with self.database.transaction() as connection:
                repository = JobRankingRepository(connection)
                ranking = repository.get_by_input_hash(input_hash)
                ranking_cache_hit = ranking is not None
                if ranking is None:
                    ranking = repository.create(JobRanking(
                        job_id=job.id, cluster_id=cluster_id,
                        analysis_id=analysis.id, profile_id=profile.id,
                        profile_version=profile.version,
                        ranking_version=self.rules.ranking_version,
                        ranking_input_hash=input_hash, ranked_as_of=as_of,
                        authority=analysis.authority, rank_score=score,
                        components=components,
                    ))
            ranked.append(RankedVacancy(
                job, ranking, analysis.fit_score,
                execution.cache_hit, ranking_cache_hit,
            ))
        return sorted(ranked, key=self._sort_key)

    def _components(self, job, analysis, profile, as_of):
        components = [ScoreComponent(
            name="authoritative_fit" if analysis.authority is AnalysisAuthority.AUTHORITATIVE else "prefilter_score",
            points=(analysis.fit_score if analysis.authority is AnalysisAuthority.AUTHORITATIVE else analysis.prefilter_score) or 0,
            reason=f"Base score is {analysis.fit_score if analysis.authority is AnalysisAuthority.AUTHORITATIVE else analysis.prefilter_score}.",
        )]
        observed = job.published_at or job.first_seen_at
        days = max(0, (as_of.date() - observed.date()).days)
        window = self.rules.ranking.freshness_window_days
        freshness = self.rules.ranking.freshness_max_bonus * max(0, window - days) / window
        if freshness:
            components.append(ScoreComponent(name="freshness", points=round(freshness, 4), reason=f"Vacancy is {days} days old within a {window}-day freshness window."))
        location_text = normalize_text(" ".join(filter(None, (job.city, job.region, job.country, job.location_raw)))) or ""
        preferred_location = next((item for item in profile.preferences.preferred_locations if (normalize_text(item) or "") in location_text), None)
        if preferred_location:
            components.append(ScoreComponent(name="preferred_location", points=self.rules.ranking.preferred_location_bonus, reason=f"Matched preferred location: {preferred_location}."))
        analysis_text = normalize_text(" ".join(requirement.name for requirement in analysis.requirements if hasattr(requirement, "name"))) or ""
        preferred_domain = next((item for item in profile.preferences.preferred_domains if (normalize_text(item) or "") in analysis_text), None)
        if preferred_domain:
            components.append(ScoreComponent(name="preferred_domain", points=self.rules.ranking.preferred_domain_bonus, reason=f"Matched preferred domain: {preferred_domain}."))
        return tuple(components)

    @staticmethod
    def _sort_key(item: RankedVacancy):
        job = item.job
        published = job.published_at or datetime.min.replace(tzinfo=UTC)
        return (
            -item.ranking.rank_score,
            -(item.fit_score if item.fit_score is not None else -1),
            -published.timestamp(),
            -(job.first_seen_at or datetime.min.replace(tzinfo=UTC)).timestamp(),
            job.title_normalized.casefold(),
            (job.company_normalized or "").casefold(),
            str(item.ranking.cluster_id or job.id),
        )
