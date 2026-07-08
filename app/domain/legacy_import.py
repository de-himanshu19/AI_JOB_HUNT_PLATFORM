"""Milestone 9 legacy-import contracts and audit models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


IMPORTER_VERSION = "legacy-import-v1"


def utc_now() -> datetime:
    return datetime.now(UTC)


class LegacySourceType(StrEnum):
    ENGLISHJOBS_CSV = "englishjobs_csv"
    STATE_INTELLIGENCE_CSV = "state_intelligence_csv"
    SENT_JOBS_JSON = "sent_jobs_json"
    MASTER_CV_JSON = "master_cv_json"
    LEGACY_ARTIFACT = "legacy_artifact"
    MYSQL_FIXTURE = "mysql_fixture"


class LegacyImportMode(StrEnum):
    DRY_RUN = "dry_run"
    APPLY = "apply"


class LegacyImportStatus(StrEnum):
    PLANNED = "planned"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    REUSED = "reused"


class LegacyImportAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    LINKED = "linked"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class LegacyItemType(StrEnum):
    JOB = "job"
    DESCRIPTION = "description"
    NOTIFICATION = "notification"
    PROFILE = "profile"
    ARTIFACT = "artifact"
    MYSQL_ROW = "mysql_row"


class LegacyArtifactKind(StrEnum):
    FLOWCV_TXT = "flowcv_txt"
    EVIDENCE_REPORT = "evidence_report"
    AI_DEBUG = "ai_debug"
    ANALYSIS_REPORT = "analysis_report"
    COVER_LETTER = "cover_letter"
    OTHER_TXT = "other_txt"


class LegacyBackup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    database_path: Path
    backup_path: Path
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    verified: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    verified_at: datetime | None = None


class LegacyImportBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    source_type: LegacySourceType
    source_name: str = Field(min_length=1)
    source_path: Path | None = None
    source_checksum: str = Field(min_length=64, max_length=64)
    importer_version: str = IMPORTER_VERSION
    mode: LegacyImportMode
    status: LegacyImportStatus = LegacyImportStatus.PLANNED
    backup_id: UUID | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    records_read: int = Field(default=0, ge=0)
    creates: int = Field(default=0, ge=0)
    updates: int = Field(default=0, ge=0)
    skips: int = Field(default=0, ge=0)
    conflicts: int = Field(default=0, ge=0)
    uncertain: int = Field(default=0, ge=0)
    rejected: int = Field(default=0, ge=0)
    warnings: tuple[str, ...] = ()
    reconciliation: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class LegacyImportItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    batch_id: UUID
    item_key: str = Field(min_length=1)
    item_type: LegacyItemType
    action: LegacyImportAction
    original_source_identifier: str | None = None
    source_checksum: str = Field(min_length=64, max_length=64)
    content_checksum: str | None = Field(default=None, min_length=64, max_length=64)
    mapping_confidence: float = Field(default=0, ge=0, le=1)
    target_table: str | None = None
    target_id: str | None = None
    warnings: tuple[str, ...] = ()
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class LegacyImportMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    item_id: UUID
    mapping_type: str = Field(min_length=1)
    target_table: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    suppresses_notifications: bool = False
    warnings: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=utc_now)


class LegacyImportPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: LegacySourceType
    source_name: str
    source_path: Path | None = None
    source_checksum: str
    batch_id: UUID | None = None
    backup_id: UUID | None = None
    records_read: int = 0
    creates: int = 0
    updates: int = 0
    skips: int = 0
    conflicts: int = 0
    uncertain: int = 0
    rejected: int = 0
    warnings: tuple[str, ...] = ()
    items: tuple[LegacyImportItem, ...] = ()
    reconciliation: dict[str, Any] = Field(default_factory=dict)
    database_modified: bool = False
    network_requested: bool = False
    idempotent_replay: bool = False
