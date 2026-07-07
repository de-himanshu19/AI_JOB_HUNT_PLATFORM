"""Collection, notification, and CV-artifact persistence models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    ArtifactFormat,
    ArtifactSource,
    CollectionRunStatus,
    JobSource,
    NotificationChannel,
    NotificationBatchStatus,
    NotificationStatus,
)


class CollectionRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    source: JobSource
    status: CollectionRunStatus = CollectionRunStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    jobs_found: int = Field(default=0, ge=0)
    jobs_stored: int = Field(default=0, ge=0)
    jobs_inserted: int = Field(default=0, ge=0)
    jobs_updated: int = Field(default=0, ge=0)
    queries_executed: int = Field(default=0, ge=0)
    pages_requested: int = Field(default=0, ge=0)
    search_requests_succeeded: int = Field(default=0, ge=0)
    search_requests_failed: int = Field(default=0, ge=0)
    detail_requests_succeeded: int = Field(default=0, ge=0)
    detail_requests_failed: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    error_summary: str | None = None
    config_snapshot: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_run_times(self) -> "CollectionRun":
        if self.started_at and self.finished_at and self.finished_at < self.started_at:
            raise ValueError("finished_at cannot be before started_at")
        return self


class Notification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    profile_id: UUID
    channel: NotificationChannel = NotificationChannel.TELEGRAM
    status: NotificationStatus = NotificationStatus.PENDING
    idempotency_key: str = Field(min_length=1)
    remote_message_id: str | None = None
    attempted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sent_at: datetime | None = None
    error_summary: str | None = None


class NotificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    profile_id: UUID
    channel: NotificationChannel = NotificationChannel.TELEGRAM
    ranking_version: str = Field(min_length=1)
    duplicate_algorithm_version: str = Field(min_length=1)
    top_n: int = Field(default=20, ge=1, le=20)
    status: NotificationBatchStatus = NotificationBatchStatus.PENDING
    selected_count: int = Field(default=0, ge=0, le=20)
    chunks_total: int = Field(default=0, ge=0)
    chunks_sent: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


class NotificationDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    batch_id: UUID
    chunk_index: int = Field(ge=1)
    attempt_number: int = Field(default=1, ge=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    status: NotificationStatus = NotificationStatus.PENDING
    remote_message_id: str | None = None
    attempted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sent_at: datetime | None = None
    error_summary: str | None = None


class NotificationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    batch_id: UUID
    delivery_id: UUID
    duplicate_cluster_id: UUID
    duplicate_algorithm_version: str = Field(min_length=1)
    representative_job_id: UUID
    ranking_id: UUID
    profile_id: UUID
    channel: NotificationChannel = NotificationChannel.TELEGRAM
    position: int = Field(ge=1, le=20)
    idempotency_key: str = Field(min_length=64, max_length=64)
    snapshot: dict[str, object] = Field(default_factory=dict)
    status: NotificationStatus = NotificationStatus.PENDING
    sent_at: datetime | None = None
    error_summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CVArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    profile_id: UUID
    analysis_id: UUID | None = None
    profile_version: int = Field(ge=1)
    artifact_format: ArtifactFormat = ArtifactFormat.FLOWCV_TXT
    source: ArtifactSource = ArtifactSource.RULE_BASED
    path: Path
    validated: bool = False
    validation_summary: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
