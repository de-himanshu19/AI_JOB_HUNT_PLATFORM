from __future__ import annotations

import requests

from app.config import settings_from_mapping
from app.integrations.ai.base import (
    AIMalformedResponseError,
    AIRateLimitError,
    AISafetyNotEnabledError,
)
from app.integrations.ai.openai_compatible import OpenAICompatibleProvider


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, *, invalid_json=False):
        self.status_code = status_code
        self._payload = payload
        self._invalid_json = invalid_json

    def json(self):
        if self._invalid_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, json, headers, timeout):
        self.calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _settings(**overrides):
    values = {
        "AI_ENABLED": "true",
        "AI_PROVIDER": "openai_compatible",
        "AI_API_KEY": "secret-key",
        "AI_BASE_URL": "https://provider.invalid/v1",
        "AI_MODEL": "safe-model",
        "AI_TIMEOUT_SECONDS": "12",
        "AI_MAX_RETRIES": "1",
        **overrides,
    }
    return settings_from_mapping(values)


def test_openai_compatible_provider_returns_mocked_polished_text() -> None:
    session = FakeSession([
        FakeResponse(payload={"choices": [{"message": {"content": "Polished CV"}}]})
    ])

    text = OpenAICompatibleProvider(_settings(), session=session).polish("Prompt")

    assert text == "Polished CV\n"
    assert session.calls[0]["url"] == "https://provider.invalid/v1/chat/completions"
    assert session.calls[0]["headers"]["Authorization"] == "Bearer secret-key"
    assert session.calls[0]["json"]["model"] == "safe-model"
    assert session.calls[0]["timeout"] == 12


def test_openai_compatible_provider_configuration_is_checked_without_network() -> None:
    session = FakeSession([])

    try:
        OpenAICompatibleProvider(
            _settings(AI_ENABLED="false", AI_API_KEY=""), session=session
        ).polish("Prompt")
    except AISafetyNotEnabledError as error:
        assert "AI_ENABLED" in str(error)
    else:
        raise AssertionError("Missing configuration did not fail safely")

    assert session.calls == []


def test_openai_compatible_provider_maps_rate_limit_timeout_and_malformed() -> None:
    rate_limited = FakeSession([FakeResponse(status_code=429), FakeResponse(status_code=429)])
    try:
        OpenAICompatibleProvider(_settings(), session=rate_limited).polish("Prompt")
    except AIRateLimitError:
        pass
    else:
        raise AssertionError("Rate limit was not mapped")
    assert len(rate_limited.calls) == 2

    timeout = FakeSession([requests.Timeout("slow")])
    try:
        OpenAICompatibleProvider(_settings(), session=timeout).polish("Prompt")
    except requests.Timeout:
        pass
    else:
        raise AssertionError("Timeout did not propagate for service mapping")

    malformed = FakeSession([FakeResponse(payload={"choices": []})])
    try:
        OpenAICompatibleProvider(_settings(), session=malformed).polish("Prompt")
    except AIMalformedResponseError:
        pass
    else:
        raise AssertionError("Malformed response was not mapped")
