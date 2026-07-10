from __future__ import annotations

from types import SimpleNamespace

from app.dashboard.presentation import (
    date_range_start,
    default_follow_up_date,
    fit_score_label,
    job_row,
    match_type_label,
    parse_city,
    posted_or_first_seen_display,
)


def test_city_parser_returns_readable_city_from_portal_locations() -> None:
    assert parse_city("34117 Kassel, Hessen, HESSEN, DEUTSCHLAND") == "Kassel"
    assert parse_city("10785 Berlin, BERLIN, DEUTSCHLAND") == "Berlin"
    assert parse_city("80809 München, BAYERN, DEUTSCHLAND") == "München"
    assert parse_city("Remote") == "Remote"


def test_match_type_and_score_labels_are_user_facing() -> None:
    assert match_type_label("authoritative") == "Full analysis"
    assert match_type_label("prefilter_only") == "Quick match only"
    assert match_type_label(None) == "Not analyzed"
    assert fit_score_label("authoritative", 82.25) == "82.25"
    assert fit_score_label("prefilter_only", None) == "Quick match only"
    assert fit_score_label(None, None) == "Quick match only"


def test_posted_first_seen_and_date_range_helpers() -> None:
    assert (
        posted_or_first_seen_display(
            "2026-07-10T08:00:00+00:00",
            "2026-07-09T08:00:00+00:00",
        )
        == "2026-07-10 (Posted)"
    )
    assert (
        posted_or_first_seen_display(None, "2026-07-09T08:00:00+00:00")
        == "2026-07-09 (First seen)"
    )
    assert default_follow_up_date().isoformat() > "2026-01-01"
    assert date_range_start("Last 3 days").count("-") == 2
    assert date_range_start("All") is None


def test_job_row_projection_hides_technical_ids() -> None:
    row = job_row(SimpleNamespace(
        job_id="technical-id",
        title="Data Analyst",
        company="Example GmbH",
        location="10785 Berlin, BERLIN, DEUTSCHLAND",
        source="arbeitsagentur",
        authority="prefilter_only",
        rank_score=77.0,
        fit_score=None,
        application_statuses=("shortlisted",),
        published_at=None,
        first_seen_at="2026-07-10T08:00:00+00:00",
        created_at=None,
    ))

    assert "job_id" not in row
    assert row["City"] == "Berlin"
    assert row["Match Type"] == "Quick match only"
    assert row["Fit Score"] == "Quick match only"
