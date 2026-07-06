"""Typed models for explainable, versioned duplicate clustering."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.job import utc_now


class DuplicateMatchMethod(StrEnum):
    SINGLETON = "singleton"
    EXACT_SOURCE_ID = "exact_source_id"
    CANONICAL_URL = "canonical_url"
    STRONG_FINGERPRINT = "strong_fingerprint"
    CROSS_SOURCE_SIMILARITY = "cross_source_similarity"
    MANUAL = "manual"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DuplicateCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    representative_job_id: UUID
    algorithm_version: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class JobDuplicateLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    cluster_id: UUID
    algorithm_version: str = Field(min_length=1)
    match_method: DuplicateMatchMethod
    confidence: float = Field(ge=0, le=1)
    reasons: tuple[str, ...] = ()
    reviewed: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class DuplicateCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    left_job_id: UUID
    right_job_id: UUID
    algorithm_version: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    reasons: tuple[str, ...] = ()
    status: ReviewStatus = ReviewStatus.PENDING
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class MatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: DuplicateMatchMethod | None = None
    confidence: float = Field(ge=0, le=1)
    reasons: tuple[str, ...] = ()
    should_cluster: bool = False
    needs_review: bool = False
