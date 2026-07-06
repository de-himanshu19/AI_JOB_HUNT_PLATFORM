from app.sources.englishjobs.url_builder import (
    build_keyword_url,
    build_state_url,
    normalize_identity_url,
)


def test_build_state_url():
    assert build_state_url("https://englishjobs.de", "bayern") == (
        "https://englishjobs.de/in/bayern"
    )
    assert build_state_url("https://englishjobs.de", "bayern", page=2) == (
        "https://englishjobs.de/in/bayern?page=2"
    )


def test_build_keyword_url():
    assert build_keyword_url("https://englishjobs.de", "Data Analyst") == (
        "https://englishjobs.de/jobs/data_analyst"
    )
    assert build_keyword_url(
        "https://englishjobs.de",
        "Data Analyst",
        "Germany",
        page=2,
    ) == "https://englishjobs.de/in/germany/data_analyst?page=2"


def test_build_keyword_url_with_unicode_location():
    assert build_keyword_url(
        "https://englishjobs.de",
        "Data Analyst",
        "Baden Württemberg",
    ) == "https://englishjobs.de/in/baden-w%C3%BCrttemberg/data_analyst"


def test_normalize_identity_url_removes_tracking():
    assert normalize_identity_url(
        "https://englishjobs.de/clickout/abc?sig=123&utm_source=test&keep=1"
    ) == "https://englishjobs.de/clickout/abc?keep=1"
