from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.analysis import JobAnalysis
from app.domain.application import ApplicationEvent
from app.domain.candidate import CandidateProfile
from app.domain.enums import (
    ApplicationStatus,
    DescriptionCompleteness,
    JobSource,
)
from app.domain.job import Job, JobDescription
from app.domain.operations import CVArtifact, CollectionRun


def test_job_model_validation_and_stable_id() -> None:
    job = Job(
        source=JobSource.ARBEITSAGENTUR,
        source_job_id="abc-123",
        title_raw=" Data Analyst ",
        title_normalized="data analyst",
        language_confidence=0.8,
    )
    assert job.id
    assert job.source_job_id == "abc-123"

    with pytest.raises(ValidationError):
        Job(
            source=JobSource.ENGLISHJOBS,
            title_raw="",
            title_normalized="data analyst",
        )
    with pytest.raises(ValidationError):
        Job(
            source=JobSource.ENGLISHJOBS,
            title_raw="Analyst",
            title_normalized="analyst",
            language_confidence=1.5,
        )


def test_full_or_snippet_description_requires_text() -> None:
    with pytest.raises(ValidationError, match="full description"):
        JobDescription(
            job_id=uuid4(),
            completeness=DescriptionCompleteness.FULL,
            content_hash="0" * 64,
        )


def test_candidate_profile_uses_master_cv_shape(master_cv_data: dict) -> None:
    profile = CandidateProfile.from_master_cv(master_cv_data, version=1)
    assert profile.display_name == "Test Candidate"
    assert profile.version == 1
    assert len(profile.content_hash) == 64

    broken = {"personal_info": {"full_name": "Broken"}}
    with pytest.raises(ValidationError, match="master-CV sections"):
        CandidateProfile.from_master_cv(broken, version=1)


def test_job_analysis_score_validation() -> None:
    with pytest.raises(ValidationError):
        JobAnalysis(
            job_id=uuid4(),
            profile_id=uuid4(),
            profile_version=1,
            analyzer_version="rules-v1",
            description_completeness="full",
            fit_score=101,
        )


def test_application_event_is_frozen() -> None:
    event = ApplicationEvent(
        application_id=uuid4(),
        from_status=None,
        to_status=ApplicationStatus.NEW,
    )
    with pytest.raises(ValidationError):
        event.reason = "changed"


def test_collection_run_rejects_reverse_timestamps() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="finished_at"):
        CollectionRun(
            source=JobSource.MANUAL,
            started_at=now,
            finished_at=now - timedelta(seconds=1),
        )


def test_cv_artifact_is_flowcv_txt_only() -> None:
    artifact = CVArtifact(
        job_id=uuid4(),
        profile_id=uuid4(),
        profile_version=1,
        path=Path("artifact.txt"),
    )
    assert artifact.artifact_format.value == "flowcv_txt"

