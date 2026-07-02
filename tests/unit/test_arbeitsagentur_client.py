from __future__ import annotations

import logging

import pytest
import requests

from app.config import settings_from_mapping
from app.sources.arbeitsagentur.client import (
    ArbeitsagenturClient,
    ArbeitsagenturClientError,
    RetryExhaustedError,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = {} if payload is None else payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


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
            "ARBEITSAGENTUR_MAX_RETRIES": "2",
            "ARBEITSAGENTUR_BACKOFF_SECONDS": "0.25",
            "ARBEITSAGENTUR_CONNECT_TIMEOUT_SECONDS": "3",
            "ARBEITSAGENTUR_READ_TIMEOUT_SECONDS": "9",
            "ARBEITSAGENTUR_API_KEY": "public-test-key",
        },
        root=tmp_path,
    )


def test_successful_search_response_and_request_shape(client_settings):
    session = FakeSession([FakeResponse(payload={"ergebnisliste": []})])
    client = ArbeitsagenturClient(client_settings, session=session, sleeper=lambda _: None)
    payload = client.search(
        "Data Analyst",
        location="Deutschland",
        page=1,
        page_size=25,
        published_within_days=7,
    )
    assert payload == {"ergebnisliste": []}
    _, kwargs = session.calls[0]
    assert kwargs["params"]["page"] == 1
    assert kwargs["params"]["size"] == 25
    assert kwargs["timeout"] == (3.0, 9.0)


def test_successful_detail_response(client_settings):
    session = FakeSession([FakeResponse(payload={"referenznummer": "REF/1"})])
    client = ArbeitsagenturClient(client_settings, session=session, sleeper=lambda _: None)
    assert client.fetch_details("REF/1")["referenznummer"] == "REF/1"
    assert "REF/1" not in session.calls[0][0]


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
def test_timeout_and_connection_errors_retry(client_settings, error):
    sleeps = []
    session = FakeSession([error, FakeResponse(payload={"ok": True})])
    client = ArbeitsagenturClient(client_settings, session=session, sleeper=sleeps.append)
    assert client.fetch_details("REF-1") == {"ok": True}
    assert len(session.calls) == 2
    assert sleeps == [0.25]


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_retriable_status_uses_exponential_backoff(client_settings, status):
    sleeps = []
    session = FakeSession(
        [FakeResponse(status), FakeResponse(status), FakeResponse(payload={"ok": True})]
    )
    client = ArbeitsagenturClient(client_settings, session=session, sleeper=sleeps.append)
    assert client.fetch_details("REF-1") == {"ok": True}
    assert sleeps == [0.25, 0.5]


@pytest.mark.parametrize("status", [400, 404])
def test_permanent_client_errors_are_not_retried(client_settings, status):
    session = FakeSession([FakeResponse(status)])
    client = ArbeitsagenturClient(client_settings, session=session, sleeper=lambda _: None)
    with pytest.raises(ArbeitsagenturClientError) as raised:
        client.fetch_details("REF-1")
    assert raised.value.status_code == status
    assert raised.value.retriable is False
    assert len(session.calls) == 1


def test_retry_exhaustion(client_settings):
    session = FakeSession([FakeResponse(503), FakeResponse(503), FakeResponse(503)])
    client = ArbeitsagenturClient(client_settings, session=session, sleeper=lambda _: None)
    with pytest.raises(RetryExhaustedError) as raised:
        client.fetch_details("REF-1")
    assert raised.value.retriable is True
    assert len(session.calls) == 3


def test_api_key_and_headers_are_not_logged_or_exposed(client_settings, caplog):
    session = FakeSession([FakeResponse(503), FakeResponse(payload={"ok": True})])
    caplog.set_level(logging.INFO)
    client = ArbeitsagenturClient(client_settings, session=session, sleeper=lambda _: None)
    client.fetch_details("REF-1")
    assert session.headers["X-API-Key"] == "public-test-key"
    assert "public-test-key" not in caplog.text
    assert client_settings.redacted_dict()["arbeitsagentur_api_key"] == "***REDACTED***"

