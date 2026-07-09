from __future__ import annotations

import pytest

from app.config import settings_from_mapping
from app.domain.enums import DescriptionCompleteness
from app.sources.base import CollectionRequest, SourceRunStatus
from app.sources.englishjobs.adapter import EnglishJobsAdapter
from app.sources.englishjobs.client import EnglishJobsClientError


STATE_PAGE = """
<html><body>
<h1>3 English-speaking jobs in Bayern</h1>
<div class="job js-job" data-job-id="listing-100">
  <a class="js-joblink" href="/jobs/internal-100">Data Analyst</a>
  <span>Insight GmbH</span><span>Munich, Bayern</span><span>June 12</span>
  <p>Snippet one.</p><a href="/clickout/track-100"></a>
</div>
<div class="job js-job" data-job-id="listing-300">
  <a class="js-joblink" href="/clickout/track-300">Operations Analyst</a>
  <span>Global Ops AG</span><span>Nuremberg, Bayern</span><span>June 10</span>
  <p>Snippet three.</p>
</div>
<a rel="next" href="/in/bayern?page=2">Next</a>
</body></html>
"""

QUERY_PAGE = """
<html><body>
<h1>2 jobs</h1>
<div class="job js-job" data-job-id="listing-100">
  <a class="js-joblink" href="/jobs/internal-100">Data Analyst</a>
  <span>Insight GmbH</span><span>Munich, Bayern</span><span>June 12</span>
  <p>Snippet one.</p>
</div>
<div class="job js-job" data-job-id="listing-200">
  <a class="js-joblink" href="/jobs/internal-200">Senior Data Analyst</a>
  <span>Northwind GmbH</span><span>Berlin</span><span>June 11</span>
  <p>Snippet two.</p>
</div>
</body></html>
"""

DETAIL_FULL = """
<html><head><link rel="canonical" href="https://englishjobs.de/jobs/internal-100"/></head>
<body><main><h1>Data Analyst</h1><div class="company">Insight GmbH</div><div class="location">Munich, Bayern</div>
<div class="job-description">
Full EnglishJobs description for a Data Analyst role. Responsibilities include
building SQL reporting workflows, validating source data, reconciling records,
maintaining Excel checks, preparing Power BI inputs, and documenting recurring
KPI outputs for finance and operations stakeholders. The role works closely
with business teams to understand requirements, translate questions into
analysis, and communicate findings clearly.

Your tasks include improving data quality, reviewing dashboard inputs,
supporting monthly reporting, tracking process exceptions, and preparing
structured summaries for decision makers. Requirements include practical SQL
experience, strong Excel skills, careful validation habits, and the ability to
explain data issues to non-technical colleagues.

Qualifications in data analytics, business reporting, information systems, or a
related field are helpful. The successful candidate profile combines curiosity,
attention to detail, stakeholder coordination, and reliable documentation. The
team offers benefits including hybrid work options, learning opportunities,
collaboration with international colleagues, and exposure to reporting projects
that improve real business processes.
</div></main></body></html>
"""

DETAIL_SHORT = """
<html><head><link rel="canonical" href="https://englishjobs.de/jobs/internal-200"/></head>
<body><div class="job-description">Short text</div></body></html>
"""

DETAIL_APPLY_ONLY = """
<html><head><link rel="canonical" href="https://englishjobs.de/jobs/internal-200"/></head>
<body><main><h1>Senior Data Analyst</h1><p>Apply now to continue to the company career page.</p></main></body></html>
"""


class FakeClient:
    def __init__(self, state_pages=None, query_pages=None, documents=None):
        self.state_pages = state_pages or {}
        self.query_pages = query_pages or {}
        self.documents = documents or {}
        self.detail_calls = []

    def search_state(self, state_slug, *, page):
        outcome = self.state_pages.get((state_slug, page), "<html></html>")
        if isinstance(outcome, Exception):
            raise outcome
        return type("Doc", (), {"text": outcome, "final_url": f"https://englishjobs.de/in/{state_slug}"})()

    def search_query(self, query, *, location, page):
        outcome = self.query_pages.get((query, location, page), "<html></html>")
        if isinstance(outcome, Exception):
            raise outcome
        return type("Doc", (), {"text": outcome, "final_url": "https://englishjobs.de/jobs"})()

    def fetch_document(self, url, *, operation):
        self.detail_calls.append((operation, url))
        outcome = self.documents.get(url, ("", url))
        if isinstance(outcome, Exception):
            raise outcome
        text, final_url = outcome
        return type("Doc", (), {"text": text, "final_url": final_url})()


@pytest.fixture
def adapter_settings(tmp_path):
    return settings_from_mapping({}, root=tmp_path)


def test_state_and_query_collection_deduplicates_and_merges_provenance(adapter_settings):
    client = FakeClient(
        state_pages={("bayern", 1): STATE_PAGE},
        query_pages={("Data Analyst", "Germany", 1): QUERY_PAGE},
        documents={
            "https://englishjobs.de/jobs/internal-100": (
                DETAIL_FULL,
                "https://englishjobs.de/jobs/internal-100",
            ),
            "https://englishjobs.de/jobs/internal-200": (
                DETAIL_SHORT,
                "https://englishjobs.de/jobs/internal-200",
            ),
        },
    )
    result = EnglishJobsAdapter(adapter_settings, client).collect(
        CollectionRequest(
            queries=("Data Analyst",),
            states=("bayern",),
            location="Germany",
            max_pages=1,
            page_size=20,
        )
    )
    assert result.status is SourceRunStatus.COMPLETED
    assert len(result.jobs) == 3
    completeness = {
        item.job.source_job_id: item.description.completeness for item in result.jobs
    }
    assert completeness["listing_id:listing-100"] is DescriptionCompleteness.FULL
    assert completeness["listing_id:listing-200"] is DescriptionCompleteness.SNIPPET
    assert result.detail_requests_attempted == 3
    assert result.detail_requests_succeeded == 3
    assert result.detail_requests_failed == 0
    assert result.external_redirects_seen == 1


def test_failed_middle_page_keeps_jobs_and_continues(adapter_settings):
    client = FakeClient(
        state_pages={
            ("bayern", 1): STATE_PAGE,
            ("bayern", 2): EnglishJobsClientError("temporary", retriable=True),
            ("bayern", 3): "<html><body></body></html>",
        },
        documents={
            "https://englishjobs.de/jobs/internal-100": (
                DETAIL_FULL,
                "https://englishjobs.de/jobs/internal-100",
            )
        },
    )
    result = EnglishJobsAdapter(adapter_settings, client).collect(
        CollectionRequest(states=("bayern",), max_pages=3, page_size=20)
    )
    assert len(result.jobs) == 2
    assert result.search_requests_failed == 1
    assert result.status is SourceRunStatus.COMPLETED_WITH_ERRORS


def test_repeated_page_detection(adapter_settings):
    client = FakeClient(
        state_pages={("bayern", 1): STATE_PAGE, ("bayern", 2): STATE_PAGE},
        documents={
            "https://englishjobs.de/jobs/internal-100": (
                DETAIL_FULL,
                "https://englishjobs.de/jobs/internal-100",
            )
        },
    )
    result = EnglishJobsAdapter(adapter_settings, client).collect(
        CollectionRequest(states=("bayern",), max_pages=2, page_size=20)
    )
    assert result.repeated_pages == 1
    assert result.pages_requested == 2


def test_clickout_resolution_keeps_snippet_when_no_full_detail(adapter_settings):
    client = FakeClient(
        state_pages={("bayern", 1): STATE_PAGE},
        documents={
            "https://englishjobs.de/jobs/internal-100": (
                DETAIL_FULL,
                "https://englishjobs.de/jobs/internal-100",
            ),
            "https://englishjobs.de/clickout/track-300": (
                "",
                "https://company.example/jobs/operations-analyst",
            ),
        },
    )
    result = EnglishJobsAdapter(adapter_settings, client).collect(
        CollectionRequest(states=("bayern",), max_pages=1, page_size=20)
    )
    by_id = {item.job.source_job_id: item for item in result.jobs}
    assert by_id["listing_id:listing-300"].description.completeness is DescriptionCompleteness.SNIPPET
    assert by_id["listing_id:listing-300"].job.canonical_url == (
        "https://company.example/jobs/operations-analyst"
    )
    assert result.external_redirects_seen == 1


def test_apply_only_detail_page_is_not_marked_full(adapter_settings):
    client = FakeClient(
        query_pages={("Data Analyst", "Germany", 1): QUERY_PAGE},
        documents={
            "https://englishjobs.de/jobs/internal-100": (
                DETAIL_FULL,
                "https://englishjobs.de/jobs/internal-100",
            ),
            "https://englishjobs.de/jobs/internal-200": (
                DETAIL_APPLY_ONLY,
                "https://englishjobs.de/jobs/internal-200",
            ),
        },
    )
    result = EnglishJobsAdapter(adapter_settings, client).collect(
        CollectionRequest(
            queries=("Data Analyst",),
            location="Germany",
            max_pages=1,
            page_size=20,
        )
    )

    by_id = {item.job.source_job_id: item for item in result.jobs}
    assert by_id["listing_id:listing-100"].description.completeness is DescriptionCompleteness.FULL
    assert by_id["listing_id:listing-200"].description.completeness is DescriptionCompleteness.SNIPPET
    assert "Snippet two" in (by_id["listing_id:listing-200"].description.raw_text or "")


def test_detail_failure_keeps_collection_and_falls_back_to_snippet(adapter_settings):
    client = FakeClient(
        query_pages={("Data Analyst", "Germany", 1): QUERY_PAGE},
        documents={
            "https://englishjobs.de/jobs/internal-100": EnglishJobsClientError(
                "detail timeout",
                retriable=True,
            ),
            "https://englishjobs.de/jobs/internal-200": (
                DETAIL_SHORT,
                "https://englishjobs.de/jobs/internal-200",
            ),
        },
    )
    result = EnglishJobsAdapter(adapter_settings, client).collect(
        CollectionRequest(
            queries=("Data Analyst",),
            location="Germany",
            max_pages=1,
            page_size=20,
        )
    )

    by_id = {item.job.source_job_id: item for item in result.jobs}
    assert result.status is SourceRunStatus.COMPLETED_WITH_ERRORS
    assert result.detail_requests_attempted == 2
    assert result.detail_requests_failed == 1
    assert by_id["listing_id:listing-100"].description.completeness is DescriptionCompleteness.SNIPPET
    assert by_id["listing_id:listing-200"].description.completeness is DescriptionCompleteness.SNIPPET


def test_max_detail_requests_bounds_detail_fetching(adapter_settings):
    client = FakeClient(
        query_pages={("Data Analyst", "Germany", 1): QUERY_PAGE},
        documents={
            "https://englishjobs.de/jobs/internal-100": (
                DETAIL_FULL,
                "https://englishjobs.de/jobs/internal-100",
            ),
            "https://englishjobs.de/jobs/internal-200": (
                DETAIL_FULL,
                "https://englishjobs.de/jobs/internal-200",
            ),
        },
    )
    result = EnglishJobsAdapter(adapter_settings, client).collect(
        CollectionRequest(
            queries=("Data Analyst",),
            location="Germany",
            max_pages=1,
            page_size=20,
            max_detail_requests=1,
        )
    )

    by_id = {item.job.source_job_id: item for item in result.jobs}
    assert result.detail_requests_attempted == 1
    assert client.detail_calls == [
        ("detail", "https://englishjobs.de/jobs/internal-100")
    ]
    assert by_id["listing_id:listing-100"].description.completeness is DescriptionCompleteness.FULL
    assert by_id["listing_id:listing-200"].description.completeness is DescriptionCompleteness.SNIPPET


def test_total_count_can_drive_second_page_without_next_link(adapter_settings):
    first_page = """
    <html><body>
    <h1>25 data analyst English-speaking jobs in Germany</h1>
    <div class="job js-job" data-job-id="listing-100">
      <a class="js-joblink" href="/jobs/internal-100">Data Analyst</a>
      <span>Insight GmbH</span><span>Munich, Bayern</span><span>June 12</span>
      <p>Snippet one.</p>
    </div>
    </body></html>
    """
    second_page = """
    <html><body>
    <div class="job js-job" data-job-id="listing-200">
      <a class="js-joblink" href="/jobs/internal-200">Senior Data Analyst</a>
      <span>Northwind GmbH</span><span>Berlin</span><span>June 11</span>
      <p>Snippet two.</p>
    </div>
    </body></html>
    """
    client = FakeClient(
        query_pages={
            ("Data Analyst", "Germany", 1): first_page,
            ("Data Analyst", "Germany", 2): second_page,
        },
        documents={
            "https://englishjobs.de/jobs/internal-100": (
                DETAIL_FULL,
                "https://englishjobs.de/jobs/internal-100",
            ),
            "https://englishjobs.de/jobs/internal-200": (
                DETAIL_SHORT,
                "https://englishjobs.de/jobs/internal-200",
            ),
        },
    )
    result = EnglishJobsAdapter(adapter_settings, client).collect(
        CollectionRequest(
            queries=("Data Analyst",),
            location="Germany",
            max_pages=2,
            page_size=20,
        )
    )
    assert len(result.jobs) == 2
    assert result.pages_requested == 2
