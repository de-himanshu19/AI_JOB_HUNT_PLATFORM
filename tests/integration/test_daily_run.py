from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import app.cli as cli
from app.db.connection import Database
from app.db.migrations import migrate
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.services.daily_run import (
    DailyRunConfigError,
    DailyRunService,
    DailySearch,
    load_searches,
)
from app.services.pipeline import PipelineService, RankingScope
from app.sources.base import CollectedJob, CollectionResult, SourceRunStatus

from tests.integration.test_pipeline import (
    _profile,
    _rules,
    _seed_stored_job,
    _settings,
)


class FakePipeline:
    def __init__(self, calls):
        self.calls = calls

    def run(self, request):
        self.calls.append(request)
        return {
            "profile_id": str(request.profile_id),
            "query": request.query,
            "location": request.location,
            "sources_requested": [source.value for source in request.sources],
            "live_collect": request.live_collect,
            "ranking_scope": request.ranking_scope.value,
            "collection": {
                source.value: {
                    "status": "completed",
                    "jobs_collected": 2,
                    "network_requested": request.live_collect,
                    "database_modified": request.live_collect,
                }
                for source in request.sources
            },
            "top_jobs": [{"job_id": "job-1"}, {"job_id": "job-2"}],
            "output_path": "data/pipeline_runs/fake.json",
        }


def _daily_service(tmp_path, *, calls=None):
    settings = _settings(tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    calls = calls if calls is not None else []
    return DailyRunService(
        database,
        settings,
        _rules(),
        pipeline_factory=lambda: FakePipeline(calls),
        now=lambda: datetime(2026, 7, 9, 8, 0, tzinfo=UTC),
        output_dir=tmp_path / "daily output",
        lock_path=tmp_path / "locks" / "daily_run.lock",
    ), calls


def test_daily_run_reuses_pipeline_and_writes_summary(tmp_path) -> None:
    service, calls = _daily_service(tmp_path)
    summary = service.run_one(
        DailySearch(
            name="stored_only",
            profile_id="profile-1",
            sources=(JobSource.ARBEITSAGENTUR,),
            live_collect=False,
            preview_notification=True,
        )
    )

    assert summary["status"] == "completed"
    assert summary["total_searches"] == 1
    assert summary["successful_searches"] == 1
    assert calls[0].live_collect is False
    assert calls[0].preview_notification is True
    output = Path(summary["output_path"])
    assert output.is_file()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["run_id"] == summary["run_id"]
    assert written["searches"][0]["jobs_collected"] == 2


def test_run_config_executes_multiple_searches_with_configured_bounds(tmp_path) -> None:
    service, calls = _daily_service(tmp_path)
    config = tmp_path / "daily config.json"
    config.write_text(
        json.dumps([
            {
                "name": "aa",
                "profile_id": "profile-1",
                "query": "Data Analyst",
                "location": "Deutschland",
                "source": "arbeitsagentur",
            },
            {
                "name": "ej",
                "profile_id": "profile-1",
                "query": "Data Analyst",
                "location": "Germany",
                "source": "englishjobs",
                "include_prefilter_only": True,
                "max_detail_requests": 10,
            },
        ]),
        encoding="utf-8",
    )

    summary = service.run_config_file(config)

    assert summary["status"] == "completed"
    assert summary["total_searches"] == 2
    assert [call.sources for call in calls] == [
        (JobSource.ARBEITSAGENTUR,),
        (JobSource.ENGLISHJOBS,),
    ]
    assert calls[1].include_prefilter_only is True
    assert calls[1].max_detail_requests == 10
    assert calls[0].ranking_scope is RankingScope.CURRENT_RUN
    assert calls[1].ranking_scope is RankingScope.CURRENT_RUN


def test_run_config_can_request_global_ranking_scope(tmp_path) -> None:
    service, calls = _daily_service(tmp_path)
    config = tmp_path / "daily global.json"
    config.write_text(
        json.dumps([
            {
                "name": "global",
                "profile_id": "profile-1",
                "source": "arbeitsagentur",
                "ranking_scope": "global",
            }
        ]),
        encoding="utf-8",
    )

    service.run_config_file(config)

    assert calls[0].ranking_scope is RankingScope.GLOBAL


def test_daily_run_config_englishjobs_current_run_not_dominated_by_old_global_jobs(
    tmp_path,
) -> None:
    settings = _settings(tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    profile, _ = _seed_stored_job(database)

    class FakeEnglishJobsCollector:
        def collect(self, request):
            job = Job(
                source=JobSource.ENGLISHJOBS,
                source_job_id="daily-ej-current",
                title_raw="Daily EnglishJobs Discovery Analyst",
                title_normalized="daily englishjobs discovery analyst",
                company_raw="Fresh Jobs GmbH",
                company_normalized="fresh jobs gmbh",
                location_raw="Hamburg",
            )
            description = JobDescription(
                job_id=job.id,
                raw_text="SQL reporting dashboard snippet",
                normalized_text="SQL reporting dashboard snippet",
                completeness=DescriptionCompleteness.SNIPPET,
                content_hash="a" * 64,
            )
            return CollectionResult(
                jobs=[CollectedJob(job=job, description=description)],
                jobs_parsed=1,
                search_requests_succeeded=1,
                status=SourceRunStatus.COMPLETED,
            )

    service = DailyRunService(
        database,
        settings,
        _rules(),
        pipeline_factory=lambda: PipelineService(
            database,
            settings,
            _rules(),
            collector_factory=lambda source: FakeEnglishJobsCollector(),
            now=lambda: datetime(2026, 7, 9, 8, 0, tzinfo=UTC),
        ),
        now=lambda: datetime(2026, 7, 9, 8, 0, tzinfo=UTC),
        output_dir=tmp_path / "daily output",
        lock_path=tmp_path / "locks" / "daily_run.lock",
    )
    config = tmp_path / "daily-ej.json"
    config.write_text(
        json.dumps([
            {
                "name": "ej",
                "profile_id": str(profile.id),
                "source": "englishjobs",
                "live_collect": True,
                "include_prefilter_only": True,
                "preview_notification": True,
            }
        ]),
        encoding="utf-8",
    )

    summary = service.run_config_file(config)
    pipeline = summary["searches"][0]["pipeline_summary"]

    assert pipeline["ranking_scope"] == "current-run"
    assert [item["title"] for item in pipeline["top_jobs"]] == [
        "Daily EnglishJobs Discovery Analyst"
    ]
    assert pipeline["top_jobs"][0]["authority"] == "prefilter_only"
    assert pipeline["top_jobs_global"][0]["title"] == "Data Analyst"
    assert pipeline["notification_preview"]["selected_count"] == 1
    assert pipeline["notification_preview"]["ranking_scope"] == "current-run"


def test_malformed_and_missing_config_fail_clearly(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    try:
        load_searches(missing)
    except DailyRunConfigError as error:
        assert "not found" in str(error)
    else:
        raise AssertionError("Missing config did not fail")

    malformed = tmp_path / "bad.json"
    malformed.write_text("{not json", encoding="utf-8")
    try:
        load_searches(malformed)
    except DailyRunConfigError as error:
        assert "not valid JSON" in str(error)
    else:
        raise AssertionError("Malformed config did not fail")

    wrong_shape = tmp_path / "shape.json"
    wrong_shape.write_text("{}", encoding="utf-8")
    try:
        load_searches(wrong_shape)
    except DailyRunConfigError as error:
        assert "JSON list" in str(error)
    else:
        raise AssertionError("Wrong config shape did not fail")


def test_lock_file_prevents_overlapping_run(tmp_path) -> None:
    service, calls = _daily_service(tmp_path)
    lock = tmp_path / "locks" / "daily_run.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("existing lock\n", encoding="utf-8")

    summary = service.run_one(
        DailySearch(name="locked", profile_id="profile-1")
    )

    assert summary["status"] == "locked"
    assert calls == []
    assert summary["output_path"] is None


def test_daily_cli_without_live_collect_uses_stored_jobs_and_no_live_collection(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    settings = _settings(tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    profile, _ = _seed_stored_job(database)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    exit_code = cli.main([
        "daily",
        "run",
        "--profile-id",
        str(profile.id),
        "--source",
        "arbeitsagentur",
        "--output-dir",
        str(tmp_path / "daily runs"),
        "--lock-file",
        str(tmp_path / "daily lock.lock"),
    ])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["status"] == "completed"
    assert output["searches"][0]["pipeline_summary"]["live_collect"] is False
    assert output["searches"][0]["pipeline_summary"]["ranking_scope"] == "current-run"
    assert (
        output["searches"][0]["pipeline_summary"]["collection"]["arbeitsagentur"][
            "network_requested"
        ]
        is False
    )
    assert Path(output["output_path"]).is_file()


def test_daily_cli_run_config_missing_file_returns_safe_json(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    settings = _settings(tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    _profile(database)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    exit_code = cli.main([
        "daily",
        "run-config",
        "--config",
        str(tmp_path / "missing.json"),
        "--output-dir",
        str(tmp_path / "daily runs"),
    ])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["status"] == "failed"
    assert output["error_type"] == "DailyRunConfigError"
