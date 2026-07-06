"""Resilient, injectable HTTP client for EnglishJobs.de search and detail pages."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlparse

import requests

from app.config import Settings
from app.logging_config import log_event
from app.sources.englishjobs.url_builder import (
    build_keyword_url,
    build_state_url,
)


LOGGER = logging.getLogger(__name__)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
}


class SessionLike(Protocol):
    headers: dict[str, str]

    def get(self, url: str, **kwargs): ...


class EnglishJobsClientError(RuntimeError):
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


class RetryExhaustedError(EnglishJobsClientError):
    pass


@dataclass(frozen=True)
class FetchedDocument:
    requested_url: str
    final_url: str
    text: str


class EnglishJobsClient:
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
        self._request_count = 0
        self.session.headers.update(DEFAULT_HEADERS)

    def search_state(self, state_slug: str, *, page: int) -> FetchedDocument:
        return self._get_text(
            build_state_url(self.settings.englishjobs_base_url, state_slug, page),
            operation="state_search",
        )

    def search_query(
        self,
        query: str,
        *,
        location: str | None,
        page: int,
    ) -> FetchedDocument:
        return self._get_text(
            build_keyword_url(
                self.settings.englishjobs_base_url,
                query,
                location,
                page,
            ),
            operation="query_search",
        )

    def fetch_document(self, url: str, *, operation: str) -> FetchedDocument:
        return self._get_text(url, operation=operation)

    def _get_text(self, url: str, *, operation: str) -> FetchedDocument:
        attempts = self.settings.englishjobs_max_retries + 1
        last_message = f"{operation} request failed"
        last_status: int | None = None

        if self._request_count > 0 and self.settings.englishjobs_request_delay_seconds:
            self.sleeper(self.settings.englishjobs_request_delay_seconds)
        self._request_count += 1

        for attempt in range(1, attempts + 1):
            try:
                response = self.session.get(
                    url,
                    timeout=(
                        self.settings.englishjobs_connect_timeout_seconds,
                        self.settings.englishjobs_read_timeout_seconds,
                    ),
                    allow_redirects=True,
                )
            except (requests.Timeout, requests.ConnectionError) as error:
                last_message = f"{operation} request failed: {type(error).__name__}"
                if attempt == attempts:
                    raise RetryExhaustedError(last_message, retriable=True) from error
                self._backoff(attempt, operation, None)
                continue
            except requests.RequestException as error:
                raise EnglishJobsClientError(
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
                raise EnglishJobsClientError(
                    f"{operation} request returned HTTP {last_status}",
                    status_code=last_status,
                    retriable=False,
                )

            return FetchedDocument(
                requested_url=url,
                final_url=getattr(response, "url", url),
                text=response.text,
            )

        raise RetryExhaustedError(last_message, status_code=last_status, retriable=True)

    def _backoff(self, attempt: int, operation: str, status_code: int | None) -> None:
        delay = self.settings.englishjobs_backoff_seconds * (2 ** (attempt - 1))
        log_event(
            LOGGER,
            "englishjobs.retry",
            "Retrying EnglishJobs request",
            operation=operation,
            attempt=attempt,
            status_code=status_code,
            delay_seconds=delay,
        )
        self.sleeper(delay)


class FixtureEnglishJobsClient:
    """Read saved HTML fixtures for explicit, offline dry runs."""

    def __init__(self, fixture_directory: Path, *, base_url: str = "https://englishjobs.de"):
        self.fixture_directory = Path(fixture_directory)
        self.base_url = base_url.rstrip("/")
        if not self.fixture_directory.is_dir():
            raise EnglishJobsClientError(
                f"Fixture directory does not exist: {self.fixture_directory}",
                retriable=False,
            )

    def search_state(self, state_slug: str, *, page: int) -> FetchedDocument:
        filename = f"state_{state_slug}_page_{page}.html"
        return self._load(filename, build_state_url(self.base_url, state_slug, page))

    def search_query(
        self,
        query: str,
        *,
        location: str | None,
        page: int,
    ) -> FetchedDocument:
        safe_query = _slug(query, separator="_")
        safe_location = _slug(location or "none", separator="-")
        filename = f"query_{safe_query}_location_{safe_location}_page_{page}.html"
        return self._load(
            filename,
            build_keyword_url(self.base_url, query, location, page),
        )

    def fetch_document(self, url: str, *, operation: str) -> FetchedDocument:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if path.startswith("clickout/"):
            slug = path.split("/", 1)[1]
            filename = f"clickout_{slug}.txt"
            return self._load_redirect(filename, url)
        slug = path.replace("/", "_") or "root"
        filename = f"detail_{slug}.html"
        return self._load(filename, url)

    def _load(self, filename: str, url: str) -> FetchedDocument:
        path = self.fixture_directory / filename
        if not path.exists():
            path = self.fixture_directory / "empty.html"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise EnglishJobsClientError(
                f"Invalid HTML fixture: {path.name}",
                retriable=False,
            ) from error
        return FetchedDocument(requested_url=url, final_url=url, text=text)

    def _load_redirect(self, filename: str, url: str) -> FetchedDocument:
        path = self.fixture_directory / filename
        if not path.exists():
            raise EnglishJobsClientError(
                f"Missing clickout fixture: {filename}",
                retriable=False,
            )
        try:
            final_url = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise EnglishJobsClientError(
                f"Invalid clickout fixture: {filename}",
                retriable=False,
            ) from error
        return FetchedDocument(requested_url=url, final_url=final_url, text="")


def _slug(value: str, *, separator: str) -> str:
    return separator.join(" ".join(value.strip().split()).lower().split(" "))
