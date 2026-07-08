"""Non-UI commands for database and source collection workflows."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.db.connection import Database
from app.db.migrations import migrate
from app.db.repositories import (
    CandidateProfileRepository,
    DuplicateRepository,
    JobRepository,
)
from app.domain.duplicates import ReviewStatus
from app.domain.enums import ApplicationStatus, JobSource
from app.domain.legacy_import import LegacyArtifactKind, LegacyImportPlan, LegacySourceType
from app.logging_config import configure_logging
from app.services.collection import CollectionService
from app.services.cv_generation import CV_BUILDER_CONTENT_VERSION, CVGenerationService
from app.services.analysis_rules import AnalysisRules
from app.services.applications import ApplicationService
from app.services.deduplication import DEDUPLICATION_VERSION, DeduplicationService
from app.services.fit_analysis import FitAnalysisService
from app.services.legacy_import import LegacyImportService
from app.services.normalization import CompanyAliases
from app.services.notifications import NotificationFormatter, NotificationService
from app.services.pipeline import PipelineRunRequest, PipelineService
from app.services.ranking import RankingService
from app.integrations.telegram import TelegramClient
from app.integrations.ai import OllamaProvider
from app.sources.arbeitsagentur.adapter import ArbeitsagenturAdapter
from app.sources.arbeitsagentur.client import (
    ArbeitsagenturClient,
    FixtureArbeitsagenturClient,
    summarize_payload_shape,
)
from app.sources.arbeitsagentur.parser import parse_job_details, parse_search_page
from app.sources.englishjobs.adapter import EnglishJobsAdapter
from app.sources.englishjobs.client import (
    EnglishJobsClient,
    FixtureEnglishJobsClient,
)
from app.sources.base import CollectionRequest, SourceRunStatus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-hunt")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect", help="Run one source adapter")
    collect.add_argument("source", choices=["arbeitsagentur", "englishjobs"])
    collect.add_argument("--query", action="append", dest="queries")
    collect.add_argument("--state", action="append", dest="states")
    collect.add_argument("--location")
    collect.add_argument("--published-within-days", type=int)
    collect.add_argument("--max-pages", type=int)
    collect.add_argument("--page-size", type=int)
    mode = collect.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Use saved fixtures and do not write SQLite (default)",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="Explicitly enable live HTTP and SQLite persistence",
    )
    collect.add_argument(
        "--fixture-dir",
        type=Path,
        help="Fixture directory for offline dry-run mode",
    )

    diagnose = commands.add_parser(
        "diagnose", help="Run explicitly enabled, value-safe integration diagnostics"
    )
    diagnose_commands = diagnose.add_subparsers(
        dest="diagnose_command", required=True
    )
    aa_detail = diagnose_commands.add_parser(
        "arbeitsagentur-detail", help="Show one detail payload's structure, not values"
    )
    aa_detail.add_argument("--query", required=True)
    aa_detail.add_argument("--location")
    aa_detail.add_argument("--published-within-days", type=int)
    aa_detail.add_argument("--live", action="store_true", required=True)

    duplicates = commands.add_parser(
        "deduplicate", help="Normalize and review stored duplicate clusters"
    )
    duplicate_commands = duplicates.add_subparsers(dest="dedup_command", required=True)
    backfill = duplicate_commands.add_parser(
        "backfill", help="Normalize jobs and rebuild one algorithm version"
    )
    backfill.add_argument("--algorithm-version", default=DEDUPLICATION_VERSION)
    backfill.add_argument("--alias-file", type=Path)
    clear = duplicate_commands.add_parser(
        "clear", help="Remove one version's clusters and review candidates"
    )
    clear.add_argument("--algorithm-version", default=DEDUPLICATION_VERSION)
    review_list = duplicate_commands.add_parser(
        "review-list", help="List explainable gray-zone candidates"
    )
    review_list.add_argument("--algorithm-version", default=DEDUPLICATION_VERSION)
    review_list.add_argument(
        "--status", choices=[item.value for item in ReviewStatus], default="pending"
    )
    review = duplicate_commands.add_parser(
        "review", help="Approve or reject a gray-zone candidate"
    )
    review.add_argument("candidate_id")
    review.add_argument("--decision", choices=["approved", "rejected"], required=True)
    split = duplicate_commands.add_parser(
        "split", help="Split one job from its current versioned cluster"
    )
    split.add_argument("job_id")
    split.add_argument("--algorithm-version", default=DEDUPLICATION_VERSION)

    profile = commands.add_parser("profile", help="Manage versioned candidate profiles")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    profile_import = profile_commands.add_parser("import", help="Import a generic JSON candidate profile")
    profile_import.add_argument("path", type=Path)
    profile_import.add_argument("--profile-key")
    profile_commands.add_parser("list", help="List stored profile versions")
    profile_show = profile_commands.add_parser("show", help="Show one stored profile")
    profile_show.add_argument("profile_id")

    analyze = commands.add_parser("analyze", help="Analyze stored jobs offline")
    analyze.add_argument("--profile-id", required=True)
    analyze.add_argument("--job-id", action="append", dest="job_ids")
    analyze.add_argument("--rules-file", type=Path)

    analysis = commands.add_parser("analysis", help="Inspect a stored analysis")
    analysis_commands = analysis.add_subparsers(dest="analysis_command", required=True)
    analysis_show = analysis_commands.add_parser("show")
    analysis_show.add_argument("analysis_id")
    analysis_show.add_argument("--rules-file", type=Path)

    rank = commands.add_parser("rank", help="Rank Milestone 4 logical vacancies")
    rank.add_argument("--profile-id", required=True)
    rank.add_argument("--duplicate-version", default=DEDUPLICATION_VERSION)
    rank.add_argument("--ranking-version")
    rank.add_argument("--rules-file", type=Path)
    rank.add_argument("--as-of", help="ISO date/time; freshness is evaluated by UTC date")
    rank.add_argument("--include-prefilter-only", action="store_true")

    notify = commands.add_parser("notify", help="Preview and deliver notifications")
    notify_commands = notify.add_subparsers(dest="notify_command", required=True)
    telegram = notify_commands.add_parser("telegram", help="Telegram delivery workflow")
    telegram_commands = telegram.add_subparsers(dest="telegram_command", required=True)
    for action in ("preview", "send"):
        command = telegram_commands.add_parser(action)
        command.add_argument("--profile-id", required=True)
        command.add_argument("--ranking-version")
        command.add_argument("--duplicate-version", default=DEDUPLICATION_VERSION)
        command.add_argument("--top-n", type=int)
        command.add_argument("--min-rank-score", type=float)
        if action == "send":
            command.add_argument("--live", action="store_true", required=True)
    retry = telegram_commands.add_parser("retry")
    retry.add_argument("--batch-id", required=True)
    retry.add_argument("--live", action="store_true", required=True)
    notify_list = notify_commands.add_parser("list")
    notify_list.add_argument("--profile-id")
    notify_show = notify_commands.add_parser("show")
    notify_show.add_argument("batch_id")

    cv = commands.add_parser("cv", help="Generate and inspect truthful CV artifacts")
    cv_commands = cv.add_subparsers(dest="cv_command", required=True)
    cv_generate = cv_commands.add_parser("generate")
    cv_generate.add_argument("--job-id", required=True)
    cv_generate.add_argument("--profile-id", required=True)
    cv_generate.add_argument("--ai-polish", action="store_true")
    cv_generate.add_argument("--live-ai", action="store_true")
    cv_generate.add_argument("--force-regenerate", action="store_true")
    cv_generate.add_argument("--mark-cv-ready", action="store_true")
    cv_manual = cv_commands.add_parser("generate-manual")
    cv_manual.add_argument("--description-file", type=Path, required=True)
    cv_manual.add_argument("--profile-id", required=True)
    cv_manual.add_argument("--ai-polish", action="store_true")
    cv_manual.add_argument("--live-ai", action="store_true")
    cv_manual.add_argument("--force-regenerate", action="store_true")
    cv_list = cv_commands.add_parser("list")
    cv_list.add_argument("--job-id")
    cv_show = cv_commands.add_parser("show")
    cv_show.add_argument("artifact_id")

    legacy = commands.add_parser("legacy", help="Import legacy local files safely")
    legacy_commands = legacy.add_subparsers(dest="legacy_command", required=True)
    legacy_inventory = legacy_commands.add_parser("inventory")
    legacy_inventory.add_argument("--root", type=Path)
    legacy_backup = legacy_commands.add_parser("backup")
    legacy_backup.add_argument("--backup-dir", type=Path)
    legacy_dry = legacy_commands.add_parser("dry-run")
    legacy_dry.add_argument("--source", required=True, choices=_legacy_source_choices())
    legacy_dry.add_argument("--path", type=Path, required=True)
    legacy_apply = legacy_commands.add_parser("apply")
    legacy_apply.add_argument("--source", required=True, choices=_legacy_source_choices())
    legacy_apply.add_argument("--path", type=Path, required=True)
    legacy_apply.add_argument("--backup-id", required=True)
    legacy_apply.add_argument("--profile-key")
    legacy_apply.add_argument(
        "--artifact-kind",
        choices=[item.value for item in LegacyArtifactKind],
    )
    legacy_reconcile = legacy_commands.add_parser("reconcile")
    legacy_reconcile.add_argument("--batch-id", required=True)
    legacy_commands.add_parser("batches")
    legacy_show = legacy_commands.add_parser("show")
    legacy_show.add_argument("batch_id")
    legacy_verify = legacy_commands.add_parser("verify")
    legacy_verify.add_argument("batch_id")

    pipeline = commands.add_parser(
        "pipeline", help="Run safe local one-command workflow orchestration"
    )
    pipeline_commands = pipeline.add_subparsers(
        dest="pipeline_command", required=True
    )
    pipeline_run = pipeline_commands.add_parser("run")
    pipeline_run.add_argument("--profile-id", required=True)
    pipeline_run.add_argument("--query", default="Data Analyst")
    pipeline_run.add_argument("--location", default="Deutschland")
    pipeline_run.add_argument(
        "--source",
        action="append",
        help="Repeatable or comma-separated: arbeitsagentur, englishjobs",
    )
    pipeline_run.add_argument("--max-pages", type=int, default=1)
    pipeline_run.add_argument("--page-size", type=int, default=10)
    pipeline_run.add_argument("--top-n", type=int, default=10)
    pipeline_run.add_argument("--live-collect", action="store_true")
    pipeline_run.add_argument("--preview-notification", action="store_true")
    pipeline_run.add_argument("--include-prefilter-only", action="store_true")
    pipeline_run.add_argument("--output", type=Path)
    pipeline_run.add_argument("--no-dashboard-hint", action="store_true")

    applications = commands.add_parser(
        "applications", help="Track job applications locally"
    )
    application_commands = applications.add_subparsers(
        dest="applications_command", required=True
    )
    app_shortlist = application_commands.add_parser("shortlist")
    app_shortlist.add_argument("--profile-id", required=True)
    app_shortlist.add_argument("--job-id", required=True)
    app_shortlist.add_argument("--priority", choices=["high", "medium", "low"])
    app_shortlist.add_argument("--note")
    app_skip = application_commands.add_parser("skip")
    app_skip.add_argument("--profile-id", required=True)
    app_skip.add_argument("--job-id", required=True)
    app_skip.add_argument("--note")
    app_status = application_commands.add_parser("set-status")
    app_status.add_argument("--profile-id", required=True)
    app_status.add_argument("--job-id", required=True)
    app_status.add_argument(
        "--status", required=True, choices=[item.value for item in ApplicationStatus]
    )
    app_status.add_argument("--note")
    app_cv = application_commands.add_parser("cv-ready")
    app_cv.add_argument("--profile-id", required=True)
    app_cv.add_argument("--job-id", required=True)
    app_cv.add_argument("--cv-artifact-id")
    app_cv.add_argument("--note")
    app_follow = application_commands.add_parser("follow-up")
    app_follow.add_argument("--profile-id", required=True)
    app_follow.add_argument("--job-id", required=True)
    app_follow.add_argument("--date", required=True)
    app_follow.add_argument("--note")
    app_list = application_commands.add_parser("list")
    app_list.add_argument("--profile-id", required=True)
    app_list.add_argument("--status", choices=[item.value for item in ApplicationStatus])
    app_due = application_commands.add_parser("due")
    app_due.add_argument("--profile-id", required=True)
    app_due.add_argument("--date")
    app_history = application_commands.add_parser("history")
    app_history.add_argument("--profile-id", required=True)
    app_history.add_argument("--job-id", required=True)
    return parser


def _legacy_source_choices() -> list[str]:
    return [
        "englishjobs-csv",
        "state-intelligence-csv",
        "sent-jobs-json",
        "master-cv-json",
        "legacy-artifact",
        "mysql-fixture",
    ]


def _legacy_source(value: str) -> LegacySourceType:
    return LegacySourceType(value.replace("-", "_"))


def _pipeline_sources(values: list[str] | None) -> tuple[JobSource, ...]:
    raw = values or [JobSource.ARBEITSAGENTUR.value]
    normalized: list[JobSource] = []
    for value in raw:
        for part in value.split(","):
            source = part.strip().casefold()
            if not source:
                continue
            try:
                parsed = JobSource(source)
            except ValueError as error:
                raise ValueError(f"Invalid pipeline source: {part.strip()}") from error
            if parsed not in {JobSource.ARBEITSAGENTUR, JobSource.ENGLISHJOBS}:
                raise ValueError(f"Invalid pipeline source: {part.strip()}")
            if parsed not in normalized:
                normalized.append(parsed)
    if not normalized:
        raise ValueError("At least one pipeline source is required")
    return tuple(normalized)


def _description_completeness_counts(result) -> dict[str, int]:
    counts = Counter(
        collected.description.completeness.value for collected in result.jobs
    )
    return {key: counts.get(key, 0) for key in ("full", "snippet", "missing")}


def _collect_arbeitsagentur(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    is_live = bool(args.live)
    queries = tuple(args.queries or (
        settings.arbeitsagentur_queries if is_live
        else settings.arbeitsagentur_queries[:1]
    ))
    request = CollectionRequest(
        queries=queries,
        location=args.location or settings.arbeitsagentur_location,
        published_within_days=(
            args.published_within_days
            if args.published_within_days is not None
            else settings.arbeitsagentur_published_within_days
        ),
        max_pages=(
            args.max_pages
            if args.max_pages is not None
            else settings.arbeitsagentur_max_pages
        ),
        page_size=(
            args.page_size
            if args.page_size is not None
            else settings.arbeitsagentur_page_size
        ),
    )

    database = Database.from_settings(settings)
    if is_live:
        migrate(database)
        client = ArbeitsagenturClient(settings)
    else:
        fixture_dir = args.fixture_dir or (
            settings.repo_root / "tests" / "fixtures" / "arbeitsagentur"
        )
        client = FixtureArbeitsagenturClient(fixture_dir)

    adapter = ArbeitsagenturAdapter(settings, client)
    report = CollectionService(database).execute(
        adapter,
        request,
        source=JobSource.ARBEITSAGENTUR,
        dry_run=not is_live,
    )
    result = report.source_result
    print(
        json.dumps(
            {
                "mode": "live" if is_live else "dry-run",
                "status": result.status.value,
                "jobs_collected": len(result.jobs),
                "would_or_did_insert": report.jobs_inserted,
                "would_or_did_update": report.jobs_updated,
                "description_versions_inserted": report.description_versions_inserted,
                "description_completeness": _description_completeness_counts(result),
                "queries_executed": result.queries_executed,
                "states_executed": result.states_executed,
                "pages_requested": result.pages_requested,
                "jobs_parsed": result.jobs_parsed,
                "invalid_cards": result.invalid_cards,
                "repeated_pages": result.repeated_pages,
                "search_requests_succeeded": result.search_requests_succeeded,
                "search_requests_failed": result.search_requests_failed,
                "detail_requests_succeeded": result.detail_requests_succeeded,
                "detail_requests_failed": result.detail_requests_failed,
                "errors": [error.model_dump(mode="json") for error in result.errors],
                "database_modified": is_live,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if result.status is SourceRunStatus.FAILED else 0


def _collect_englishjobs(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    is_live = bool(args.live)
    queries = tuple(args.queries or ())
    states = tuple(
        args.states
        or (
            settings.englishjobs_states
            if is_live
            else settings.englishjobs_states[:1]
        )
    )
    request = CollectionRequest(
        queries=queries,
        states=states,
        location=args.location or "Germany",
        max_pages=(
            args.max_pages
            if args.max_pages is not None
            else settings.englishjobs_max_pages
        ),
        page_size=(
            args.page_size
            if args.page_size is not None
            else settings.englishjobs_page_size
        ),
    )

    database = Database.from_settings(settings)
    if is_live:
        migrate(database)
        client = EnglishJobsClient(settings)
    else:
        fixture_dir = args.fixture_dir or (
            settings.repo_root / "tests" / "fixtures" / "englishjobs"
        )
        client = FixtureEnglishJobsClient(
            fixture_dir,
            base_url=settings.englishjobs_base_url,
        )

    adapter = EnglishJobsAdapter(settings, client)
    report = CollectionService(database).execute(
        adapter,
        request,
        source=JobSource.ENGLISHJOBS,
        dry_run=not is_live,
    )
    result = report.source_result
    print(
        json.dumps(
            {
                "mode": "live" if is_live else "dry-run",
                "status": result.status.value,
                "jobs_collected": len(result.jobs),
                "would_or_did_insert": report.jobs_inserted,
                "would_or_did_update": report.jobs_updated,
                "description_versions_inserted": report.description_versions_inserted,
                "description_completeness": _description_completeness_counts(result),
                "queries_executed": result.queries_executed,
                "states_executed": result.states_executed,
                "pages_requested": result.pages_requested,
                "jobs_parsed": result.jobs_parsed,
                "invalid_cards": result.invalid_cards,
                "repeated_pages": result.repeated_pages,
                "search_requests_succeeded": result.search_requests_succeeded,
                "search_requests_failed": result.search_requests_failed,
                "detail_requests_succeeded": result.detail_requests_succeeded,
                "detail_requests_failed": result.detail_requests_failed,
                "errors": [error.model_dump(mode="json") for error in result.errors],
                "database_modified": is_live,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if result.status is SourceRunStatus.FAILED else 0


def _diagnose(args: argparse.Namespace) -> int:
    if args.diagnose_command != "arbeitsagentur-detail":
        raise AssertionError("Unhandled diagnostic command")
    settings = get_settings()
    configure_logging(settings)
    client = ArbeitsagenturClient(settings)
    query = args.query.strip()
    location = args.location or settings.arbeitsagentur_location
    published_within_days = (
        args.published_within_days
        if args.published_within_days is not None
        else settings.arbeitsagentur_published_within_days
    )
    search_payload = client.search(
        query,
        location=location,
        page=1,
        page_size=1,
        published_within_days=published_within_days,
    )
    page = parse_search_page(
        search_payload,
        search_term=query,
        detail_base_url=settings.arbeitsagentur_detail_url,
    )
    if not page.jobs:
        print(json.dumps({"status": "no_results", "live_request": True}, indent=2))
        return 1
    summary = page.jobs[0]
    payload = client.fetch_details(summary.source_job_id, summary.source_detail_url)
    details = parse_job_details(
        payload,
        source_job_id=summary.source_job_id,
        source_url=summary.source_detail_url,
    )
    print(json.dumps({
        "status": "ok",
        "live_request": True,
        "payload_values_included": False,
        "description_extracted": bool(details.description),
        "description_length": len(details.description or ""),
        "payload_shape": summarize_payload_shape(payload),
    }, ensure_ascii=True, indent=2))
    return 0


def _deduplicate(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    database = Database.from_settings(settings)
    migrate(database)
    alias_path = getattr(args, "alias_file", None) or settings.company_aliases_path
    service = DeduplicationService(
        database, aliases=CompanyAliases.from_json(alias_path)
    )

    if args.dedup_command == "backfill":
        report = service.backfill(algorithm_version=args.algorithm_version)
        print(json.dumps(report.__dict__, ensure_ascii=False, indent=2))
        return 0
    if args.dedup_command == "clear":
        service.clear_version(args.algorithm_version)
        print(json.dumps({"cleared_algorithm_version": args.algorithm_version}, indent=2))
        return 0
    if args.dedup_command == "review-list":
        with database.read_connection() as connection:
            candidates = DuplicateRepository(connection).list_candidates(
                args.algorithm_version, status=ReviewStatus(args.status)
            )
        print(
            json.dumps(
                [candidate.model_dump(mode="json") for candidate in candidates],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.dedup_command == "review":
        service.review_candidate(args.candidate_id, ReviewStatus(args.decision))
        print(
            json.dumps(
                {"candidate_id": args.candidate_id, "decision": args.decision}, indent=2
            )
        )
        return 0
    if args.dedup_command == "split":
        cluster_id = service.split_job(args.job_id, args.algorithm_version)
        print(
            json.dumps(
                {
                    "job_id": args.job_id,
                    "algorithm_version": args.algorithm_version,
                    "new_cluster_id": str(cluster_id),
                },
                indent=2,
            )
        )
        return 0
    raise AssertionError("Unhandled deduplicate command")


def _profile(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database.from_settings(settings)
    migrate(database)
    if args.profile_command == "import":
        payload = json.loads(args.path.read_text(encoding="utf-8"))
        with database.transaction() as connection:
            profile = CandidateProfileRepository(connection).create_version(
                payload, profile_key=args.profile_key
            )
        print(json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0
    with database.read_connection() as connection:
        repository = CandidateProfileRepository(connection)
        if args.profile_command == "list":
            profiles = repository.list_all()
            print(json.dumps([
                {
                    "id": str(item.id), "profile_key": item.profile_key,
                    "version": item.version, "display_name": item.display_name,
                    "active": item.active, "content_hash": item.content_hash,
                }
                for item in profiles
            ], ensure_ascii=False, indent=2))
            return 0
        if args.profile_command == "show":
            profile = repository.get(args.profile_id)
            if profile is None:
                raise KeyError(f"Candidate profile not found: {args.profile_id}")
            print(json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return 0
    raise AssertionError("Unhandled profile command")


def _rules(settings, args) -> AnalysisRules:
    path = getattr(args, "rules_file", None) or settings.fit_rules_path
    rules = AnalysisRules.from_json(path)
    ranking_version = getattr(args, "ranking_version", None)
    return rules.model_copy(update={"ranking_version": ranking_version}) if ranking_version else rules


def _analyze(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    database = Database.from_settings(settings)
    migrate(database)
    rules = _rules(settings, args)
    service = FitAnalysisService(database, rules)
    with database.read_connection() as connection:
        job_ids = args.job_ids or [str(job.id) for job in JobRepository(connection).list_all()]
    output = []
    for job_id in job_ids:
        execution = service.analyze_job(job_id, args.profile_id)
        analysis = execution.analysis
        output.append({
            "analysis_id": str(analysis.id), "job_id": str(analysis.job_id),
            "authority": analysis.authority.value, "cache_hit": execution.cache_hit,
            "generated": not execution.cache_hit,
            "description_completeness": analysis.description_completeness,
            "completeness_warning": analysis.completeness_warning,
            "prefilter_score": analysis.prefilter_score, "fit_score": analysis.fit_score,
            "missing_evidence": list(analysis.missing_skills),
            "risk_flags": list(analysis.risk_flags),
            "positive_components": [item.model_dump(mode="json") for item in analysis.positive_components],
            "penalties": [item.model_dump(mode="json") for item in analysis.penalties],
            "score_caps": [item.model_dump(mode="json") for item in analysis.score_caps],
            "analyzer_version": analysis.analyzer_version,
            "rules_version": analysis.rules_version,
            "ranking_version": analysis.ranking_version,
            "profile_version": analysis.profile_version,
            "description_version": analysis.description_content_hash,
        })
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _analysis(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database.from_settings(settings)
    migrate(database)
    analysis = FitAnalysisService(database, _rules(settings, args)).get_analysis(
        args.analysis_id
    )
    print(json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def _rank(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    database = Database.from_settings(settings)
    migrate(database)
    rules = _rules(settings, args)
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
    ranked = RankingService(database, rules).rank(
        args.profile_id, args.duplicate_version, as_of=as_of,
        include_prefilter_only=args.include_prefilter_only,
    )
    print(json.dumps([
        {
            "position": index, "job_id": str(item.job.id),
            "cluster_id": str(item.ranking.cluster_id),
            "title": item.job.title_raw, "company": item.job.company_raw,
            "authority": item.ranking.authority.value,
            "rank_score": item.ranking.rank_score,
            "components": [component.model_dump(mode="json") for component in item.ranking.components],
            "ranking_version": item.ranking.ranking_version,
            "analysis_cache_hit": item.analysis_cache_hit,
            "ranking_cache_hit": item.ranking_cache_hit,
        }
        for index, item in enumerate(ranked, start=1)
    ], ensure_ascii=False, indent=2))
    return 0


def _notification_json(report):
    return {
        "batch": (
            report.batch.model_dump(mode="json") if report.batch else None
        ),
        "deliveries": [
            item.model_dump(mode="json") for item in report.deliveries
        ],
    }


def _notify(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    database = Database.from_settings(settings)
    migrate(database)
    formatter = NotificationFormatter(settings.telegram_message_max_chars)

    if args.notify_command == "list":
        batches = NotificationService(
            database, formatter=formatter
        ).list_batches(args.profile_id)
        print(json.dumps([
            batch.model_dump(mode="json") for batch in batches
        ], ensure_ascii=False, indent=2))
        return 0
    if args.notify_command == "show":
        batch, items, deliveries = NotificationService(
            database, formatter=formatter
        ).batch_details(args.batch_id)
        print(json.dumps({
            "batch": batch.model_dump(mode="json"),
            "items": [item.model_dump(mode="json") for item in items],
            "deliveries": [item.model_dump(mode="json") for item in deliveries],
        }, ensure_ascii=False, indent=2))
        return 0

    if args.telegram_command == "preview":
        ranking_version = args.ranking_version or AnalysisRules.from_json(
            settings.fit_rules_path
        ).ranking_version
        preview = NotificationService(database, formatter=formatter).preview(
            profile_id=args.profile_id,
            ranking_version=ranking_version,
            duplicate_algorithm_version=args.duplicate_version,
            top_n=args.top_n or settings.telegram_top_n,
            min_rank_score=(
                args.min_rank_score
                if args.min_rank_score is not None
                else settings.telegram_min_rank_score
            ),
        )
        print(json.dumps({
            "mode": "preview", "network_requested": False,
            "database_modified": False,
            "selected_count": preview.selected_count,
            "chunks": [
                {"index": chunk.index, "characters": len(chunk.text), "text": chunk.text}
                for chunk in preview.chunks
            ],
        }, ensure_ascii=False, indent=2))
        return 0

    if not args.live or not settings.telegram_enabled:
        raise ValueError(
            "Live Telegram delivery requires --live and TELEGRAM_ENABLED=true"
        )
    service = NotificationService(
        database, formatter=formatter, client=TelegramClient(settings)
    )
    if args.telegram_command == "send":
        ranking_version = args.ranking_version or AnalysisRules.from_json(
            settings.fit_rules_path
        ).ranking_version
        report = service.send(
            profile_id=args.profile_id,
            ranking_version=ranking_version,
            duplicate_algorithm_version=args.duplicate_version,
            top_n=args.top_n or settings.telegram_top_n,
            min_rank_score=(
                args.min_rank_score
                if args.min_rank_score is not None
                else settings.telegram_min_rank_score
            ),
        )
    elif args.telegram_command == "retry":
        report = service.retry(args.batch_id)
    else:
        raise AssertionError("Unhandled Telegram command")
    print(json.dumps(_notification_json(report), ensure_ascii=False, indent=2))
    return 0


def _artifact_json(artifact):
    return {
        "artifact_id": str(artifact.id),
        "source": artifact.source.value,
        "generation_mode": artifact.generation_mode.value,
        "job_id": str(artifact.job_id) if artifact.job_id else None,
        "logical_cluster_id": (
            str(artifact.logical_cluster_id) if artifact.logical_cluster_id else None
        ),
        "description_id": str(artifact.description_id) if artifact.description_id else None,
        "description_hash": artifact.description_content_hash,
        "profile_id": str(artifact.profile_id),
        "profile_version": artifact.profile_version,
        "profile_hash": artifact.profile_content_hash,
        "analysis_id": str(artifact.analysis_id) if artifact.analysis_id else None,
        "analyzer_version": artifact.analyzer_version,
        "rules_version": artifact.rules_version,
        "generator_version": artifact.generator_version,
        "formatter_version": artifact.formatter_version,
        "artifact_path": str(artifact.artifact_path),
        "evidence_report_path": str(artifact.evidence_report_path),
        "content_hash": artifact.content_hash,
        "validated": artifact.validated,
        "validation_result": artifact.validation_result,
        "parent_rule_based_artifact_id": (
            str(artifact.parent_rule_based_artifact_id)
            if artifact.parent_rule_based_artifact_id else None
        ),
        "provider": artifact.provider,
        "model": artifact.model,
        "prompt_version": artifact.prompt_version,
        "created_at": artifact.created_at.isoformat(),
    }


def _application_json(application):
    return {
        "id": str(application.id),
        "profile_id": str(application.profile_id),
        "job_id": str(application.job_id),
        "logical_cluster_id": (
            str(application.logical_cluster_id)
            if application.logical_cluster_id else None
        ),
        "current_status": application.status.value,
        "priority": application.priority.value if application.priority else None,
        "notes": application.notes,
        "follow_up_date": (
            application.follow_up_date.isoformat()
            if application.follow_up_date else None
        ),
        "cv_artifact_id": (
            str(application.cv_artifact_id) if application.cv_artifact_id else None
        ),
        "source": application.source,
        "created_at": application.created_at.isoformat(),
        "updated_at": application.updated_at.isoformat(),
    }


def _application_event_json(event):
    return {
        "id": str(event.id),
        "application_id": str(event.application_id),
        "old_status": event.from_status.value if event.from_status else None,
        "new_status": event.to_status.value,
        "event_type": event.event_type,
        "note": event.note,
        "created_at": event.created_at.isoformat(),
    }


def _cv(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    database = Database.from_settings(settings)
    migrate(database)
    rules = AnalysisRules.from_json(settings.fit_rules_path)
    wants_ai = bool(getattr(args, "ai_polish", False))
    live_ai = bool(getattr(args, "live_ai", False))
    provider = None
    if wants_ai and live_ai:
        if settings.ai_provider != "rule_based":
            provider = OllamaProvider(settings)
    service = CVGenerationService(
        database, settings, rules, provider=provider
    )
    if args.cv_command == "generate":
        result = service.generate_for_job(
            args.job_id, args.profile_id,
            ai_polish=wants_ai, live_ai=live_ai,
            force_regenerate=args.force_regenerate,
        )
    elif args.cv_command == "generate-manual":
        result = service.generate_manual_file(
            args.description_file, args.profile_id,
            ai_polish=wants_ai, live_ai=live_ai,
            force_regenerate=args.force_regenerate,
        )
    elif args.cv_command == "list":
        artifacts = service.list_artifacts(args.job_id)
        print(json.dumps(
            [_artifact_json(item) for item in artifacts], ensure_ascii=False, indent=2
        ))
        return 0
    elif args.cv_command == "show":
        artifact, attempts = service.artifact_details(args.artifact_id)
        output = _artifact_json(artifact)
        output["ai_attempts"] = [
            item.model_dump(mode="json") for item in attempts
        ]
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    else:
        raise AssertionError("Unhandled CV command")

    output = {
        "authoritative_rule_based_artifact": _artifact_json(
            result.rule_based_artifact
        ),
        "cached_artifact_reused": result.cache_hit,
        "force_regenerate_requested": bool(getattr(args, "force_regenerate", False)),
        "builder_content_version": CV_BUILDER_CONTENT_VERSION,
        "ai_polish_requested": wants_ai,
        "ai_status": result.ai_status,
        "ai_failure_category": result.ai_failure_category,
        "ai_artifact": _artifact_json(result.ai_artifact) if result.ai_artifact else None,
        "suggested_next_state": "cv_ready",
        "application_status_changed": False,
    }
    if (
        args.cv_command == "generate"
        and getattr(args, "mark_cv_ready", False)
    ):
        application = ApplicationService(database).mark_cv_ready(
            args.profile_id,
            args.job_id,
            cv_artifact_id=result.rule_based_artifact.id,
            note="CV generated and marked ready from CLI",
        )
        output["application_status_changed"] = True
        output["application"] = _application_json(application)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _applications(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    database = Database.from_settings(settings)
    migrate(database)
    service = ApplicationService(database)
    command = args.applications_command
    if command == "shortlist":
        output = _application_json(service.shortlist_job(
            args.profile_id, args.job_id, priority=args.priority, note=args.note
        ))
    elif command == "skip":
        output = _application_json(service.skip_job(
            args.profile_id, args.job_id, note=args.note
        ))
    elif command == "set-status":
        output = _application_json(service.set_status(
            profile_id=args.profile_id,
            job_id=args.job_id,
            status=args.status,
            note=args.note,
        ))
    elif command == "cv-ready":
        output = _application_json(service.mark_cv_ready(
            args.profile_id,
            args.job_id,
            cv_artifact_id=args.cv_artifact_id,
            note=args.note,
        ))
    elif command == "follow-up":
        output = _application_json(service.set_follow_up(
            profile_id=args.profile_id,
            job_id=args.job_id,
            follow_up_date=args.date,
            note=args.note,
        ))
    elif command == "list":
        output = [
            _application_json(item)
            for item in service.list_applications(args.profile_id, args.status)
        ]
    elif command == "due":
        output = [
            _application_json(item)
            for item in service.list_due_followups(args.profile_id, args.date)
        ]
    elif command == "history":
        with database.read_connection() as connection:
            application = service._resolve_application(  # noqa: SLF001 - CLI read helper.
                connection,
                application_id=None,
                profile_id=args.profile_id,
                job_id=args.job_id,
                create=False,
            )
        output = [
            _application_event_json(item)
            for item in service.history(application.id)
        ]
    else:
        raise AssertionError("Unhandled applications command")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _legacy_plan_json(plan: LegacyImportPlan) -> dict[str, object]:
    return {
        "source_type": plan.source_type.value,
        "source_name": plan.source_name,
        "source_path": str(plan.source_path) if plan.source_path else None,
        "source_checksum": plan.source_checksum,
        "batch_id": str(plan.batch_id) if plan.batch_id else None,
        "backup_id": str(plan.backup_id) if plan.backup_id else None,
        "records_read": plan.records_read,
        "creates": plan.creates,
        "updates": plan.updates,
        "skips": plan.skips,
        "conflicts": plan.conflicts,
        "uncertain": plan.uncertain,
        "rejected": plan.rejected,
        "warnings": list(plan.warnings),
        "reconciliation": plan.reconciliation,
        "database_modified": plan.database_modified,
        "network_requested": plan.network_requested,
        "idempotent_replay": plan.idempotent_replay,
        "sample_items": [
            item.model_dump(mode="json") for item in plan.items[:20]
        ],
    }


def _legacy(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    database = Database.from_settings(settings)
    service = LegacyImportService(database, settings)

    if args.legacy_command == "inventory":
        print(json.dumps(
            service.inventory(args.root), ensure_ascii=False, indent=2
        ))
        return 0
    if args.legacy_command == "dry-run":
        plan = service.dry_run(_legacy_source(args.source), args.path)
        print(json.dumps(_legacy_plan_json(plan), ensure_ascii=False, indent=2))
        return 0

    migrate(database)
    if args.legacy_command == "backup":
        backup = service.create_backup(args.backup_dir)
        print(json.dumps(backup.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0
    if args.legacy_command == "apply":
        source_type = _legacy_source(args.source)
        plan = service.apply(
            source_type,
            args.path,
            backup_id=args.backup_id,
            profile_key=args.profile_key,
            artifact_kind=args.artifact_kind,
        )
        output = _legacy_plan_json(plan)
        if source_type in {
            LegacySourceType.ENGLISHJOBS_CSV,
            LegacySourceType.STATE_INTELLIGENCE_CSV,
        } and not plan.idempotent_replay:
            alias_path = settings.company_aliases_path
            dedup_report = DeduplicationService(
                database, aliases=CompanyAliases.from_json(alias_path)
            ).backfill(algorithm_version=DEDUPLICATION_VERSION)
            output["deduplication"] = dedup_report.__dict__
            output["current_analysis_required"] = True
            output["legacy_scores_authoritative"] = False
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    if args.legacy_command == "reconcile":
        print(json.dumps(
            service.reconcile(args.batch_id), ensure_ascii=False, indent=2
        ))
        return 0
    if args.legacy_command == "batches":
        print(json.dumps(
            [batch.model_dump(mode="json") for batch in service.batches()],
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    if args.legacy_command == "show":
        batch, items = service.show(args.batch_id)
        print(json.dumps({
            "batch": batch.model_dump(mode="json"),
            "items": [item.model_dump(mode="json") for item in items],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.legacy_command == "verify":
        print(json.dumps(
            service.verify(args.batch_id), ensure_ascii=False, indent=2
        ))
        return 0
    raise AssertionError("Unhandled legacy command")


def _pipeline(args: argparse.Namespace) -> int:
    if args.pipeline_command != "run":
        raise AssertionError("Unhandled pipeline command")
    settings = get_settings()
    configure_logging(settings)
    database = Database.from_settings(settings)
    migrate(database)
    rules = AnalysisRules.from_json(settings.fit_rules_path)
    service = PipelineService(
        database,
        settings,
        rules,
        aliases=CompanyAliases.from_json(settings.company_aliases_path),
    )
    summary = service.run(PipelineRunRequest(
        profile_id=args.profile_id,
        query=args.query,
        location=args.location,
        sources=_pipeline_sources(args.source),
        max_pages=args.max_pages,
        page_size=args.page_size,
        top_n=args.top_n,
        live_collect=args.live_collect,
        preview_notification=args.preview_notification,
        include_prefilter_only=args.include_prefilter_only,
        output_path=args.output,
        dashboard_hint=not args.no_dashboard_hint,
    ))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect" and args.source == "arbeitsagentur":
        return _collect_arbeitsagentur(args)
    if args.command == "collect" and args.source == "englishjobs":
        return _collect_englishjobs(args)
    if args.command == "diagnose":
        return _diagnose(args)
    if args.command == "deduplicate":
        return _deduplicate(args)
    if args.command == "profile":
        return _profile(args)
    if args.command == "analyze":
        return _analyze(args)
    if args.command == "analysis":
        return _analysis(args)
    if args.command == "rank":
        return _rank(args)
    if args.command == "notify":
        return _notify(args)
    if args.command == "cv":
        return _cv(args)
    if args.command == "legacy":
        return _legacy(args)
    if args.command == "pipeline":
        return _pipeline(args)
    if args.command == "applications":
        return _applications(args)
    raise AssertionError("Unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())
