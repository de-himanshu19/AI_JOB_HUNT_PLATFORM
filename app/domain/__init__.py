"""Typed domain models shared by every future source and delivery surface."""

from app.domain.analysis import JobAnalysis
from app.domain.application import Application, ApplicationEvent
from app.domain.candidate import CandidateProfile
from app.domain.enums import (
    ApplicationStatus,
    ArtifactFormat,
    ArtifactSource,
    CollectionRunStatus,
    DescriptionCompleteness,
    JobSource,
    NotificationChannel,
    NotificationStatus,
)
from app.domain.job import Job, JobDescription
from app.domain.operations import CVArtifact, CollectionRun, Notification

__all__ = [
    "Application",
    "ApplicationEvent",
    "ApplicationStatus",
    "ArtifactFormat",
    "ArtifactSource",
    "CVArtifact",
    "CandidateProfile",
    "CollectionRun",
    "CollectionRunStatus",
    "DescriptionCompleteness",
    "Job",
    "JobAnalysis",
    "JobDescription",
    "JobSource",
    "Notification",
    "NotificationChannel",
    "NotificationStatus",
]

