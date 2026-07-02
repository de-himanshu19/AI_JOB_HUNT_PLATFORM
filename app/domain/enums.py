"""Stable persisted enum values for the unified application."""

from enum import StrEnum


class JobSource(StrEnum):
    ARBEITSAGENTUR = "arbeitsagentur"
    ENGLISHJOBS = "englishjobs"
    MANUAL = "manual"


class DescriptionCompleteness(StrEnum):
    FULL = "full"
    SNIPPET = "snippet"
    MISSING = "missing"


class ApplicationStatus(StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    CV_READY = "cv_ready"
    APPLIED = "applied"
    SKIPPED = "skipped"
    REJECTED = "rejected"
    INTERVIEW = "interview"


class CollectionRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class NotificationChannel(StrEnum):
    TELEGRAM = "telegram"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class ArtifactFormat(StrEnum):
    FLOWCV_TXT = "flowcv_txt"


class ArtifactSource(StrEnum):
    RULE_BASED = "rule_based"
    AI_POLISHED = "ai_polished"

