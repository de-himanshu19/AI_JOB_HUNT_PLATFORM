from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import app.cli as cli
from app.config import settings_from_mapping
from app.dashboard.query_service import DashboardQueryService
from app.dashboard.view_models import JobFilters
from app.db.connection import Database
from app.db.repositories import CandidateProfileRepository, JobDescriptionRepository, JobRepository
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.services.analysis_rules import AnalysisRules
from app.services.analytics import (
    ApplicationAnalyticsService,
    read_daily_run_summaries,
)
from app.services.applications import ApplicationService
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


def _add_job(
    database: Database,
    *,
    source: JobSource,
    source_id: str,
    title: str = "Data Analyst",
    company: str = "Another GmbH",
    completeness: DescriptionCompleteness = DescriptionCompleteness.FULL,
) -> Job:
    text = "SQL reporting validation stakeholder dashboards " * 30
    job = Job(
        source=source,
        source_job_id=source_id,
        source_url=f"https://example.invalid/{source_id}",
        canonical_url=f"https://example.invalid/{source_id}",
        title_raw=title,
        title_normalized=title.casefold(),
        company_raw=company,
        company_normalized=company.casefold(),
        location_raw="Berlin",
        city="berlin",
        country="germany",
        language_detected="en",
        first_seen_at=datetime(2026, 7, 9, tzinfo=UTC),
        last_seen_at=datetime(2026, 7, 9, tzinfo=UTC),
    )
    with database.transaction() as connection:
        JobRepository(connection).create(job)
        JobDescriptionRepository(connection).create(JobDescription(
            job_id=job.id,
            raw_text=text if completeness is not DescriptionCompleteness.MISSING else "",
            normalized_text=text if completeness is not DescriptionCompleteness.MISSING else "",
            completeness=completeness,
            content_hash=source_id.replace("-", "")[:64].ljust(64, "0"),
        ))
    return job


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
    analytics = service.application_analytics(daily_runs_dir=database.path.parent)
    assert analytics["metrics"]["total_jobs_stored"] == 0
    assert analytics["metrics"]["total_logical_vacancies"] == 0
    assert analytics["metrics"]["due_followups"] == 0
    assert analytics["applications_by_status"]["applied"] == 0
    assert analytics["daily_runs"]["latest"] is None


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


def test_applications_query_includes_crm_and_score_context(database: Database) -> None:
    profile, jobs = _seed_logical_vacancy(database)
    ApplicationService(database).shortlist_job(
        profile.id, jobs[0].id, priority="high", note="Dashboard follow-up"
    )

    rows = DashboardQueryService(database).applications(profile.id)

    assert len(rows) == 1
    assert rows[0]["current_status"] == "shortlisted"
    assert rows[0]["priority"] == "high"
    assert rows[0]["rank_score"] is not None
    assert rows[0]["fit_score"] is not None
    assert rows[0]["notes_preview"] == "Dashboard follow-up"


def test_application_analytics_counts_statuses_sources_and_followups(
    database: Database,
) -> None:
    profile, jobs = _seed_logical_vacancy(database)
    extra = _add_job(
        database,
        source=JobSource.ENGLISHJOBS,
        source_id="analytics-ej-snippet",
        company="Different GmbH",
        completeness=DescriptionCompleteness.SNIPPET,
    )
    service = ApplicationService(database)
    service.mark_cv_ready(profile.id, jobs[0].id, note="FlowCV ready")
    service.mark_applied(profile.id, extra.id, note="Applied manually")
    service.set_follow_up(
        profile_id=profile.id,
        job_id=extra.id,
        follow_up_date=date(2026, 7, 9),
        note="Ask recruiter for update",
    )

    summary = ApplicationAnalyticsService(
        database, today=date(2026, 7, 10)
    ).summary(profile.id)

    assert summary["metrics"]["total_jobs_stored"] == 3
    assert summary["jobs_by_source"]["arbeitsagentur"] == 1
    assert summary["jobs_by_source"]["englishjobs"] == 2
    assert summary["applications_by_status"]["cv_ready"] == 1
    assert summary["applications_by_status"]["applied"] == 1
    assert summary["metrics"]["cv_ready_count"] == 1
    assert summary["metrics"]["applied_count"] == 1
    assert summary["metrics"]["overdue_followups"] == 1
    assert summary["followups"]["overdue"][0]["last_note"].endswith(
        "Ask recruiter for update"
    )
    englishjobs = next(
        row for row in summary["source_quality"] if row["source"] == "englishjobs"
    )
    assert englishjobs["snippet_descriptions"] == 1
    assert englishjobs["applications"] == 1
    assert englishjobs["applied"] == 1


def test_daily_run_summary_reader_skips_malformed_files(tmp_path: Path) -> None:
    (tmp_path / "daily_bad.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "daily_ok.json").write_text(
        json.dumps({
            "status": "completed",
            "started_at": "2026-07-10T08:00:00+00:00",
            "finished_at": "2026-07-10T08:05:00+00:00",
            "total_searches": 2,
            "successful_searches": 1,
            "failed_searches": 1,
            "errors": [{"message": "fixture failure"}],
            "searches": [
                {
                    "jobs_collected": 3,
                    "top_jobs_count": 2,
                    "pipeline_summary": {"ranking_scope": "current-run"},
                },
                {"status": "failed", "jobs_collected": 0, "top_jobs_count": 0},
            ],
        }),
        encoding="utf-8",
    )

    rows = read_daily_run_summaries(tmp_path, limit=7)

    assert len(rows) == 1
    assert rows[0]["searches"] == 2
    assert rows[0]["failed_searches"] == 1
    assert rows[0]["jobs_collected"] == 3
    assert rows[0]["top_jobs"] == 2
    assert rows[0]["ranking_scope"] == "current-run"


def test_analytics_cli_summary_returns_json(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    settings = settings_from_mapping(
        {"JOBHUNT_DATABASE_PATH": "analytics.sqlite3"},
        root=tmp_path,
    )
    database = Database.from_settings(settings)
    from app.db.migrations import migrate

    migrate(database)
    profile, jobs = _seed_logical_vacancy(database)
    ApplicationService(database).shortlist_job(profile.id, jobs[0].id, priority="high")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    result = cli.main([
        "analytics",
        "summary",
        "--profile-id",
        str(profile.id),
        "--daily-runs-dir",
        str(tmp_path / "daily runs with spaces"),
    ])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["profile_id"] == str(profile.id)
    assert payload["applications_by_status"]["shortlisted"] == 1
    assert payload["daily_runs"]["latest"] is None


def test_cv_artifact_queries_read_text_and_handle_missing_files(
    database: Database, tmp_path: Path,
) -> None:
    profile, jobs = _seed_logical_vacancy(database)
    with database.read_connection() as connection:
        analyzed_job_id = connection.execute(
            """SELECT job_id FROM job_analyses
            WHERE profile_id = ? ORDER BY created_at DESC LIMIT 1""",
            (str(profile.id),),
        ).fetchone()["job_id"]
    job = next(item for item in jobs if str(item.id) == analyzed_job_id)
    application = ApplicationService(database).shortlist_job(profile.id, job.id)
    cv_path = tmp_path / "flowcv.txt"
    evidence_path = tmp_path / "evidence.txt"
    cv_path.write_text("FlowCV copy text", encoding="utf-8")
    evidence_path.write_text("Private evidence text", encoding="utf-8")
    artifact_id = "22222222-2222-4222-8222-222222222222"
    with database.transaction() as connection:
        description = connection.execute(
            """SELECT id, content_hash FROM job_descriptions
            WHERE job_id = ? ORDER BY created_at DESC LIMIT 1""",
            (str(job.id),),
        ).fetchone()
        analysis = connection.execute(
            """SELECT id FROM job_analyses
            WHERE job_id = ? AND profile_id = ? ORDER BY created_at DESC LIMIT 1""",
            (str(job.id), str(profile.id)),
        ).fetchone()
        connection.execute(
            """INSERT INTO cv_generation_artifacts (
                id, job_id, logical_cluster_id, description_id,
                description_content_hash, description_completeness, profile_id,
                profile_version, profile_content_hash, analysis_id,
                analyzer_version, rules_version, generator_version,
                formatter_version, generation_mode, generation_identity,
                artifact_format, source, parent_rule_based_artifact_id,
                artifact_path, evidence_report_path, content_hash,
                evidence_report_hash, provider, model, prompt_version,
                ai_generated_at, validated, validation_result_json, created_at
            ) VALUES (
                ?, ?, ?, ?, ?, 'full', ?, 1, ?, ?, 'analyzer', 'rules',
                'generator', 'formatter', 'stored_job', ?, 'flowcv_txt',
                'rule_based', NULL, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 1,
                '{}', '2026-07-09T00:00:00+00:00'
            )""",
            (
                artifact_id, str(job.id), str(application.logical_cluster_id),
                description["id"], description["content_hash"], str(profile.id),
                profile.content_hash, analysis["id"], "i" * 64, str(cv_path),
                str(evidence_path), "c" * 64, "e" * 64,
            ),
        )

    service = DashboardQueryService(database)
    artifacts = service.list_cv_artifacts(profile.id)
    detail = service.get_cv_artifact_detail(artifact_id)

    assert artifacts[0]["artifact_id"] == artifact_id
    assert artifacts[0]["application_status"] == "shortlisted"
    assert detail["title_raw"] == "Data Analyst"
    assert service.read_cv_artifact_text(artifact_id)["text"] == "FlowCV copy text"
    assert (
        service.read_evidence_report_text(artifact_id)["text"]
        == "Private evidence text"
    )
    applications = service.list_applications_with_cv_context(profile.id)
    assert applications[0]["latest_cv_artifact_id"] == artifact_id
    cv_path.unlink()
    missing = service.read_cv_artifact_text(artifact_id)
    assert missing["found"] is False
    assert "missing" in missing["message"]


def test_cv_artifact_queries_include_ai_metadata(database: Database, tmp_path: Path) -> None:
    profile, jobs = _seed_logical_vacancy(database)
    with database.read_connection() as connection:
        analyzed_job_id = connection.execute(
            """SELECT job_id FROM job_analyses
            WHERE profile_id = ? ORDER BY created_at DESC LIMIT 1""",
            (str(profile.id),),
        ).fetchone()["job_id"]
    job = next(item for item in jobs if str(item.id) == analyzed_job_id)
    parent_id = "33333333-3333-4333-8333-333333333333"
    ai_id = "44444444-4444-4444-8444-444444444444"
    parent_path = tmp_path / "rule.txt"
    ai_path = tmp_path / "ai.txt"
    evidence_path = tmp_path / "evidence.txt"
    parent_path.write_text("Rule CV", encoding="utf-8")
    ai_path.write_text("AI CV", encoding="utf-8")
    evidence_path.write_text("Evidence", encoding="utf-8")
    with database.transaction() as connection:
        description = connection.execute(
            """SELECT id, content_hash FROM job_descriptions
            WHERE job_id = ? ORDER BY created_at DESC LIMIT 1""",
            (str(job.id),),
        ).fetchone()
        analysis = connection.execute(
            """SELECT id FROM job_analyses
            WHERE job_id = ? AND profile_id = ? ORDER BY created_at DESC LIMIT 1""",
            (str(job.id), str(profile.id)),
        ).fetchone()
        for artifact_id, source, parent, path, provider, model, prompt in (
            (parent_id, "rule_based", None, parent_path, None, None, None),
            (
                ai_id, "ai_polished", parent_id, ai_path,
                "openai_compatible", "test-model", "m13-cv-polish-v1",
            ),
        ):
            connection.execute(
                """INSERT INTO cv_generation_artifacts (
                    id, job_id, logical_cluster_id, description_id,
                    description_content_hash, description_completeness, profile_id,
                    profile_version, profile_content_hash, analysis_id,
                    analyzer_version, rules_version, generator_version,
                    formatter_version, generation_mode, generation_identity,
                    artifact_format, source, parent_rule_based_artifact_id,
                    artifact_path, evidence_report_path, content_hash,
                    evidence_report_hash, provider, model, prompt_version,
                    ai_generated_at, validated, validation_result_json, created_at
                ) VALUES (
                    ?, ?, NULL, ?, ?, 'full', ?, 1, ?, ?, 'analyzer', 'rules',
                    'generator', 'formatter', 'stored_job', ?, 'flowcv_txt',
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    CASE WHEN ? IS NULL THEN NULL ELSE '2026-07-09T00:00:00+00:00' END,
                    1, '{"valid": true}', '2026-07-09T00:00:00+00:00'
                )""",
                (
                    artifact_id, str(job.id), description["id"],
                    description["content_hash"], str(profile.id),
                    profile.content_hash, analysis["id"],
                    artifact_id.replace("-", "")[:64].ljust(64, "0"),
                    source, parent, str(path), str(evidence_path),
                    "c" * 64, "e" * 64, provider, model, prompt, provider,
                ),
            )
        connection.execute(
            """INSERT INTO cv_ai_attempts (
                id, parent_rule_based_artifact_id, derivative_artifact_id,
                provider, model, prompt_version, status, failure_category,
                evidence_report_path, validation_result_json, generated_at
            ) VALUES (
                '55555555-5555-4555-8555-555555555555', ?, ?,
                'openai_compatible', 'test-model', 'm13-cv-polish-v1',
                'succeeded', NULL, ?, '{"valid": true}', '2026-07-09T00:00:00+00:00'
            )""",
            (parent_id, ai_id, str(evidence_path)),
        )

    artifacts = DashboardQueryService(database).list_cv_artifacts(profile.id)
    ai = next(item for item in artifacts if item["artifact_id"] == ai_id)

    assert ai["source"] == "ai_polished"
    assert ai["parent_rule_based_artifact_id"] == parent_id
    assert ai["provider"] == "openai_compatible"
    assert ai["model"] == "test-model"
    assert ai["prompt_version"] == "m13-cv-polish-v1"
    assert ai["ai_status"] == "succeeded"
