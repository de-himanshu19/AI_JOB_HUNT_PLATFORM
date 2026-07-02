"""Persistable placeholder for later deterministic fit-analysis results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class JobAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    profile_id: UUID
    profile_version: int = Field(ge=1)
    analyzer_version: str = Field(min_length=1)
    description_completeness: str
    requirements: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    missing_skills: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    prefilter_score: float | None = Field(default=None, ge=0, le=100)
    fit_score: float | None = Field(default=None, ge=0, le=100)
    fit_reasons: list[str] = Field(default_factory=list)
    language_risk_penalty: float = Field(default=0, ge=0, le=100)
    banking_preference_bonus: float = Field(default=0, ge=0, le=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

