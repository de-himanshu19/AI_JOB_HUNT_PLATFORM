"""Explicitly opt-in OpenAI-compatible CV polish provider."""

from __future__ import annotations

from typing import Any

import requests

from app.config import Settings
from app.integrations.ai.base import (
    AIConfigurationError,
    AIMalformedResponseError,
    AIProviderError,
    AIRateLimitError,
    AISafetyNotEnabledError,
)


class OpenAICompatibleProvider:
    """Small chat-completions client with secret-safe failures."""

    name = "openai_compatible"

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.model = settings.ai_model
        self._enabled = settings.ai_enabled
        self._provider = settings.ai_provider
        self._api_key = settings.ai_api_key
        self._base_url = settings.ai_base_url.strip().rstrip("/")
        self._timeout = settings.ai_timeout_seconds
        self._max_retries = settings.ai_max_retries
        self._session = session or requests.Session()

    def polish(self, prompt: str) -> str:
        self._validate_configuration()
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You polish CV wording only. Preserve every fact exactly, "
                        "do not add claims, and return FlowCV-friendly plain text."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        last_status: int | None = None
        for attempt in range(self._max_retries + 1):
            response = self._session.post(
                self._endpoint(),
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
            last_status = response.status_code
            if response.status_code == 429:
                if attempt < self._max_retries:
                    continue
                raise AIRateLimitError("AI provider rate limit")
            if 500 <= response.status_code < 600 and attempt < self._max_retries:
                continue
            if response.status_code >= 400:
                raise AIProviderError(f"AI provider HTTP {response.status_code}")
            return self._extract_text(response)
        raise AIProviderError(f"AI provider HTTP {last_status or 'unknown'}")

    def _validate_configuration(self) -> None:
        if not self._enabled:
            raise AISafetyNotEnabledError("AI_ENABLED must be true for live AI polish")
        if self._provider != self.name:
            raise AIConfigurationError("AI_PROVIDER must be openai_compatible")
        if self._api_key is None:
            raise AIConfigurationError("AI_API_KEY is required for live AI polish")
        if not self._base_url:
            raise AIConfigurationError("AI_BASE_URL is required for live AI polish")
        if not self.model.strip():
            raise AIConfigurationError("AI_MODEL is required for live AI polish")

    def _endpoint(self) -> str:
        if self._base_url.endswith("/chat/completions"):
            return self._base_url
        return f"{self._base_url}/chat/completions"

    @staticmethod
    def _extract_text(response: requests.Response) -> str:
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as error:
            raise AIMalformedResponseError("AI provider returned invalid JSON") from error
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise AIMalformedResponseError(
                "AI provider returned incomplete response content"
            ) from error
        if not isinstance(text, str) or not text.strip():
            raise AIMalformedResponseError(
                "AI provider returned incomplete response content"
            )
        return text.strip() + "\n"
