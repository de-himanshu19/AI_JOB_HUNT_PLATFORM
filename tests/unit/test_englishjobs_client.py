from __future__ import annotations

import logging

import pytest
import requests

from app.config import settings_from_mapping
from app.sources.englishjobs.client import (
    EnglishJobsClient,
    EnglishJobsClientError,
    RetryExhaustedError,
)


class FakeResponse:
    def __init__(self, status_code=200, text="<html></html>", url="https://englishjobs.de"):
        self.status_code = status_code
        self.text = text
        self.url = url


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def client_settings(tmp_path):
    return settings_from_mapping(
        {
            "ENGLISHJOBS_MAX_RETRIES": "2",
            "ENGLISHJOBS_BACKOFF_SECONDS": "0.25",
            "ENGLISHJOBS_REQUEST_DELAY_SECONDS": "0.5",
            "ENGLISHJOBS_CONNECT_TIMEOUT_SECONDS": "3",
            "ENGLISHJOBS_READ_TIMEOUT_SECONDS": "9",
        },
        root=tmp_path,
    )


def test_successful_state_request(client_settings):
    session = FakeSession([FakeResponse(text="<html>ok</html>")])
    client = EnglishJobsClient(client_settings, session=session, sleeper=lambda _: None)
    result = client.search_state("bayern", page=1)
    assert "ok" in result.text
    _, kwargs = session.calls[0]
    assert kwargs["timeout"] == (3.0, 9.0)


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
def test_timeout_and_connection_errors_retry(client_settings, error):
    sleeps = []
    session = FakeSession([error, FakeResponse()])
    client = EnglishJobsClient(client_settings, session=session, sleeper=sleeps.append)
    client.search_query("Data Analyst", location="Germany", page=1)
    assert len(session.calls) == 2
    assert sleeps == [0.25]


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_retriable_status_backoff(client_settings, status):
    sleeps = []
    session = FakeSession([FakeResponse(status_code=status), FakeResponse()])
    client = EnglishJobsClient(client_settings, session=session, sleeper=sleeps.append)
    client.fetch_document("https://englishjobs.de/jobs/internal-100", operation="detail")
    assert sleeps == [0.25]


@pytest.mark.parametrize("status", [400, 404])
def test_permanent_client_errors_are_not_retried(client_settings, status):
    session = FakeSession([FakeResponse(status_code=status)])
    client = EnglishJobsClient(client_settings, session=session, sleeper=lambda _: None)
    with pytest.raises(EnglishJobsClientError) as raised:
        client.search_state("bayern", page=1)
    assert raised.value.status_code == status
    assert len(session.calls) == 1


def test_retry_exhaustion(client_settings):
    session = FakeSession([FakeResponse(status_code=503)] * 3)
    client = EnglishJobsClient(client_settings, session=session, sleeper=lambda _: None)
    with pytest.raises(RetryExhaustedError):
        client.search_state("bayern", page=1)


def test_request_delay_and_safe_logging(client_settings, caplog):
    sleeps = []
    session = FakeSession([FakeResponse(), FakeResponse()])
    caplog.set_level(logging.INFO)
    client = EnglishJobsClient(client_settings, session=session, sleeper=sleeps.append)
    client.search_state("bayern", page=1)
    client.search_state("bayern", page=2)
    assert sleeps == [0.5]
    assert "Mozilla" not in caplog.text
