"""Application lifecycle models with immutable events."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ApplicationStatus


class ApplicationPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Application(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    profile_id: UUID
    logical_cluster_id: UUID | None = None
    status: ApplicationStatus = ApplicationStatus.NEW
    priority: ApplicationPriority | None = None
    notes: str = ""
    follow_up_date: date | None = None
    cv_artifact_id: UUID | None = None
    source: str = "manual"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApplicationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    application_id: UUID
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    event_type: str = "status_changed"
    reason: str | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
