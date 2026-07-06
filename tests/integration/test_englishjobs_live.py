from __future__ import annotations

import os

import pytest

from app import get_settings
from app.sources.base import CollectionRequest
from app.sources.englishjobs.adapter import EnglishJobsAdapter
from app.sources.englishjobs.client import EnglishJobsClient


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_ENGLISHJOBS_LIVE_TEST") != "1",
    reason="Live EnglishJobs smoke test requires explicit opt-in",
)


@pytest.mark.live
def test_live_englishjobs_smoke():
    settings = get_settings()
    adapter = EnglishJobsAdapter(settings, EnglishJobsClient(settings))
    result = adapter.collect(
        CollectionRequest(states=("bayern",), max_pages=1, page_size=10)
    )
    assert result.status.value in {"completed", "completed_with_errors"}
