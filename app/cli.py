"""Non-UI commands for database and source collection workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.db.connection import Database
from app.db.migrations import migrate
from app.domain.enums import JobSource
from app.logging_config import configure_logging
from app.services.collection import CollectionService
from app.sources.arbeitsagentur.adapter import ArbeitsagenturAdapter
from app.sources.arbeitsagentur.client import (
    ArbeitsagenturClient,
    FixtureArbeitsagenturClient,
)
from app.sources.base import CollectionRequest, SourceRunStatus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-hunt")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect", help="Run one source adapter")
    collect.add_argument("source", choices=["arbeitsagentur"])
    collect.add_argument("--query", action="append", dest="queries")
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
                "pages_requested": result.pages_requested,
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect" and args.source == "arbeitsagentur":
        return _collect_arbeitsagentur(args)
    raise AssertionError("Unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())

