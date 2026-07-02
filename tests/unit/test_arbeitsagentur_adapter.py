from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings_from_mapping
from app.domain.enums import DescriptionCompleteness
from app.sources.arbeitsagentur.adapter import ArbeitsagenturAdapter
from app.sources.arbeitsagentur.client import ArbeitsagenturClientError
from app.sources.base import CollectionRequest, SourceRunStatus


FIXTURES = Path(__file__).parents[1] / "fixtures" / "arbeitsagentur"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _record(reference: str, title: str = "Data Analyst") -> dict:
    return {
        "referenznummer": reference,
        "stellenangebotsTitel": title,
        "firma": "Example GmbH",
        "kurzbeschreibung": "A useful summary description for this vacancy.",
    }


class FakeClient:
    def __init__(self, pages, details=None):
        self.pages = pages
        self.details = details or {}
        self.search_calls = []
        self.detail_calls = []

    def search(self, query, *, location, page, page_size, published_within_days):
        self.search_calls.append((query, page))
        outcome = self.pages.get((query, page), {"ergebnisliste": []})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def fetch_details(self, source_job_id, url=None):
        self.detail_calls.append(source_job_id)
        outcome = self.details.get(source_job_id, {})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def adapter_settings(tmp_path):
    return settings_from_mapping({}, root=tmp_path)


def _request(*queries, max_pages=5, page_size=25):
    return CollectionRequest(
        queries=queries or ("Data Analyst",),
        max_pages=max_pages,
        page_size=page_size,
    )


def test_single_page_and_full_detail(adapter_settings):
    client = FakeClient(
        {("Data Analyst", 1): {"maxErgebnisse": 1, "ergebnisliste": [_record("R1")]}},
        {"R1": _fixture("detail_full.json")},
    )
    result = ArbeitsagenturAdapter(adapter_settings, client).collect(_request())
    assert result.status is SourceRunStatus.COMPLETED
    assert result.pages_requested == 1
    assert result.detail_requests_succeeded == 1
    assert result.jobs[0].description.completeness is DescriptionCompleteness.FULL
    assert result.jobs[0].job.explicit_german_requirement == "German C1"


def test_multiple_pages_and_empty_final_page(adapter_settings):
    pages = {
        ("Data Analyst", 1): {"ergebnisliste": [_record("R1")]},
        ("Data Analyst", 2): {"ergebnisliste": [_record("R2")]},
        ("Data Analyst", 3): {"ergebnisliste": []},
    }
    result = ArbeitsagenturAdapter(adapter_settings, FakeClient(pages)).collect(
        _request(max_pages=5, page_size=1)
    )
    assert len(result.jobs) == 2
    assert result.pages_requested == 3
    assert result.search_requests_succeeded == 3


def test_configured_maximum_page_limit(adapter_settings):
    pages = {
        ("Data Analyst", 1): {"maxErgebnisse": 100, "ergebnisliste": [_record("R1")]},
        ("Data Analyst", 2): {"maxErgebnisse": 100, "ergebnisliste": [_record("R2")]},
    }
    client = FakeClient(pages)
    result = ArbeitsagenturAdapter(adapter_settings, client).collect(
        _request(max_pages=2, page_size=1)
    )
    assert len(result.jobs) == 2
    assert result.pages_requested == 2
    assert client.search_calls == [("Data Analyst", 1), ("Data Analyst", 2)]


def test_failed_middle_page_keeps_jobs_and_continues(adapter_settings):
    pages = {
        ("Data Analyst", 1): {"maxErgebnisse": 3, "ergebnisliste": [_record("R1")]},
        ("Data Analyst", 2): ArbeitsagenturClientError("temporary", retriable=True),
        ("Data Analyst", 3): {"maxErgebnisse": 3, "ergebnisliste": [_record("R3")]},
    }
    result = ArbeitsagenturAdapter(adapter_settings, FakeClient(pages)).collect(
        _request(max_pages=3, page_size=1)
    )
    assert {item.job.source_job_id for item in result.jobs} == {"R1", "R3"}
    assert result.search_requests_failed == 1
    assert result.status is SourceRunStatus.COMPLETED_WITH_ERRORS


def test_repeated_result_across_pages_stops_and_deduplicates(adapter_settings):
    page = {"ergebnisliste": [_record("R1")]}
    client = FakeClient({("Data Analyst", 1): page, ("Data Analyst", 2): page})
    result = ArbeitsagenturAdapter(adapter_settings, client).collect(
        _request(max_pages=10, page_size=1)
    )
    assert len(result.jobs) == 1
    assert result.pages_requested == 2
    assert client.detail_calls == ["R1"]


def test_same_source_reference_across_queries_is_one_job(adapter_settings):
    pages = {
        ("Data Analyst", 1): {"maxErgebnisse": 1, "ergebnisliste": [_record("R1")]},
        ("Reporting", 1): {"maxErgebnisse": 1, "ergebnisliste": [_record("R1")]},
    }
    result = ArbeitsagenturAdapter(adapter_settings, FakeClient(pages)).collect(
        _request("Data Analyst", "Reporting")
    )
    assert len(result.jobs) == 1
    assert result.jobs[0].description.structured_data["search_terms"] == [
        "Data Analyst", "Reporting"
    ]
    assert result.queries_executed == 2


def test_detail_failure_keeps_summary_as_snippet(adapter_settings):
    pages = {
        ("Data Analyst", 1): {"maxErgebnisse": 1, "ergebnisliste": [_record("R1")]}
    }
    details = {"R1": ArbeitsagenturClientError("detail failed", retriable=True)}
    result = ArbeitsagenturAdapter(adapter_settings, FakeClient(pages, details)).collect(
        _request()
    )
    assert len(result.jobs) == 1
    assert result.jobs[0].description.completeness is DescriptionCompleteness.SNIPPET
    assert result.detail_requests_failed == 1
    assert result.status is SourceRunStatus.COMPLETED_WITH_ERRORS


def test_missing_detail_and_summary_is_marked_missing(adapter_settings):
    record = _record("R1")
    record.pop("kurzbeschreibung")
    pages = {
        ("Data Analyst", 1): {"maxErgebnisse": 1, "ergebnisliste": [record]}
    }
    result = ArbeitsagenturAdapter(
        adapter_settings, FakeClient(pages, {"R1": {}})
    ).collect(_request())
    assert len(result.jobs) == 1
    assert result.jobs[0].description.completeness is DescriptionCompleteness.MISSING
    assert result.jobs[0].description.raw_text is None


def test_all_search_requests_fail(adapter_settings):
    client = FakeClient(
        {("Data Analyst", page): ArbeitsagenturClientError("down", retriable=True)
         for page in range(1, 4)}
    )
    result = ArbeitsagenturAdapter(adapter_settings, client).collect(
        _request(max_pages=3)
    )
    assert result.jobs == []
    assert result.search_requests_succeeded == 0
    assert result.status is SourceRunStatus.FAILED


def test_malformed_search_is_parse_error_not_http_failure(adapter_settings):
    result = ArbeitsagenturAdapter(
        adapter_settings,
        FakeClient({("Data Analyst", 1): {"ergebnisliste": {}}}),
    ).collect(_request(max_pages=1))
    assert result.status is SourceRunStatus.FAILED
    assert result.search_requests_succeeded == 1
    assert result.search_requests_failed == 0
    assert result.errors[0].operation == "search_parse"


def test_malformed_detail_keeps_job_without_double_counting_request(adapter_settings):
    pages = {
        ("Data Analyst", 1): {"maxErgebnisse": 1, "ergebnisliste": [_record("R1")]}
    }
    result = ArbeitsagenturAdapter(
        adapter_settings, FakeClient(pages, {"R1": []})
    ).collect(_request())
    assert len(result.jobs) == 1
    assert result.detail_requests_succeeded == 1
    assert result.detail_requests_failed == 0
    assert result.errors[0].operation == "detail_parse"


def test_empty_successful_search_is_completed(adapter_settings):
    result = ArbeitsagenturAdapter(
        adapter_settings,
        FakeClient({("Data Analyst", 1): {"ergebnisliste": []}}),
    ).collect(_request())
    assert result.jobs == []
    assert result.status is SourceRunStatus.COMPLETED
