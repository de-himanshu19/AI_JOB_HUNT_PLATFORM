"""Source-independent job and versioned description models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import DescriptionCompleteness, JobSource


def utc_now() -> datetime:
    return datetime.now(UTC)


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    source: JobSource
    source_job_id: str | None = None
    source_url: str | None = None
    canonical_url: str | None = None

    title_raw: str = Field(min_length=1)
    title_normalized: str = Field(min_length=1)
    company_raw: str | None = None
    company_normalized: str | None = None
    location_raw: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_mode: str | None = None
    language_detected: str | None = None
    language_confidence: float | None = Field(default=None, ge=0, le=1)
    explicit_german_requirement: str | None = None
    published_at: datetime | None = None
    expires_at: datetime | None = None
    employment_type: str | None = None
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    active: bool = True
    first_seen_run_id: UUID | None = None
    last_seen_run_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("source_job_id", "source_url", "canonical_url", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_timestamps(self) -> "Job":
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("last_seen_at cannot be before first_seen_at")
        return self


class JobDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    raw_text: str | None = None
    normalized_text: str | None = None
    completeness: DescriptionCompleteness = DescriptionCompleteness.MISSING
    content_hash: str
    fetched_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_completeness(self) -> "JobDescription":
        if self.completeness is DescriptionCompleteness.FULL and not self.raw_text:
            raise ValueError("A full description must contain raw text")
        if self.completeness is DescriptionCompleteness.SNIPPET and not self.raw_text:
            raise ValueError("A snippet description must contain raw text")
        return self

