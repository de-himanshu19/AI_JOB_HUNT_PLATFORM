"""Non-UI commands for database and source collection workflows."""

from __future__ import annotations

import argparse
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
from app.domain.enums import JobSource
from app.logging_config import configure_logging
from app.services.collection import CollectionService
from app.services.analysis_rules import AnalysisRules
from app.services.deduplication import DEDUPLICATION_VERSION, DeduplicationService
from app.services.fit_analysis import FitAnalysisService
from app.services.normalization import CompanyAliases
from app.services.ranking import RankingService
from app.sources.arbeitsagentur.adapter import ArbeitsagenturAdapter
from app.sources.arbeitsagentur.client import (
    ArbeitsagenturClient,
    FixtureArbeitsagenturClient,
)
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
    return parser


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect" and args.source == "arbeitsagentur":
        return _collect_arbeitsagentur(args)
    if args.command == "collect" and args.source == "englishjobs":
        return _collect_englishjobs(args)
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
    raise AssertionError("Unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())
