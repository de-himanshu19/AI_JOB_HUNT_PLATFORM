"""Typed raw Arbeitsagentur records retained before common-model conversion."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LanguageSignals(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    detected_language: str | None = None
    language_confidence: float | None = Field(default=None, ge=0, le=1)
    german_requirement: str | None = None
    german_level: str | None = None
    english_signal: bool = False
    customer_facing_german_risk: bool = False
    matched_german_phrases: tuple[str, ...] = ()
    matched_english_phrases: tuple[str, ...] = ()
    matched_customer_facing_phrases: tuple[str, ...] = ()


class RawJobSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_job_id: str
    title: str
    company: str | None = None
    location_raw: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    publication_date: date | None = None
    profession: str | None = None
    external_url: str | None = None
    source_detail_url: str
    search_term: str
    search_terms: tuple[str, ...]
    description_snippet: str | None = None


class RawJobDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_job_id: str
    description: str | None = None
    responsibilities: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    employer_details: str | None = None
    work_locations: tuple[dict[str, Any], ...] = ()
    employment_type: str | None = None
    contract_type: str | None = None
    working_time: tuple[str, ...] = ()
    start_date: date | None = None
    application_deadline: date | None = None
    original_application_url: str | None = None
    source_url: str | None = None
    language_signals: LanguageSignals = Field(default_factory=LanguageSignals)
    structured_data: dict[str, Any] = Field(default_factory=dict)


class SearchPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[RawJobSummary] = Field(default_factory=list)
    total_results: int | None = Field(default=None, ge=0)
    record_errors: list[str] = Field(default_factory=list)

