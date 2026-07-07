from app.services.notifications import NotificationFormatter, NotificationService
from tests.notification_helpers import DUPLICATE_VERSION, RANKING_VERSION, seed_ranked_vacancies
from app.db.repositories import DuplicateRepository, JobRepository
from app.domain.duplicates import DuplicateMatchMethod, JobDuplicateLink
from app.domain.enums import JobSource
from app.domain.job import Job


def test_selection_is_limited_to_top_20_and_preserves_rank_order(database) -> None:
    profile, seeded = seed_ranked_vacancies(database, 23)
    preview = NotificationService(
        database, formatter=NotificationFormatter()
    ).preview(
        profile_id=profile.id, ranking_version=RANKING_VERSION,
        duplicate_algorithm_version=DUPLICATE_VERSION, top_n=20,
    )
    assert preview.selected_count == 20
    assert [item["ranking_id"] for item in preview.snapshots] == [
        str(item[3].id) for item in seeded[:20]
    ]


def test_minimum_score_and_top_n_are_applied(database) -> None:
    profile, _ = seed_ranked_vacancies(database, 5)
    preview = NotificationService(
        database, formatter=NotificationFormatter()
    ).preview(
        profile_id=profile.id, ranking_version=RANKING_VERSION,
        duplicate_algorithm_version=DUPLICATE_VERSION,
        top_n=2, min_rank_score=97,
    )
    assert preview.selected_count == 2


def test_second_source_row_in_cluster_is_not_selected_separately(database) -> None:
    profile, seeded = seed_ranked_vacancies(database, 1)
    representative, cluster, _, _ = seeded[0]
    copy = Job(
        source=JobSource.ENGLISHJOBS,
        source_job_id="english-copy",
        title_raw=representative.title_raw,
        title_normalized=representative.title_normalized,
        company_raw=representative.company_raw,
        company_normalized=representative.company_normalized,
    )
    with database.transaction() as connection:
        JobRepository(connection).create(copy)
        DuplicateRepository(connection).create_link(JobDuplicateLink(
            job_id=copy.id, cluster_id=cluster.id,
            algorithm_version=DUPLICATE_VERSION,
            match_method=DuplicateMatchMethod.CANONICAL_URL,
            confidence=1, reasons=("fixture source copy",),
        ))
    preview = NotificationService(
        database, formatter=NotificationFormatter()
    ).preview(
        profile_id=profile.id, ranking_version=RANKING_VERSION,
        duplicate_algorithm_version=DUPLICATE_VERSION,
    )
    assert preview.selected_count == 1
