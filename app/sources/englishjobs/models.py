"""Typed raw EnglishJobs.de records retained before common-model conversion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class RawEnglishJobsRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing_id: str | None = None
    title: str
    company: str | None = None
    location_raw: str | None = None
    city: str | None = None
    state_key: str | None = None
    state_display: str | None = None
    published_text: str | None = None
    listing_url: str | None = None
    clickout_url: str | None = None
    description_snippet: str | None = None
    search_query: str | None = None
    search_location: str | None = None
    search_state: str | None = None
    discovered_queries: tuple[str, ...] = ()
    discovered_states: tuple[str, ...] = ()
    page_number: int = Field(ge=1)
    retrieved_at: datetime = Field(default_factory=utc_now)


class RawEnglishJobsDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    company: str | None = None
    location_raw: str | None = None
    description: str | None = None
    canonical_url: str | None = None
    final_url: str | None = None
    structured_data: dict[str, Any] = Field(default_factory=dict)


class ParsedEnglishJobsPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[RawEnglishJobsRecord] = Field(default_factory=list)
    total_jobs: int | None = None
    has_next_page: bool | None = None
    invalid_cards: int = 0
    record_errors: list[str] = Field(default_factory=list)
    page_fingerprint: tuple[str, ...] = ()
