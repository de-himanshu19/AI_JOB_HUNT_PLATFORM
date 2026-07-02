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

