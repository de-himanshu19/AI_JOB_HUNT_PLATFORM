"""Narrow source-independent collection contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.job import Job, JobDescription


class SourceRunStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class CollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    queries: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    location: str = "Deutschland"
    published_within_days: int = Field(default=7, ge=0, le=365)
    max_pages: int = Field(default=5, ge=1, le=100)
    page_size: int = Field(default=25, ge=1, le=100)

    @field_validator("queries", "states", mode="before")
    @classmethod
    def normalize_values(cls, value):
        if value is None:
            return ()
        if isinstance(value, str):
            value = (value,)
        unique = tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        return unique

    @model_validator(mode="after")
    def validate_scope(self) -> "CollectionRequest":
        if not self.queries and not self.states:
            raise ValueError("At least one collection query or state is required")
        return self


class CollectionError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: str
    message: str
    query: str | None = None
    state: str | None = None
    page: int | None = None
    source_job_id: str | None = None
    error_type: str
    retriable: bool = False


class CollectedJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: Job
    description: JobDescription


class CollectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[CollectedJob] = Field(default_factory=list)
    queries_executed: int = 0
    states_executed: int = 0
    pages_requested: int = 0
    jobs_parsed: int = 0
    invalid_cards: int = 0
    repeated_pages: int = 0
    search_requests_succeeded: int = 0
    search_requests_failed: int = 0
    detail_requests_succeeded: int = 0
    detail_requests_failed: int = 0
    errors: list[CollectionError] = Field(default_factory=list)
    status: SourceRunStatus = SourceRunStatus.STARTED


class JobSourceAdapter(Protocol):
    def collect(self, request: CollectionRequest) -> CollectionResult: ...
