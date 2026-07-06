"""Typed domain models shared by every future source and delivery surface."""

from app.domain.analysis import (
    AnalysisAuthority,
    EvidenceReference,
    EvidenceType,
    JobAnalysis,
    JobRanking,
    JobRequirement,
    RequirementCategory,
    ScoreCap,
    ScoreComponent,
)
from app.domain.application import Application, ApplicationEvent
from app.domain.candidate import CandidateEvidenceProfile, CandidateProfile
from app.domain.duplicates import (
    DuplicateCandidate,
    DuplicateCluster,
    DuplicateMatchMethod,
    JobDuplicateLink,
    MatchDecision,
    ReviewStatus,
)
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
    "AnalysisAuthority",
    "ArtifactFormat",
    "ArtifactSource",
    "CVArtifact",
    "CandidateProfile",
    "CandidateEvidenceProfile",
    "CollectionRun",
    "CollectionRunStatus",
    "DescriptionCompleteness",
    "EvidenceReference",
    "EvidenceType",
    "DuplicateCandidate",
    "DuplicateCluster",
    "DuplicateMatchMethod",
    "Job",
    "JobAnalysis",
    "JobRanking",
    "JobRequirement",
    "JobDescription",
    "JobDuplicateLink",
    "JobSource",
    "Notification",
    "NotificationChannel",
    "NotificationStatus",
    "MatchDecision",
    "ReviewStatus",
    "RequirementCategory",
    "ScoreCap",
    "ScoreComponent",
]
