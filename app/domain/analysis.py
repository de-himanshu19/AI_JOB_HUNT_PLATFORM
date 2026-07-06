"""Typed, immutable fit-analysis and ranking records."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class AnalysisAuthority(StrEnum):
    AUTHORITATIVE = "authoritative"
    PREFILTER_ONLY = "prefilter_only"


class RequirementCategory(StrEnum):
    ROLE = "role"
    SENIORITY = "seniority"
    SKILL = "skill"
    TOOL = "tool"
    LANGUAGE = "language"
    DOMAIN = "domain"
    EDUCATION = "education"


class EvidenceType(StrEnum):
    DIRECT_PROFESSIONAL = "direct_professional"
    PROFESSIONAL_TRANSFERABLE = "professional_transferable"
    PROJECT = "project"
    EDUCATION_TRAINING = "education_training_certification"
    NO_EVIDENCE = "no_evidence"


class JobRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: RequirementCategory
    required: bool = True
    level: str | None = None
    source_text: str | None = None


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    evidence_type: EvidenceType
    evidence_id: str | None = None
    label: str | None = None
    reason: str


class ScoreComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    points: float
    reason: str


class ScoreCap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    maximum: float = Field(ge=0, le=100)
    reason: str


class JobAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    description_id: UUID | None = None
    description_content_hash: str | None = None
    profile_id: UUID
    profile_version: int = Field(ge=1)
    analyzer_version: str = Field(min_length=1)
    rules_version: str = "legacy"
    ranking_version: str = "legacy"
    analysis_input_hash: str | None = None
    description_completeness: str
    authority: AnalysisAuthority = AnalysisAuthority.PREFILTER_ONLY
    completeness_warning: str | None = None
    requirements: tuple[JobRequirement, ...] | dict[str, Any] = ()
    evidence: tuple[EvidenceReference, ...] | dict[str, Any] = ()
    missing_skills: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    prefilter_score: float | None = Field(default=None, ge=0, le=100)
    fit_score: float | None = Field(default=None, ge=0, le=100)
    fit_reasons: tuple[str, ...] = ()
    positive_components: tuple[ScoreComponent, ...] = ()
    penalties: tuple[ScoreComponent, ...] = ()
    score_caps: tuple[ScoreCap, ...] = ()
    language_risk_penalty: float = Field(default=0, ge=0, le=100)
    banking_preference_bonus: float = Field(default=0, ge=0, le=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobRanking(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    cluster_id: UUID | None = None
    analysis_id: UUID
    profile_id: UUID
    profile_version: int = Field(ge=1)
    ranking_version: str
    ranking_input_hash: str
    ranked_as_of: datetime
    authority: AnalysisAuthority
    rank_score: float
    components: tuple[ScoreComponent, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
