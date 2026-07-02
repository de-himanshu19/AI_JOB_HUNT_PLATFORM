from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.sources.arbeitsagentur.parser import (
    SourcePayloadError,
    extract_language_signals,
    parse_job_details,
    parse_search_page,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "arbeitsagentur"


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_normal_search_response_preserves_fields_and_unicode():
    page = parse_search_page(
        _fixture("search_page_1.json"),
        search_term="Data Analyst",
        detail_base_url="https://detail.invalid",
    )
    assert len(page.jobs) == 2
    first, second = page.jobs
    assert first.source_job_id == "REF-100"
    assert first.company == "Beispiel Daten GmbH"
    assert first.city == "Berlin"
    assert first.publication_date.isoformat() == "2026-06-30"
    assert second.city == "München"
    assert first.search_terms == ("Data Analyst",)


@pytest.mark.parametrize(
    ("field", "attribute"),
    [
        ("firma", "company"),
        ("stellenlokationen", "city"),
        ("datumErsteVeroeffentlichung", "publication_date"),
    ],
)
def test_missing_optional_search_fields_are_tolerated(field, attribute):
    payload = _fixture("search_page_1.json")
    payload["ergebnisliste"] = [copy.deepcopy(payload["ergebnisliste"][0])]
    payload["ergebnisliste"][0].pop(field)
    page = parse_search_page(
        payload, search_term="Analyst", detail_base_url="https://detail.invalid"
    )
    assert getattr(page.jobs[0], attribute) is None


def test_missing_source_reference_is_reported_and_rejected():
    payload = _fixture("search_page_1.json")
    payload["ergebnisliste"] = [copy.deepcopy(payload["ergebnisliste"][0])]
    payload["ergebnisliste"][0].pop("referenznummer")
    page = parse_search_page(
        payload, search_term="Analyst", detail_base_url="https://detail.invalid"
    )
    assert page.jobs == []
    assert "missing referenznummer" in page.record_errors[0]


def test_empty_result_page():
    page = parse_search_page(
        _fixture("search_empty.json"),
        search_term="Analyst",
        detail_base_url="https://detail.invalid",
    )
    assert page.jobs == []
    assert page.total_results == 0


@pytest.mark.parametrize("payload", [[], {}, {"ergebnisliste": {}}])
def test_malformed_search_structure(payload):
    with pytest.raises(SourcePayloadError):
        parse_search_page(
            payload, search_term="Analyst", detail_base_url="https://detail.invalid"
        )


def test_full_detail_sections_urls_employment_and_language_signals():
    detail = parse_job_details(
        _fixture("detail_full.json"),
        source_job_id="REF-100",
        source_url="https://detail.invalid/ref",
    )
    assert "Job Description" in detail.description
    assert "Responsibilities" in detail.description
    assert "Requirements" in detail.description
    assert len(detail.responsibilities) == 2
    assert detail.original_application_url.endswith("/apply")
    assert detail.employment_type == "Vollzeit"
    assert detail.contract_type == "Unbefristet"
    assert detail.working_time == ("Vollzeit", "Hybrid")
    assert detail.start_date.isoformat() == "2026-08-01"
    assert detail.application_deadline.isoformat() == "2026-07-31"
    assert detail.language_signals.german_level == "C1"
    assert detail.language_signals.german_requirement == "German C1"
    assert detail.language_signals.english_signal is True


def test_customer_facing_signal_does_not_exclude_or_fail_parsing():
    signals = extract_language_signals(
        "Direkter Kundenkontakt und Kundenberatung. Fluent English is useful."
    )
    assert signals.customer_facing_german_risk is True
    assert signals.english_signal is True


def test_missing_optional_detail_sections():
    detail = parse_job_details(
        _fixture("detail_minimal.json"),
        source_job_id="REF-200",
        source_url="https://detail.invalid/ref",
    )
    assert detail.description is None
    assert detail.requirements == ()
    assert detail.employment_type == "Teilzeit oder Vollzeit"


def test_empty_detail_response_is_valid_missing_detail():
    detail = parse_job_details(
        {}, source_job_id="REF-EMPTY", source_url="https://detail.invalid/ref"
    )
    assert detail.description is None
    assert detail.source_job_id == "REF-EMPTY"


def test_malformed_detail_structure():
    with pytest.raises(SourcePayloadError):
        parse_job_details(
            [], source_job_id="REF-BAD", source_url="https://detail.invalid/ref"
        )

