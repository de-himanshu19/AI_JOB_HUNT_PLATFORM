from __future__ import annotations

import pytest

from app.db.connection import Database
from app.db.repositories import CollectionRunRepository
from app.domain.enums import CollectionRunStatus, JobSource
from app.services.collection import CollectionService
from app.sources.base import (
    CollectionError,
    CollectionRequest,
    CollectionResult,
    SourceRunStatus,
)


class ResultAdapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def collect(self, request):
        if self.error:
            raise self.error
        return self.result


def _request(*queries):
    return CollectionRequest(queries=queries or ("Data Analyst",))


def _stored_run(database: Database, run_id):
    with database.read_connection() as connection:
        return CollectionRunRepository(connection).get(run_id)


def test_all_queries_succeed(database: Database):
    result = CollectionResult(
        queries_executed=2,
        pages_requested=2,
        search_requests_succeeded=2,
        status=SourceRunStatus.COMPLETED,
    )
    report = CollectionService(database).execute(
        ResultAdapter(result), _request("Data", "Reporting"),
        source=JobSource.ARBEITSAGENTUR,
    )
    run = _stored_run(database, report.run_id)
    assert run.status is CollectionRunStatus.COMPLETED
    assert run.queries_executed == 2
    assert run.search_requests_succeeded == 2


@pytest.mark.parametrize(
    "failed_metric",
    ["search_requests_failed", "detail_requests_failed"],
)
def test_query_or_detail_failure_finalizes_partial(database: Database, failed_metric):
    values = {
        "queries_executed": 2,
        "search_requests_succeeded": 1,
        failed_metric: 1,
        "errors": [
            CollectionError(
                operation="search" if "search" in failed_metric else "detail",
                message="fixture failure",
                error_type="FixtureError",
            )
        ],
        "status": SourceRunStatus.COMPLETED_WITH_ERRORS,
    }
    report = CollectionService(database).execute(
        ResultAdapter(CollectionResult(**values)), _request("Data", "Reporting"),
        source=JobSource.ARBEITSAGENTUR,
    )
    run = _stored_run(database, report.run_id)
    assert run.status is CollectionRunStatus.PARTIAL
    assert getattr(run, failed_metric) == 1
    assert run.error_count == 1


def test_empty_search_results_complete_successfully(database: Database):
    report = CollectionService(database).execute(
        ResultAdapter(
            CollectionResult(
                queries_executed=1,
                pages_requested=1,
                search_requests_succeeded=1,
                status=SourceRunStatus.COMPLETED,
            )
        ),
        _request(),
        source=JobSource.ARBEITSAGENTUR,
    )
    assert _stored_run(database, report.run_id).status is CollectionRunStatus.COMPLETED
    assert report.source_result.jobs == []


def test_complete_adapter_failure_is_finalized(database: Database):
    report = CollectionService(database).execute(
        ResultAdapter(error=RuntimeError("adapter crashed")),
        _request(),
        source=JobSource.ARBEITSAGENTUR,
    )
    run = _stored_run(database, report.run_id)
    assert run.status is CollectionRunStatus.FAILED
    assert run.finished_at is not None
    assert run.error_count == 1
    assert "adapter crashed" in run.error_summary

