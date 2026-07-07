from threading import Event, Thread

from app.domain.enums import NotificationBatchStatus
from app.integrations.telegram import TelegramSendResult
from tests.integration.test_notification_delivery import FakeClient, _send, _service
from tests.notification_helpers import seed_ranked_vacancies


class BlockingClient:
    def __init__(self, entered: Event, release: Event):
        self.entered = entered
        self.release = release
        self.messages = []

    def send_message(self, text):
        self.messages.append(text)
        self.entered.set()
        assert self.release.wait(5)
        return TelegramSendResult(True, "blocking-success")


def test_pending_reservation_prevents_concurrent_duplicate_send(database) -> None:
    profile, _ = seed_ranked_vacancies(database, 1)
    entered = Event()
    release = Event()
    first_client = BlockingClient(entered, release)
    result = {}
    thread = Thread(
        target=lambda: result.setdefault("first", _send(_service(database, first_client), profile))
    )
    thread.start()
    assert entered.wait(5)
    second_client = FakeClient([TelegramSendResult(True, "should-not-send")])
    second = _send(_service(database, second_client), profile)
    release.set()
    thread.join(5)

    assert second.batch is None
    assert second_client.messages == []
    assert result["first"].batch.status is NotificationBatchStatus.COMPLETED
