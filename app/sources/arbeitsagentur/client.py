"""Resilient, injectable HTTP client for Arbeitsagentur search and details."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Protocol

import requests

from app.config import Settings
from app.logging_config import log_event


LOGGER = logging.getLogger(__name__)


class SessionLike(Protocol):
    headers: dict[str, str]

    def get(self, url: str, **kwargs): ...


class ArbeitsagenturClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retriable: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retriable = retriable


class RetryExhaustedError(ArbeitsagenturClientError):
    pass


class ResponseFormatError(ArbeitsagenturClientError):
    pass


def encode_ref_number(reference: str) -> str:
    encoded = base64.urlsafe_b64encode(reference.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


class ArbeitsagenturClient:
    def __init__(
        self,
        settings: Settings,
        *,
        session: SessionLike | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.session.headers.update(
            {"X-API-Key": settings.arbeitsagentur_api_key.get_secret_value()}
        )

    def search(
        self,
        query: str,
        *,
        location: str,
        page: int,
        page_size: int,
        published_within_days: int,
    ) -> dict[str, Any]:
        return self._get_json(
            self.settings.arbeitsagentur_search_url,
            params={
                "was": query,
                "wo": location,
                "angebotsart": "1",
                "size": page_size,
                "page": page,
                "veroeffentlichtseit": published_within_days,
            },
            operation="search",
        )

    def fetch_details(self, source_job_id: str, url: str | None = None) -> dict[str, Any]:
        detail_url = url or (
            self.settings.arbeitsagentur_detail_url.rstrip("/")
            + "/"
            + encode_ref_number(source_job_id)
        )
        return self._get_json(detail_url, params=None, operation="detail")

    def _get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None,
        operation: str,
    ) -> dict[str, Any]:
        attempts = self.settings.arbeitsagentur_max_retries + 1
        last_message = f"{operation} request failed"
        last_status: int | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=(
                        self.settings.arbeitsagentur_connect_timeout_seconds,
                        self.settings.arbeitsagentur_read_timeout_seconds,
                    ),
                )
            except (requests.Timeout, requests.ConnectionError) as error:
                last_message = f"{operation} request failed: {type(error).__name__}"
                if attempt == attempts:
                    raise RetryExhaustedError(
                        last_message, retriable=True
                    ) from error
                self._backoff(attempt, operation, None)
                continue
            except requests.RequestException as error:
                raise ArbeitsagenturClientError(
                    f"{operation} request failed: {type(error).__name__}",
                    retriable=False,
                ) from error

            last_status = int(response.status_code)
            if last_status == 429 or 500 <= last_status <= 599:
                last_message = f"{operation} request returned HTTP {last_status}"
                if attempt == attempts:
                    raise RetryExhaustedError(
                        last_message, status_code=last_status, retriable=True
                    )
                self._backoff(attempt, operation, last_status)
                continue
            if 400 <= last_status <= 499:
                raise ArbeitsagenturClientError(
                    f"{operation} request returned HTTP {last_status}",
                    status_code=last_status,
                    retriable=False,
                )

            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError) as error:
                raise ResponseFormatError(
                    f"{operation} response was not valid JSON",
                    status_code=last_status,
                    retriable=False,
                ) from error
            if not isinstance(payload, dict):
                raise ResponseFormatError(
                    f"{operation} response root must be an object",
                    status_code=last_status,
                    retriable=False,
                )
            return payload

        raise RetryExhaustedError(
            last_message, status_code=last_status, retriable=True
        )

    def _backoff(
        self, attempt: int, operation: str, status_code: int | None
    ) -> None:
        delay = self.settings.arbeitsagentur_backoff_seconds * (2 ** (attempt - 1))
        log_event(
            LOGGER,
            "arbeitsagentur.retry",
            "Retrying Arbeitsagentur request",
            operation=operation,
            attempt=attempt,
            status_code=status_code,
            delay_seconds=delay,
        )
        self.sleeper(delay)


class FixtureArbeitsagenturClient:
    """Read saved fixture JSON for explicit, offline dry runs."""

    def __init__(self, fixture_directory: Path):
        self.fixture_directory = Path(fixture_directory)
        if not self.fixture_directory.is_dir():
            raise ArbeitsagenturClientError(
                f"Fixture directory does not exist: {self.fixture_directory}",
                retriable=False,
            )
        self._details: dict[str, dict[str, Any]] = {}
        for path in self.fixture_directory.glob("detail_*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as error:
                raise ArbeitsagenturClientError(
                    f"Invalid detail fixture: {path.name}", retriable=False
                ) from error
            reference = str(payload.get("referenznummer") or "").strip()
            if reference:
                self._details[reference] = payload

    def search(
        self,
        query: str,
        *,
        location: str,
        page: int,
        page_size: int,
        published_within_days: int,
    ) -> dict[str, Any]:
        path = self.fixture_directory / f"search_page_{page}.json"
        if not path.exists():
            path = self.fixture_directory / "search_empty.json"
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            raise ArbeitsagenturClientError(
                f"Invalid search fixture for page {page}", retriable=False
            ) from error

    def fetch_details(self, source_job_id: str, url: str | None = None) -> dict[str, Any]:
        try:
            return self._details[source_job_id]
        except KeyError as error:
            safe_reference = re.sub(r"[^A-Za-z0-9_.-]", "_", source_job_id)
            raise ArbeitsagenturClientError(
                f"No detail fixture for source reference {safe_reference}",
                retriable=False,
            ) from error
