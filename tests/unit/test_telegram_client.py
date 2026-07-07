import logging

import pytest
import requests

from app.config import settings_from_mapping
from app.integrations.telegram import TelegramClient


class Response:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class InvalidJsonResponse(Response):
    def json(self):
        raise ValueError("private malformed response")


class Session:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _settings(tmp_path, **updates):
    values = {
        "TELEGRAM_ENABLED": "true",
        "TELEGRAM_BOT_TOKEN": "super-secret-token",
        "TELEGRAM_CHAT_ID": "secret-chat-id",
        "TELEGRAM_BACKOFF_SECONDS": "0",
    }
    values.update(updates)
    return settings_from_mapping(values, root=tmp_path)


def test_success_returns_remote_message_id(tmp_path) -> None:
    session = Session([Response(200, {"ok": True, "result": {"message_id": 42}})])
    result = TelegramClient(_settings(tmp_path), session=session).send_message("hello")
    assert result.success
    assert result.remote_message_id == "42"
    assert len(session.calls) == 1


def test_429_and_5xx_are_retried_with_bounded_backoff(tmp_path) -> None:
    session = Session([
        Response(429, headers={"Retry-After": "0"}),
        Response(503),
        Response(200, {"ok": True, "result": {"message_id": 7}}),
    ])
    sleeps = []
    result = TelegramClient(
        _settings(tmp_path), session=session, sleeper=sleeps.append
    ).send_message("hello")
    assert result.success and result.attempts == 3
    assert sleeps == [0.0, 0.0]


def test_permanent_4xx_is_not_retried(tmp_path) -> None:
    session = Session([Response(400, {"ok": False, "description": "private"})])
    result = TelegramClient(_settings(tmp_path), session=session).send_message("hello")
    assert not result.success
    assert result.error_summary == "http_status:400"
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (InvalidJsonResponse(200), "response:invalid_json"),
        (Response(200, ["unexpected"]), "response:invalid_shape"),
    ],
)
def test_malformed_success_responses_fail_safely(tmp_path, response, expected) -> None:
    result = TelegramClient(
        _settings(tmp_path), session=Session([response])
    ).send_message("hello")
    assert not result.success
    assert result.error_summary == expected


def test_transport_failure_is_safe_and_secrets_are_not_logged(
    tmp_path, caplog,
) -> None:
    session = Session([requests.Timeout("contains-private-body")] * 4)
    caplog.set_level(logging.WARNING)
    result = TelegramClient(_settings(tmp_path), session=session, sleeper=lambda _: None).send_message("private message")
    logged = caplog.text
    assert not result.success
    assert result.error_summary == "transport:Timeout"
    assert "super-secret-token" not in logged
    assert "secret-chat-id" not in logged
    assert "private message" not in logged
    assert "contains-private-body" not in logged


def test_disabled_client_cannot_be_constructed(tmp_path) -> None:
    with pytest.raises(ValueError, match="TELEGRAM_ENABLED"):
        TelegramClient(settings_from_mapping({}, root=tmp_path))


def test_unexpected_request_exception_is_safely_summarized(tmp_path) -> None:
    result = TelegramClient(
        _settings(tmp_path),
        session=Session([requests.RequestException("private transport detail")]),
    ).send_message("private message")
    assert not result.success
    assert result.error_summary == "transport:RequestException"
