from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.analysis import AnalysisAuthority, JobRanking
from app.domain.enums import JobSource
from app.domain.job import Job
from app.services.ranking import RankedVacancy, RankingService


NOW = datetime(2026, 7, 6, tzinfo=UTC)


def _ranked(title, *, score=90, fit=80, published=NOW, first_seen=NOW):
    job = Job(
        source=JobSource.MANUAL, title_raw=title,
        title_normalized=title.casefold(), published_at=published,
        first_seen_at=first_seen, last_seen_at=first_seen,
    )
    ranking = JobRanking(
        job_id=job.id, analysis_id=uuid4(), profile_id=uuid4(),
        profile_version=1, ranking_version="v1",
        ranking_input_hash=str(uuid4()), ranked_as_of=NOW,
        authority=AnalysisAuthority.AUTHORITATIVE, rank_score=score,
    )
    return RankedVacancy(job, ranking, fit, False, False)


def test_tie_break_order_is_score_fit_published_first_seen_then_title() -> None:
    rows = [
        _ranked("Z role", score=89, fit=100),
        _ranked("C role", score=90, fit=79),
        _ranked("B role", score=90, fit=80, published=NOW - timedelta(days=1)),
        _ranked("A role", score=90, fit=80),
    ]
    ordered = sorted(rows, key=RankingService._sort_key)
    assert [item.job.title_raw for item in ordered] == [
        "A role", "B role", "C role", "Z role"
    ]


def test_final_cluster_identifier_breaks_complete_ties_stably() -> None:
    rows = [_ranked("Same role"), _ranked("Same role")]
    ordered_once = sorted(rows, key=RankingService._sort_key)
    ordered_twice = sorted(reversed(rows), key=RankingService._sort_key)
    assert [item.job.id for item in ordered_once] == [
        item.job.id for item in ordered_twice
    ]
