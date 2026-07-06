from __future__ import annotations

from datetime import UTC, datetime

from app.db.connection import Database
from app.services.deduplication import DEDUPLICATION_VERSION, DeduplicationService
from app.services.ranking import RankingService

from tests.integration.test_fit_analysis_persistence import (
    _description,
    _job,
    _profile,
    _rules,
)
from app.domain.enums import DescriptionCompleteness, JobSource


def test_ranking_uses_logical_vacancies_once_and_caches_versions(database: Database) -> None:
    profile = _profile(database)
    aa = _job(database, source=JobSource.ARBEITSAGENTUR, source_id="aa-copy", title="A Data Analyst")
    ej = _job(database, source=JobSource.ENGLISHJOBS, source_id="ej-copy", title="A Data Analyst")
    other = _job(database, source=JobSource.ENGLISHJOBS, source_id="other", title="B Data Analyst")
    for job in (aa, ej, other):
        _description(database, job, "full_data_analyst.txt", DescriptionCompleteness.FULL)
    with database.transaction() as connection:
        connection.execute("UPDATE jobs SET canonical_url = ? WHERE id IN (?, ?)", ("https://employer.example/a", str(aa.id), str(ej.id)))
        connection.execute("UPDATE jobs SET company_raw = 'Other Company', company_normalized = 'other company' WHERE id = ?", (str(other.id),))
        connection.execute(
            "UPDATE jobs SET first_seen_at = ?",
            (datetime(2026, 7, 1, tzinfo=UTC).isoformat(),),
        )
    DeduplicationService(database).backfill()
    as_of = datetime(2026, 7, 6, tzinfo=UTC)
    service = RankingService(database, _rules())

    first = service.rank(profile.id, DEDUPLICATION_VERSION, as_of=as_of)
    repeated = service.rank(profile.id, DEDUPLICATION_VERSION, as_of=as_of)

    assert len(first) == 2
    assert [item.job.title_raw for item in first] == ["A Data Analyst", "B Data Analyst"]
    assert len({item.ranking.cluster_id for item in first}) == 2
    assert all(item.ranking_cache_hit for item in repeated)

    changed_rules = _rules().model_copy(update={"ranking_version": "m5-ranking-v2"})
    changed = RankingService(database, changed_rules).rank(
        profile.id, DEDUPLICATION_VERSION, as_of=as_of
    )
    assert {item.ranking.id for item in changed}.isdisjoint(
        {item.ranking.id for item in first}
    )


def test_prefilter_only_is_excluded_unless_explicitly_requested(database: Database) -> None:
    profile = _profile(database)
    job = _job(database, source_id="snippet", title="Data Analyst")
    _description(database, job, "full_data_analyst.txt", DescriptionCompleteness.SNIPPET)
    DeduplicationService(database).backfill()
    service = RankingService(database, _rules())
    as_of = datetime(2026, 7, 6, tzinfo=UTC)

    assert service.rank(profile.id, DEDUPLICATION_VERSION, as_of=as_of) == []
    included = service.rank(
        profile.id, DEDUPLICATION_VERSION, as_of=as_of,
        include_prefilter_only=True,
    )
    assert len(included) == 1
    assert included[0].ranking.authority.value == "prefilter_only"
