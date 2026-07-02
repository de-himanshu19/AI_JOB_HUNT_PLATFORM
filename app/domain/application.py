"""Application lifecycle models with immutable events."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ApplicationStatus


class Application(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    profile_id: UUID
    status: ApplicationStatus = ApplicationStatus.NEW
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApplicationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    application_id: UUID
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

