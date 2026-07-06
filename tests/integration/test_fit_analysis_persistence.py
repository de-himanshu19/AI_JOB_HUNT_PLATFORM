from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.db.connection import Database
from app.db.repositories import (
    CandidateProfileRepository,
    JobAnalysisRepository,
    JobDescriptionRepository,
    JobRepository,
)
from app.domain.analysis import AnalysisAuthority, EvidenceType
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.services.analysis_rules import AnalysisRules
from app.services.fit_analysis import FitAnalysisService
import app.cli as cli
from app.config import settings_from_mapping
from app.db.migrations import migrate


ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "fit_analysis"


def _payload():
    return json.loads((FIXTURES / "candidate_profile.json").read_text(encoding="utf-8"))


def _rules():
    return AnalysisRules.from_json(ROOT / "config" / "fit_rules.json")


def _profile(database: Database):
    with database.transaction() as connection:
        return CandidateProfileRepository(connection).create_version(
            _payload(), profile_key="example"
        )


def _job(database, *, source=JobSource.ARBEITSAGENTUR, source_id="job-1", title="Senior Data Analyst"):
    job = Job(
        source=source, source_job_id=source_id,
        source_url=f"https://jobs.example/{source_id}",
        title_raw=title, title_normalized=title.casefold(),
        company_raw="Example Company", company_normalized="example company",
        location_raw="Berlin", city="berlin", country="germany",
        published_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    with database.transaction() as connection:
        JobRepository(connection).create(job)
    return job


def _description(database, job, filename, completeness, suffix="1", fetched_at=None):
    text = (FIXTURES / filename).read_text(encoding="utf-8") if filename else None
    description = JobDescription(
        job_id=job.id, raw_text=text, normalized_text=text,
        completeness=completeness, content_hash=f"{job.id}-{suffix}",
        fetched_at=fetched_at or datetime.now(UTC),
    )
    with database.transaction() as connection:
        JobDescriptionRepository(connection).create(description)
    return description


def test_full_analysis_is_explainable_cached_and_historically_readable(database: Database) -> None:
    profile = _profile(database)
    job = _job(database)
    _description(database, job, "risk_german_sap_senior_finance.txt", DescriptionCompleteness.FULL)
    service = FitAnalysisService(database, _rules())

    first = service.analyze_job(job.id, profile.id)
    repeated = service.analyze_job(job.id, profile.id)

    assert first.cache_hit is False
    assert repeated.cache_hit is True
    assert repeated.analysis == first.analysis
    assert first.analysis.authority is AnalysisAuthority.AUTHORITATIVE
    assert first.analysis.fit_score <= 60
    assert {item.name for item in first.analysis.penalties} >= {
        "language_mismatch", "erp_ownership_gap", "seniority_gap",
        "finance_direct_experience_gap",
    }
    assert first.analysis.score_caps
    assert first.analysis.missing_skills
    with database.read_connection() as connection:
        restored = JobAnalysisRepository(connection).get(first.analysis.id)
    assert restored == first.analysis
    assert any(
        item.evidence_type is EvidenceType.NO_EVIDENCE
        for item in restored.evidence
    )


def test_profile_description_and_rule_versions_create_new_results(database: Database) -> None:
    profile = _profile(database)
    job = _job(database)
    _description(database, job, "full_data_analyst.txt", DescriptionCompleteness.FULL, "v1")
    service = FitAnalysisService(database, _rules())
    original = service.analyze_job(job.id, profile.id).analysis

    changed_payload = _payload()
    changed_payload["domains"] = [*changed_payload["domains"], "analytics"]
    with database.transaction() as connection:
        profile_v2 = CandidateProfileRepository(connection).create_version(
            changed_payload, profile_key="example"
        )
    profile_changed = service.analyze_job(job.id, profile_v2.id).analysis

    _description(
        database, job, "required_missing.txt", DescriptionCompleteness.FULL,
        "v2", datetime.now(UTC) + timedelta(minutes=1),
    )
    description_changed = service.analyze_job(job.id, profile.id).analysis
    changed_rules = _rules().model_copy(update={"rules_version": "m5-rules-v2"})
    rules_changed = FitAnalysisService(database, changed_rules).analyze_job(
        job.id, profile.id
    ).analysis
    changed_analyzer = _rules().model_copy(update={"analyzer_version": "m5-analyzer-v2"})
    analyzer_changed = FitAnalysisService(database, changed_analyzer).analyze_job(
        job.id, profile.id
    ).analysis

    assert len({
        original.id, profile_changed.id, description_changed.id,
        rules_changed.id, analyzer_changed.id,
    }) == 5
    assert service.get_analysis(original.id) == original


def test_snippet_and_missing_descriptions_are_prefilter_only(database: Database) -> None:
    profile = _profile(database)
    snippet_job = _job(database, source_id="snippet", title="Data Analyst")
    _description(database, snippet_job, "full_data_analyst.txt", DescriptionCompleteness.SNIPPET)
    missing_job = _job(database, source_id="missing", title="Data Analyst")
    service = FitAnalysisService(database, _rules())

    for job in (snippet_job, missing_job):
        analysis = service.analyze_job(job.id, profile.id).analysis
        assert analysis.authority is AnalysisAuthority.PREFILTER_ONLY
        assert analysis.fit_score is None
        assert analysis.prefilter_score is not None
        assert "prefilter-only" in analysis.completeness_warning


def test_equivalent_sources_receive_identical_analysis_components(database: Database) -> None:
    profile = _profile(database)
    analyses = []
    for source, source_id in (
        (JobSource.ARBEITSAGENTUR, "aa-equivalent"),
        (JobSource.ENGLISHJOBS, "ej-equivalent"),
    ):
        job = _job(database, source=source, source_id=source_id, title="Data Analyst")
        _description(database, job, "full_data_analyst.txt", DescriptionCompleteness.FULL)
        analyses.append(FitAnalysisService(database, _rules()).analyze_job(job.id, profile.id).analysis)
    left, right = analyses
    assert left.requirements == right.requirements
    assert left.evidence == right.evidence
    assert left.positive_components == right.positive_components
    assert left.penalties == right.penalties
    assert left.score_caps == right.score_caps
    assert left.fit_score == right.fit_score


def test_profile_analysis_and_ranking_cli_are_offline_and_explicit(
    monkeypatch, tmp_path, capsys,
) -> None:
    settings = settings_from_mapping(
        {
            "JOBHUNT_DATABASE_PATH": "m5-cli.sqlite3",
            "FIT_RULES_PATH": str(ROOT / "config" / "fit_rules.json"),
            "DEDUP_COMPANY_ALIASES_PATH": str(ROOT / "config" / "company_aliases.json"),
        },
        root=tmp_path,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main([
        "profile", "import", str(FIXTURES / "candidate_profile.json"),
        "--profile-key", "cli-candidate",
    ]) == 0
    profile_output = json.loads(capsys.readouterr().out)
    profile_id = profile_output["id"]
    assert cli.main(["profile", "list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["profile_key"] == "cli-candidate"
    assert cli.main(["profile", "show", profile_id]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == profile_id

    database = Database.from_settings(settings)
    migrate(database)
    job = _job(database, source_id="cli-job", title="Data Analyst")
    _description(database, job, "full_data_analyst.txt", DescriptionCompleteness.FULL)
    from app.services.deduplication import DeduplicationService
    DeduplicationService(database).backfill()

    analyze_args = ["analyze", "--profile-id", profile_id, "--job-id", str(job.id)]
    assert cli.main(analyze_args) == 0
    generated = json.loads(capsys.readouterr().out)[0]
    assert generated["authority"] == "authoritative"
    assert generated["generated"] is True
    assert generated["cache_hit"] is False
    assert cli.main(analyze_args) == 0
    cached = json.loads(capsys.readouterr().out)[0]
    assert cached["cache_hit"] is True
    assert cli.main(["analysis", "show", generated["analysis_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == generated["analysis_id"]
    assert cli.main([
        "rank", "--profile-id", profile_id,
        "--as-of", "2026-07-06T12:00:00+00:00",
    ]) == 0
    ranking = json.loads(capsys.readouterr().out)
    assert len(ranking) == 1
    assert ranking[0]["authority"] == "authoritative"
    assert ranking[0]["components"]
