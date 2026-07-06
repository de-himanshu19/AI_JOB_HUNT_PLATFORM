import json
from pathlib import Path

from app.domain.candidate import CandidateEvidenceProfile, CandidateProfile
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.services.prefilter import PrefilterService


FIXTURES = Path(__file__).parents[1] / "fixtures" / "fit_analysis"


def _profile():
    payload = json.loads((FIXTURES / "candidate_profile.json").read_text(encoding="utf-8"))
    return CandidateEvidenceProfile.from_candidate_profile(
        CandidateProfile.from_master_cv(payload, version=1)
    )


def test_prefilter_is_profile_driven_and_source_neutral() -> None:
    description = JobDescription(
        job_id="00000000-0000-0000-0000-000000000001",
        raw_text="SQL reporting role in Berlin",
        completeness=DescriptionCompleteness.SNIPPET,
        content_hash="snippet",
    )
    scores = []
    for source in (JobSource.ARBEITSAGENTUR, JobSource.ENGLISHJOBS):
        job = Job(
            source=source, title_raw="Data Analyst",
            title_normalized="data analyst", location_raw="Berlin",
        )
        scores.append(PrefilterService().score(job, description, _profile()))
    assert scores[0] == scores[1]
    assert scores[0][0] > 0


def test_prefilter_has_no_candidate_independent_bank_bonus() -> None:
    job = Job(
        source=JobSource.MANUAL, title_raw="Unrelated Role at a Bank",
        title_normalized="unrelated role at a bank",
    )
    score, components = PrefilterService().score(job, None, _profile())
    assert score == 0
    assert not components
