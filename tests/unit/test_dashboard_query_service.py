from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.dashboard.query_service import DashboardQueryService
from app.dashboard.view_models import JobFilters
from app.db.connection import Database
from app.db.repositories import CandidateProfileRepository, JobDescriptionRepository, JobRepository
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.services.analysis_rules import AnalysisRules
from app.services.deduplication import DeduplicationService
from app.services.ranking import RankingService


ROOT = Path(__file__).parents[2]
FIT_FIXTURES = ROOT / "tests" / "fixtures" / "fit_analysis"


def _seed_logical_vacancy(database: Database):
    profile_data = json.loads(
        (FIT_FIXTURES / "candidate_profile.json").read_text(encoding="utf-8")
    )
    text = (FIT_FIXTURES / "full_data_analyst.txt").read_text(encoding="utf-8")
    jobs = [
        Job(
            source=JobSource.ARBEITSAGENTUR, source_job_id="dash-aa",
            source_url="https://example.invalid/aa", canonical_url="https://example.invalid/job",
            title_raw="Data Analyst", title_normalized="data analyst",
            company_raw="Example GmbH", company_normalized="example",
            location_raw="Muenchen", city="munich", country="germany",
            language_detected="en", published_at=datetime(2026, 7, 1, tzinfo=UTC),
        ),
        Job(
            source=JobSource.ENGLISHJOBS, source_job_id="dash-ej",
            source_url="https://example.invalid/ej", canonical_url="https://example.invalid/job",
            title_raw="Data Analyst", title_normalized="data analyst",
            company_raw="Example GmbH", company_normalized="example",
            location_raw="München", city="munich", country="germany",
            language_detected="en", published_at=datetime(2026, 7, 1, tzinfo=UTC),
        ),
    ]
    with database.transaction() as connection:
        profile = CandidateProfileRepository(connection).create_version(
            profile_data, profile_key="dashboard"
        )
        for index, job in enumerate(jobs):
            JobRepository(connection).create(job)
            JobDescriptionRepository(connection).create(JobDescription(
                job_id=job.id, raw_text=text, normalized_text=text,
                completeness=DescriptionCompleteness.FULL,
                content_hash=(str(index + 1) * 64),
            ))
    DeduplicationService(database).backfill()
    rules = AnalysisRules.from_json(ROOT / "config" / "fit_rules.json")
    RankingService(database, rules).rank(
        profile.id, "m4-dedup-v1", as_of=datetime(2026, 7, 8, tzinfo=UTC)
    )
    return profile, jobs


def test_empty_dashboard_queries_return_useful_empty_views(database: Database) -> None:
    service = DashboardQueryService(database)
    overview = service.overview()
    assert overview.active_source_jobs == 0
    assert overview.logical_vacancies == 0
    assert overview.authoritative_analyses == 0
    assert overview.preliminary_analyses == 0
    assert overview.ranked_vacancies == 0
    assert overview.preliminary_rankings == 0
    assert service.jobs(JobFilters()).items == ()
    assert service.profiles() == ()
    assert service.runs() == ()
    assert service.diagnostics()["foreign_key_issues"] == 0


def test_jobs_default_to_logical_vacancies_and_filters_compose(database: Database) -> None:
    profile, jobs = _seed_logical_vacancy(database)
    service = DashboardQueryService(database)
    logical = service.jobs(JobFilters(search="analyst"), profile.id)
    source_rows = service.jobs(
        JobFilters(search="analyst", logical_only=False), profile.id
    )
    filtered = service.jobs(
        JobFilters(source="englishjobs", completeness="full", logical_only=False),
        profile.id,
    )
    assert logical.total == 1
    assert source_rows.total == 2
    assert filtered.total == 1
    assert filtered.items[0].location == "München"
    assert logical.items[0].rank_score is not None
    assert {item.job_id for item in source_rows.items} == {str(job.id) for job in jobs}


def test_job_detail_composes_cluster_analysis_ranking_and_full_description(
    database: Database,
) -> None:
    profile, jobs = _seed_logical_vacancy(database)
    service = DashboardQueryService(database)
    detail = service.job_detail(jobs[0].id, profile.id)
    assert detail.description["completeness"] == "full"
    assert "SQL" in detail.description["raw_text"]
    assert len(detail.cluster_members) == 2
    assert detail.analysis["authority"] == "authoritative"
    assert detail.ranking["rank_score"] is not None


def test_sort_whitelist_ignores_unknown_sort_expression(database: Database) -> None:
    profile, _ = _seed_logical_vacancy(database)
    result = DashboardQueryService(database).jobs(
        JobFilters(sort_by="rank_score; DROP TABLE jobs"), profile.id
    )
    assert result.total == 1
    with database.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
