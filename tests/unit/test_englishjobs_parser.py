from pathlib import Path

from app.sources.englishjobs.parser import (
    extract_total_jobs_count,
    parse_job_detail,
    parse_search_page,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "englishjobs"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_state_page_and_total_count():
    page = parse_search_page(
        _html("state_bayern_page_1.html"),
        base_url="https://englishjobs.de",
        page_number=1,
        search_state="bayern",
        state_display="Bayern",
    )
    assert extract_total_jobs_count(_html("state_bayern_page_1.html")) == 3
    assert len(page.records) == 2
    assert page.records[0].title == "Data Analyst"
    assert page.records[0].company == "Insight GmbH"
    assert page.records[0].city == "Munich"
    assert page.records[0].clickout_url == "https://englishjobs.de/clickout/track-100"


def test_parse_query_page_unicode_and_missing_fields():
    page = parse_search_page(
        _html("query_data_analyst_location_germany_page_1.html"),
        base_url="https://englishjobs.de",
        page_number=1,
        search_query="Data Analyst",
        search_location="Germany",
    )
    assert len(page.records) == 2
    assert page.records[1].location_raw == "Berlin"
    assert page.invalid_cards == 0


def test_selector_failure_is_visible():
    page = parse_search_page(
        "<html><body><h1>5 jobs in Bayern</h1></body></html>",
        base_url="https://englishjobs.de",
        page_number=1,
        search_state="bayern",
        state_display="Bayern",
    )
    assert page.records == []
    assert page.record_errors == ["No job cards matched the expected selectors"]


def test_parse_full_job_detail():
    detail = parse_job_detail(
        _html("detail_jobs_internal-100.html"),
        source_url="https://englishjobs.de/jobs/internal-100",
        final_url="https://englishjobs.de/jobs/internal-100",
    )
    assert "Full EnglishJobs description" in detail.description
    assert detail.canonical_url == "https://englishjobs.de/jobs/internal-100"


def test_missing_next_link_keeps_pagination_state_unknown():
    page = parse_search_page(
        _html("query_data_analyst_location_germany_page_1.html"),
        base_url="https://englishjobs.de",
        page_number=1,
        search_query="Data Analyst",
        search_location="Germany",
    )
    assert page.has_next_page is None
