from __future__ import annotations

import os

import pytest

from app.config import get_settings
from app.sources.arbeitsagentur.adapter import ArbeitsagenturAdapter
from app.sources.arbeitsagentur.client import ArbeitsagenturClient
from app.sources.base import CollectionRequest


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("RUN_ARBEITSAGENTUR_LIVE_TEST") != "1",
    reason="Live Arbeitsagentur smoke test requires explicit opt-in",
)
def test_live_arbeitsagentur_one_page_smoke():
    settings = get_settings()
    adapter = ArbeitsagenturAdapter(settings, ArbeitsagenturClient(settings))
    result = adapter.collect(
        CollectionRequest(
            queries=("Data Analyst",),
            location="Deutschland",
            published_within_days=1,
            max_pages=1,
            page_size=1,
        )
    )
    assert result.search_requests_succeeded + result.search_requests_failed == 1

