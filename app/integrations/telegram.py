"""Injected Telegram Bot API client with bounded retries and safe errors."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

import requests

from app.config import Settings


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramSendResult:
    success: bool
    remote_message_id: str | None = None
    error_summary: str | None = None
    attempts: int = 1


class TelegramClient:
    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if not settings.telegram_enabled:
            raise ValueError("Telegram delivery requires TELEGRAM_ENABLED=true")
        self.settings = settings
        self.session = session or requests.Session()
        self.sleeper = sleeper

    def send_message(self, text: str) -> TelegramSendResult:
        token = self.settings.telegram_bot_token
        chat_id = self.settings.telegram_chat_id
        if token is None or chat_id is None:
            raise ValueError("Telegram credentials are required for live delivery")
        url = (
            self.settings.telegram_api_base_url.rstrip("/")
            + f"/bot{token.get_secret_value()}/sendMessage"
        )
        attempts = self.settings.telegram_max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.post(
                    url,
                    data={
                        "chat_id": chat_id.get_secret_value(),
                        "text": text,
                        "disable_web_page_preview": True,
                    },
                    timeout=(
                        self.settings.telegram_connect_timeout_seconds,
                        self.settings.telegram_read_timeout_seconds,
                    ),
                )
            except (requests.Timeout, requests.ConnectionError) as error:
                if attempt < attempts:
                    self._backoff(attempt)
                    continue
                return TelegramSendResult(
                    False,
                    error_summary=f"transport:{type(error).__name__}",
                    attempts=attempt,
                )
            except requests.RequestException as error:
                return TelegramSendResult(
                    False,
                    error_summary=f"transport:{type(error).__name__}",
                    attempts=attempt,
                )

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    return TelegramSendResult(
                        False, error_summary="response:invalid_json", attempts=attempt
                    )
                if not isinstance(payload, dict):
                    return TelegramSendResult(
                        False, error_summary="response:invalid_shape", attempts=attempt
                    )
                if payload.get("ok") is True:
                    message_id = payload.get("result", {}).get("message_id")
                    return TelegramSendResult(
                        True,
                        remote_message_id=(str(message_id) if message_id is not None else None),
                        attempts=attempt,
                    )
                return TelegramSendResult(
                    False,
                    error_summary=f"telegram:error_code_{payload.get('error_code', 'unknown')}",
                    attempts=attempt,
                )

            retriable = response.status_code == 429 or response.status_code >= 500
            if retriable and attempt < attempts:
                retry_after = response.headers.get("Retry-After")
                self._backoff(attempt, retry_after=retry_after)
                continue
            return TelegramSendResult(
                False,
                error_summary=f"http_status:{response.status_code}",
                attempts=attempt,
            )
        raise AssertionError("Telegram retry loop exhausted unexpectedly")

    def _backoff(self, attempt: int, *, retry_after: str | None = None) -> None:
        delay = self.settings.telegram_backoff_seconds * (2 ** (attempt - 1))
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        LOGGER.warning("Telegram request retry scheduled", extra={"attempt": attempt})
        self.sleeper(delay)
