"""Immutable Milestone 7 CV artifact and AI-attempt records."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ArtifactFormat, ArtifactSource


class GenerationMode(StrEnum):
    STORED_JOB = "stored_job"
    MANUAL_JD = "manual_jd"


class AIAttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CVGenerationArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    job_id: UUID | None = None
    logical_cluster_id: UUID | None = None
    description_id: UUID | None = None
    description_content_hash: str = Field(min_length=64, max_length=64)
    description_completeness: str = "full"
    profile_id: UUID
    profile_version: int = Field(ge=1)
    profile_content_hash: str = Field(min_length=64, max_length=64)
    analysis_id: UUID | None = None
    analyzer_version: str = Field(min_length=1)
    rules_version: str = Field(min_length=1)
    generator_version: str = Field(min_length=1)
    formatter_version: str = Field(min_length=1)
    generation_mode: GenerationMode
    generation_identity: str = Field(min_length=64, max_length=64)
    artifact_format: ArtifactFormat = ArtifactFormat.FLOWCV_TXT
    source: ArtifactSource = ArtifactSource.RULE_BASED
    parent_rule_based_artifact_id: UUID | None = None
    artifact_path: Path
    evidence_report_path: Path
    content_hash: str = Field(min_length=64, max_length=64)
    evidence_report_hash: str = Field(min_length=64, max_length=64)
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    ai_generated_at: datetime | None = None
    validated: bool
    validation_result: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_provenance(self) -> "CVGenerationArtifact":
        stored = self.generation_mode is GenerationMode.STORED_JOB
        if stored and not all((self.job_id, self.description_id, self.analysis_id)):
            raise ValueError("Stored-job artifacts require job, description, and analysis IDs")
        if not stored and any((self.job_id, self.description_id, self.analysis_id)):
            raise ValueError("Manual-JD artifacts must not claim stored provenance")
        if self.description_completeness != "full":
            raise ValueError("CV generation requires a full description")
        if self.source is ArtifactSource.RULE_BASED:
            if self.parent_rule_based_artifact_id or any(
                (self.provider, self.model, self.prompt_version, self.ai_generated_at)
            ):
                raise ValueError("Rule-based artifacts cannot claim AI provenance")
        elif not all((
            self.parent_rule_based_artifact_id, self.provider, self.model,
            self.prompt_version, self.ai_generated_at,
        )):
            raise ValueError("AI derivatives require complete parent and provider provenance")
        return self


class CVAIAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    parent_rule_based_artifact_id: UUID
    derivative_artifact_id: UUID | None = None
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    status: AIAttemptStatus
    failure_category: str | None = None
    evidence_report_path: Path
    validation_result: dict[str, object] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_outcome(self) -> "CVAIAttempt":
        if self.status is AIAttemptStatus.SUCCEEDED:
            if self.derivative_artifact_id is None or self.failure_category is not None:
                raise ValueError("Successful AI attempts require only a derivative artifact")
        elif self.derivative_artifact_id is not None or not self.failure_category:
            raise ValueError("Failed AI attempts require a safe failure category")
        return self
