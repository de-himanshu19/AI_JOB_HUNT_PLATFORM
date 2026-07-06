"""Versioned normalization and explainable cross-source duplicate clustering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from itertools import combinations
from uuid import UUID, uuid5

from app.db.connection import Database
from app.db.repositories import (
    DuplicateRepository,
    JobDescriptionRepository,
    JobRepository,
)
from app.domain.duplicates import (
    DuplicateCandidate,
    DuplicateCluster,
    DuplicateMatchMethod,
    JobDuplicateLink,
    MatchDecision,
    ReviewStatus,
)
from app.domain.job import Job
from app.services.normalization import (
    NORMALIZATION_VERSION,
    CompanyAliases,
    normalize_description,
    normalize_location,
    normalize_title,
    normalize_url,
)


DEDUPLICATION_VERSION = "m4-dedup-v1"
_NAMESPACE = UUID("f3280f69-f305-41cc-8a24-4a55df05a615")
_SENIORITY = {"intern", "junior", "senior", "lead", "head", "director", "manager"}


@dataclass(frozen=True)
class BackfillReport:
    algorithm_version: str
    jobs_normalized: int
    descriptions_normalized: int
    clusters_created: int
    links_created: int
    review_candidates_created: int


def _tokens(value: str | None) -> set[str]:
    return set(value.split()) if value else set()


def _token_similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(jaccard, sequence)


def _days_apart(left: Job, right: Job) -> int | None:
    if left.published_at is None or right.published_at is None:
        return None
    return abs((left.published_at.date() - right.published_at.date()).days)


def _location_compatible(left: Job, right: Job) -> bool:
    if left.remote_mode == "remote" and right.remote_mode == "remote":
        return True
    if left.city and right.city:
        return left.city == right.city
    if left.region and right.region:
        return left.region == right.region
    return False


class DuplicateMatcher:
    """Layered matcher that auto-clusters only high-confidence decisions."""

    def compare(
        self,
        left: Job,
        right: Job,
        *,
        left_description: str | None = None,
        right_description: str | None = None,
    ) -> MatchDecision:
        if (
            left.source == right.source
            and left.source_job_id
            and left.source_job_id == right.source_job_id
        ):
            return MatchDecision(
                method=DuplicateMatchMethod.EXACT_SOURCE_ID,
                confidence=1,
                reasons=("same source and source job ID",),
                should_cluster=True,
            )
        if left.canonical_url and left.canonical_url == right.canonical_url:
            return MatchDecision(
                method=DuplicateMatchMethod.CANONICAL_URL,
                confidence=1,
                reasons=("same canonical vacancy URL",),
                should_cluster=True,
            )

        days = _days_apart(left, right)
        exact_fingerprint = (
            bool(left.company_normalized)
            and left.company_normalized == right.company_normalized
            and left.title_normalized == right.title_normalized
            and bool(left.city)
            and left.city == right.city
            and days is not None
            and days <= 14
        )
        if exact_fingerprint:
            return MatchDecision(
                method=DuplicateMatchMethod.STRONG_FINGERPRINT,
                confidence=0.98,
                reasons=(
                    "same normalized company, title, and city",
                    f"publication dates within {days} days",
                ),
                should_cluster=True,
            )

        if left.source == right.source:
            return MatchDecision(confidence=0, reasons=("cross-source comparison required",))

        title_score = _token_similarity(left.title_normalized, right.title_normalized)
        company_score = _token_similarity(left.company_normalized, right.company_normalized)
        description_score = _token_similarity(left_description, right_description)
        location_score = 1.0 if _location_compatible(left, right) else 0.0
        date_score = 1.0 if days is not None and days <= 14 else 0.0
        confidence = (
            title_score * 0.40
            + company_score * 0.30
            + location_score * 0.15
            + description_score * 0.10
            + date_score * 0.05
        )
        reasons = (
            f"title similarity {title_score:.2f}",
            f"company similarity {company_score:.2f}",
            f"location compatible {bool(location_score)}",
            f"description similarity {description_score:.2f}",
            f"publication date compatible {bool(date_score)}",
        )
        seniority_conflict = (_tokens(left.title_normalized) & _SENIORITY) != (
            _tokens(right.title_normalized) & _SENIORITY
        )
        if seniority_conflict:
            confidence = min(confidence, 0.79)
            reasons += ("seniority tokens conflict",)

        should_cluster = (
            confidence >= 0.90
            and title_score >= 0.82
            and company_score >= 0.85
            and location_score == 1
            and not seniority_conflict
        )
        needs_review = not should_cluster and confidence >= 0.72
        return MatchDecision(
            method=(
                DuplicateMatchMethod.CROSS_SOURCE_SIMILARITY
                if should_cluster else None
            ),
            confidence=round(confidence, 6),
            reasons=reasons,
            should_cluster=should_cluster,
            needs_review=needs_review,
        )


class _DisjointSet:
    def __init__(self, values: list[UUID]):
        self.parent = {value: value for value in values}

    def find(self, value: UUID) -> UUID:
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: UUID, right: UUID) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


class DeduplicationService:
    def __init__(
        self,
        database: Database,
        *,
        aliases: CompanyAliases | None = None,
        matcher: DuplicateMatcher | None = None,
    ):
        self.database = database
        self.aliases = aliases or CompanyAliases()
        self.matcher = matcher or DuplicateMatcher()

    def backfill(
        self,
        *,
        algorithm_version: str = DEDUPLICATION_VERSION,
        normalization_version: str = NORMALIZATION_VERSION,
    ) -> BackfillReport:
        with self.database.transaction() as connection:
            jobs_repository = JobRepository(connection)
            descriptions_repository = JobDescriptionRepository(connection)
            jobs_normalized = self._normalize_jobs(
                jobs_repository, normalization_version
            )
            descriptions_normalized = descriptions_repository.normalize_all(
                normalize_description, version=normalization_version
            )
            jobs = jobs_repository.list_all()
            descriptions = {
                job.id: (
                    descriptions_repository.latest_for_job(job.id).normalized_text
                    if descriptions_repository.latest_for_job(job.id)
                    else None
                )
                for job in jobs
            }
            duplicate_repository = DuplicateRepository(connection)
            existing_counts = duplicate_repository.version_counts(algorithm_version)
            if (
                existing_counts[1] == len(jobs)
                and existing_counts[0] > 0
                and jobs_normalized == 0
                and descriptions_normalized == 0
            ):
                return BackfillReport(
                    algorithm_version=algorithm_version,
                    jobs_normalized=0,
                    descriptions_normalized=0,
                    clusters_created=existing_counts[0],
                    links_created=existing_counts[1],
                    review_candidates_created=existing_counts[2],
                )
            duplicate_repository.clear_version(algorithm_version)
            decisions, candidates = self._decisions(jobs, descriptions)
            groups = self._groups(jobs, decisions)

            for members in groups:
                representative = self._representative(members, descriptions)
                cluster_id = self._stable_id(
                    "cluster", algorithm_version, *(str(job.id) for job in members)
                )
                duplicate_repository.create_cluster(
                    DuplicateCluster(
                        id=cluster_id,
                        representative_job_id=representative.id,
                        algorithm_version=algorithm_version,
                    )
                )
                for job in members:
                    decision = self._best_decision(job.id, members, decisions)
                    duplicate_repository.create_link(
                        JobDuplicateLink(
                            id=self._stable_id("link", algorithm_version, str(job.id)),
                            job_id=job.id,
                            cluster_id=cluster_id,
                            algorithm_version=algorithm_version,
                            match_method=(
                                decision.method
                                if decision and decision.method
                                else DuplicateMatchMethod.SINGLETON
                            ),
                            confidence=decision.confidence if decision else 1,
                            reasons=decision.reasons if decision else ("single source row",),
                        )
                    )
            for left, right, decision in candidates:
                duplicate_repository.create_candidate(
                    DuplicateCandidate(
                        id=self._stable_id(
                            "candidate", algorithm_version,
                            *sorted((str(left.id), str(right.id))),
                        ),
                        left_job_id=left.id,
                        right_job_id=right.id,
                        algorithm_version=algorithm_version,
                        confidence=decision.confidence,
                        reasons=decision.reasons,
                    )
                )

            return BackfillReport(
                algorithm_version=algorithm_version,
                jobs_normalized=jobs_normalized,
                descriptions_normalized=descriptions_normalized,
                clusters_created=len(groups),
                links_created=len(jobs),
                review_candidates_created=len(candidates),
            )

    def clear_version(self, algorithm_version: str) -> None:
        with self.database.transaction() as connection:
            DuplicateRepository(connection).clear_version(algorithm_version)

    def review_candidate(
        self, candidate_id: UUID | str, decision: ReviewStatus
    ) -> None:
        if decision is ReviewStatus.PENDING:
            raise ValueError("Review decision must be approved or rejected")
        with self.database.transaction() as connection:
            repository = DuplicateRepository(connection)
            candidate = repository.get_candidate(candidate_id)
            if candidate is None:
                raise KeyError(f"Duplicate candidate not found: {candidate_id}")
            if decision is ReviewStatus.APPROVED:
                self._merge_jobs(
                    repository,
                    candidate.left_job_id,
                    candidate.right_job_id,
                    candidate.algorithm_version,
                )
            repository.set_candidate_status(
                candidate.id, decision, datetime.now(UTC)
            )

    def split_job(self, job_id: UUID | str, algorithm_version: str) -> UUID:
        job_uuid = UUID(str(job_id))
        with self.database.transaction() as connection:
            repository = DuplicateRepository(connection)
            old_cluster = repository.cluster_id_for_job(job_uuid, algorithm_version)
            if old_cluster is None:
                raise KeyError(f"No duplicate link for job: {job_id}")
            old_members = repository.cluster_member_ids(old_cluster, algorithm_version)
            if len(old_members) == 1:
                return old_cluster
            repository.remove_link(job_uuid, algorithm_version)
            new_cluster = self._stable_id(
                "manual-singleton", algorithm_version, str(job_uuid)
            )
            repository.create_cluster(
                DuplicateCluster(
                    id=new_cluster,
                    representative_job_id=job_uuid,
                    algorithm_version=algorithm_version,
                )
            )
            repository.create_link(
                JobDuplicateLink(
                    id=self._stable_id("manual-link", algorithm_version, str(job_uuid)),
                    job_id=job_uuid,
                    cluster_id=new_cluster,
                    algorithm_version=algorithm_version,
                    match_method=DuplicateMatchMethod.MANUAL,
                    confidence=1,
                    reasons=("manually split from duplicate cluster",),
                    reviewed=True,
                )
            )
            remaining = repository.cluster_member_ids(old_cluster, algorithm_version)
            repository.update_representative(
                old_cluster, min(remaining), algorithm_version
            )
            return new_cluster

    def _normalize_jobs(
        self, repository: JobRepository, normalization_version: str
    ) -> int:
        changed = 0
        for job in repository.list_all():
            title = normalize_title(job.title_raw) or job.title_normalized
            company = self.aliases.canonical(job.company_raw)
            location = normalize_location(
                job.city, job.region, job.country, raw=job.location_raw
            )
            canonical_url = normalize_url(job.canonical_url or job.source_url)
            was_changed = repository.update_normalized_fields(
                job.id,
                title=title,
                company=company,
                canonical_url=canonical_url,
                city=location.city,
                region=location.region,
                country=location.country,
                remote_mode=location.remote_mode or job.remote_mode,
                version=normalization_version,
            )
            changed += int(was_changed)
        return changed

    def _decisions(self, jobs, descriptions):
        accepted = {}
        candidates = []
        for left, right in combinations(jobs, 2):
            decision = self.matcher.compare(
                left,
                right,
                left_description=descriptions.get(left.id),
                right_description=descriptions.get(right.id),
            )
            if decision.should_cluster:
                accepted[frozenset((left.id, right.id))] = decision
            elif decision.needs_review:
                candidates.append((left, right, decision))
        return accepted, candidates

    @staticmethod
    def _groups(jobs, decisions):
        disjoint = _DisjointSet([job.id for job in jobs])
        for pair in decisions:
            left, right = tuple(pair)
            disjoint.union(left, right)
        grouped = {}
        for job in jobs:
            grouped.setdefault(disjoint.find(job.id), []).append(job)
        return [sorted(group, key=lambda job: str(job.id)) for group in grouped.values()]

    @staticmethod
    def _representative(members, descriptions):
        return max(
            members,
            key=lambda job: (
                bool(descriptions.get(job.id)),
                bool(job.canonical_url),
                bool(job.source_job_id),
                -int(job.id),
            ),
        )

    @staticmethod
    def _best_decision(job_id, members, decisions):
        matches = [
            decision for pair, decision in decisions.items()
            if job_id in pair and any(member.id in pair for member in members)
        ]
        return max(matches, key=lambda item: item.confidence) if matches else None

    @staticmethod
    def _stable_id(*parts: str) -> UUID:
        return uuid5(_NAMESPACE, "|".join(parts))

    @staticmethod
    def _merge_jobs(repository, left_job_id, right_job_id, algorithm_version):
        left_cluster = repository.cluster_id_for_job(left_job_id, algorithm_version)
        right_cluster = repository.cluster_id_for_job(right_job_id, algorithm_version)
        if left_cluster is None or right_cluster is None:
            raise KeyError("Both reviewed jobs must have cluster links")
        if left_cluster == right_cluster:
            return
        target, source = sorted((left_cluster, right_cluster))
        repository.move_cluster_members(source, target, algorithm_version)
        members = repository.cluster_member_ids(target, algorithm_version)
        repository.update_representative(target, min(members), algorithm_version)
