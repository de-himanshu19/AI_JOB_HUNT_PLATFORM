from __future__ import annotations

from app.db.repositories import NotificationRepository
from app.db.repositories import JobRankingRepository
from uuid import uuid4
from app.domain.enums import NotificationBatchStatus, NotificationStatus
from app.integrations.telegram import TelegramSendResult
from app.services.notifications import NotificationFormatter, NotificationService
from app.services.deduplication import DeduplicationService
from tests.notification_helpers import DUPLICATE_VERSION, RANKING_VERSION, seed_ranked_vacancies


class FakeClient:
    def __init__(self, results):
        self.results = list(results)
        self.messages = []

    def send_message(self, text):
        self.messages.append(text)
        return self.results.pop(0)


def _service(database, client, max_chars=4000):
    return NotificationService(
        database, formatter=NotificationFormatter(max_chars), client=client
    )


def _send(service, profile, **updates):
    values = {
        "profile_id": profile.id,
        "ranking_version": RANKING_VERSION,
        "duplicate_algorithm_version": DUPLICATE_VERSION,
    }
    values.update(updates)
    return service.send(**values)


def test_successful_clusters_are_not_resent(database) -> None:
    profile, seeded = seed_ranked_vacancies(database, 3)
    client = FakeClient([TelegramSendResult(True, "message-1")])
    service = _service(database, client)
    first = _send(service, profile)
    second = _send(service, profile)

    assert first.batch.status is NotificationBatchStatus.COMPLETED
    assert first.batch.selected_count == 3
    assert first.batch.chunks_sent == first.batch.chunks_total == 1
    assert second.batch is None
    assert len(client.messages) == 1
    with database.read_connection() as connection:
        items = NotificationRepository(connection).items_for_batch(first.batch.id)
    assert all(item.status is NotificationStatus.SENT for item in items)
    assert len({item.duplicate_cluster_id for item in items}) == 3

    prior_ranking = seeded[0][3]
    with database.transaction() as connection:
        JobRankingRepository(connection).create(prior_ranking.model_copy(update={
            "id": uuid4(), "ranking_version": "m5-ranking-v2",
            "ranking_input_hash": "f" * 64,
        }))
    assert service.preview(
        profile_id=profile.id, ranking_version="m5-ranking-v2",
        duplicate_algorithm_version=DUPLICATE_VERSION,
    ).selected_count == 0

    DeduplicationService(database).clear_version(DUPLICATE_VERSION)
    batch, retained_items, _ = service.batch_details(first.batch.id)
    assert batch.status is NotificationBatchStatus.COMPLETED
    assert len(retained_items) == 3


def test_partial_chunk_failure_is_retryable_without_resending_successes(database) -> None:
    profile, _ = seed_ranked_vacancies(database, 3)
    first_client = FakeClient([
        TelegramSendResult(True, "message-1"),
        TelegramSendResult(False, error_summary="http_status:503"),
    ])
    service = _service(database, first_client, max_chars=500)
    first = _send(service, profile)

    assert first.batch.status is NotificationBatchStatus.PARTIAL
    assert first.batch.chunks_total == 2
    assert first.batch.chunks_sent == 1
    assert [item.status for item in first.deliveries] == [
        NotificationStatus.SENT, NotificationStatus.FAILED
    ]

    retry_client = FakeClient([TelegramSendResult(True, "message-2-retry")])
    retry_service = _service(database, retry_client, max_chars=500)
    retried = retry_service.retry(first.batch.id)
    assert retried.batch.status is NotificationBatchStatus.COMPLETED
    assert len(retried.deliveries) == 1
    assert retried.deliveries[0].attempt_number == 2
    assert retry_client.messages == [first_client.messages[1]]
    with database.read_connection() as connection:
        items = NotificationRepository(connection).items_for_batch(first.batch.id)
        deliveries = NotificationRepository(connection).deliveries_for_batch(first.batch.id)
    assert all(item.status is NotificationStatus.SENT for item in items)
    assert len(deliveries) == 3


def test_all_failed_batch_remains_auditable_and_retryable(database) -> None:
    profile, _ = seed_ranked_vacancies(database, 1)
    service = _service(
        database, FakeClient([TelegramSendResult(False, error_summary="transport:Timeout")])
    )
    failed = _send(service, profile)
    assert failed.batch.status is NotificationBatchStatus.FAILED
    batch, items, deliveries = service.batch_details(failed.batch.id)
    assert batch.status is NotificationBatchStatus.FAILED
    assert items[0].error_summary == "transport:Timeout"
    assert deliveries[0].error_summary == "transport:Timeout"
