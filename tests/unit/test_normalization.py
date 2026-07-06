from __future__ import annotations

import json

import pytest

from app.services.normalization import (
    CompanyAliases,
    normalize_description,
    normalize_location,
    normalize_text,
    normalize_title,
    normalize_url,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Senior\u00a0Data—Analyst  ", "senior data analyst"),
        ("Müller & Söhne", "mueller soehne"),
        (None, None),
    ],
)
def test_text_normalization_matrix(raw, expected) -> None:
    assert normalize_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Data Analyst (m/w/d)", "data analyst"),
        ("Senior Data Analyst", "senior data analyst"),
        ("Head of Risk", "head of risk"),
    ],
)
def test_title_normalization_preserves_role_and_seniority(raw, expected) -> None:
    assert normalize_title(raw) == expected


def test_company_aliases_are_configurable_and_legal_suffixes_are_removed(tmp_path) -> None:
    path = tmp_path / "aliases.json"
    path.write_text(
        json.dumps({"International Business Machines": "IBM"}), encoding="utf-8"
    )
    aliases = CompanyAliases.from_json(path)

    assert aliases.canonical("International Business Machines GmbH") == "ibm"
    assert aliases.canonical("Example Bank AG") == "example bank"


def test_location_normalizes_aliases_regions_country_and_remote_mode() -> None:
    location = normalize_location(
        "Munich", "Bavaria", "Deutschland", raw="Munich / Home Office"
    )

    assert location.city == "muenchen"
    assert location.region == "bayern"
    assert location.country == "germany"
    assert location.remote_mode == "remote"


def test_description_normalization_strips_markup_and_unsafe_content() -> None:
    raw = "<p>Build&nbsp;reports</p><script>secret()</script><b>with SQL</b>"
    assert normalize_description(raw) == "build reports with sql"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "HTTPS://Jobs.Example.com//vacancy/42/?utm_source=x&b=2&a=1#details",
            "https://jobs.example.com/vacancy/42?a=1&b=2",
        ),
        ("https://jobs.example.com/42?gclid=abc", "https://jobs.example.com/42"),
        ("not-a-url", None),
        (None, None),
    ],
)
def test_url_normalization_matrix(raw, expected) -> None:
    assert normalize_url(raw) == expected
