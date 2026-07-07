from __future__ import annotations

import json
from datetime import UTC, datetime

from app.db.connection import Database
from app.db.repositories import (
    CandidateProfileRepository,
    DuplicateRepository,
    JobAnalysisRepository,
    JobRankingRepository,
    JobRepository,
)
from app.domain.analysis import AnalysisAuthority, JobAnalysis, JobRanking
from app.domain.duplicates import DuplicateCluster, DuplicateMatchMethod, JobDuplicateLink
from app.domain.enums import JobSource
from app.domain.job import Job


DUPLICATE_VERSION = "m4-dedup-v1"
RANKING_VERSION = "m5-ranking-v1"


def seed_ranked_vacancies(database: Database, count: int):
    profile_data = {
        "personal_info": {"full_name": "Notification Candidate"},
        "work_experience": {"items": []},
        "skills_and_tools": {"skills": ["SQL"]},
    }
    with database.transaction() as connection:
        profile = CandidateProfileRepository(connection).create_version(
            profile_data, profile_key="notification-candidate"
        )
        jobs = JobRepository(connection)
        analyses = JobAnalysisRepository(connection)
        rankings = JobRankingRepository(connection)
        duplicates = DuplicateRepository(connection)
        seeded = []
        now = datetime(2026, 7, 6, tzinfo=UTC)
        for index in range(1, count + 1):
            job = Job(
                source=(
                    JobSource.ARBEITSAGENTUR if index % 2 else JobSource.ENGLISHJOBS
                ),
                source_job_id=f"notification-{index}",
                source_url=f"https://jobs.example/{index}",
                canonical_url=f"https://employer.example/jobs/{index}",
                title_raw=f"Data Analyst {index:02d}",
                title_normalized=f"data analyst {index:02d}",
                company_raw=f"Example Company {index:02d}",
                company_normalized=f"example company {index:02d}",
                location_raw="Berlin & Remote <possible>",
                city="berlin", country="germany", published_at=now,
                first_seen_at=now, last_seen_at=now,
            )
            jobs.create(job)
            analysis = analyses.create(JobAnalysis(
                job_id=job.id, profile_id=profile.id,
                profile_version=profile.version,
                analyzer_version="m5-analyzer-v1", rules_version="m5-rules-v1",
                ranking_version=RANKING_VERSION,
                analysis_input_hash=f"{index:064x}",
                description_completeness="full",
                authority=AnalysisAuthority.AUTHORITATIVE,
                fit_score=90 - index / 10,
                fit_reasons=(f"Verified evidence reason {index}.",),
            ))
            cluster = DuplicateCluster(
                representative_job_id=job.id,
                algorithm_version=DUPLICATE_VERSION,
            )
            duplicates.create_cluster(cluster)
            duplicates.create_link(JobDuplicateLink(
                job_id=job.id, cluster_id=cluster.id,
                algorithm_version=DUPLICATE_VERSION,
                match_method=DuplicateMatchMethod.SINGLETON,
                confidence=1, reasons=("fixture singleton",),
            ))
            ranking = rankings.create(JobRanking(
                job_id=job.id, cluster_id=cluster.id, analysis_id=analysis.id,
                profile_id=profile.id, profile_version=profile.version,
                ranking_version=RANKING_VERSION,
                ranking_input_hash=f"{index + 1000:064x}", ranked_as_of=now,
                authority=AnalysisAuthority.AUTHORITATIVE,
                rank_score=100 - index,
            ))
            seeded.append((job, cluster, analysis, ranking))
    return profile, seeded
