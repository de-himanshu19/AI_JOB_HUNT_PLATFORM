from pathlib import Path

from app.sources.englishjobs.parser import (
    extract_total_jobs_count,
    is_full_description_text,
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
    assert detail.structured_data["detail_description_quality"] == "full"
    assert detail.structured_data["detail_keyword_hits"] >= 2


def test_detail_page_with_metadata_only_is_not_full():
    detail = parse_job_detail(
        """
        <html><body><main>
          <h1>Data Analyst</h1>
          <div class="company">Example GmbH</div>
          <div class="location">Berlin</div>
          <p>Apply now to continue to the company career page.</p>
        </main></body></html>
        """,
        source_url="https://englishjobs.de/jobs/internal-apply",
        final_url="https://englishjobs.de/jobs/internal-apply",
    )

    assert detail.description is None
    assert detail.structured_data["detail_description_quality"] == "not_full"


def test_full_description_heuristic_rejects_short_snippets_and_repeated_boilerplate():
    assert not is_full_description_text(
        "Responsibilities include SQL reporting.",
        title="Data Analyst",
        company="Example GmbH",
        location="Berlin",
    )
    repeated = "Responsibilities requirements benefits role tasks. " * 80
    assert not is_full_description_text(
        repeated,
        title="Data Analyst",
        company="Example GmbH",
        location="Berlin",
    )


def test_missing_next_link_keeps_pagination_state_unknown():
    page = parse_search_page(
        _html("query_data_analyst_location_germany_page_1.html"),
        base_url="https://englishjobs.de",
        page_number=1,
        search_query="Data Analyst",
        search_location="Germany",
    )
    assert page.has_next_page is None
