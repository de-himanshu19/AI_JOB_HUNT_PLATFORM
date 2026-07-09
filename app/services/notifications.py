"""Cluster-level Telegram selection, formatting, delivery, and retry."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.db.connection import Database
from app.db.repositories import NotificationRepository
from app.domain.enums import NotificationBatchStatus, NotificationStatus
from app.domain.operations import (
    NotificationBatch,
    NotificationDelivery,
    NotificationItem,
)
from app.integrations.telegram import TelegramClient, TelegramSendResult


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean(value: object, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= maximum:
        return text
    return text[: max(0, maximum - 1)].rstrip() + "…"


@dataclass(frozen=True)
class FormattedChunk:
    index: int
    text: str
    positions: tuple[int, ...]


@dataclass(frozen=True)
class NotificationPreview:
    selected_count: int
    chunks: tuple[FormattedChunk, ...]
    snapshots: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class NotificationExecutionReport:
    batch: NotificationBatch | None
    deliveries: tuple[NotificationDelivery, ...]


class NotificationFormatter:
    HEADER = "AI Job Hunt - Top new matches"

    def __init__(self, max_chars: int = 4000):
        self.max_chars = max_chars

    def chunks(self, snapshots: list[dict[str, Any]]) -> tuple[FormattedChunk, ...]:
        if not snapshots:
            return ()
        chunks: list[FormattedChunk] = []
        blocks: list[str] = []
        positions: list[int] = []
        for snapshot in snapshots:
            block = self._block(snapshot)
            candidate = self.HEADER + "\n\n" + "\n\n".join((*blocks, block))
            if blocks and len(candidate) > self.max_chars:
                text = self.HEADER + "\n\n" + "\n\n".join(blocks)
                chunks.append(FormattedChunk(len(chunks) + 1, text, tuple(positions)))
                blocks = []
                positions = []
            if len(self.HEADER) + 2 + len(block) > self.max_chars:
                block = block[: self.max_chars - len(self.HEADER) - 3].rstrip() + "…"
            blocks.append(block)
            positions.append(int(snapshot["position"]))
        if blocks:
            text = self.HEADER + "\n\n" + "\n\n".join(blocks)
            chunks.append(FormattedChunk(len(chunks) + 1, text, tuple(positions)))
        return tuple(chunks)

    @staticmethod
    def _block(snapshot: dict[str, Any]) -> str:
        location = _clean(snapshot.get("location"), 120) or "Location not listed"
        company = _clean(snapshot.get("company"), 120) or "Company not listed"
        reason = _clean(snapshot.get("reason"), 240) or "See stored analysis for details."
        url = _clean(snapshot.get("url"), 1200)
        fit_score = snapshot.get("fit_score")
        fit_label = (
            f"{float(fit_score):.2f}" if fit_score is not None else "prefilter only"
        )
        lines = [
            f"{snapshot['position']}. {_clean(snapshot.get('title'), 160)}",
            f"{company} | {location}",
            f"Rank: {float(snapshot['rank_score']):.2f} | Fit: {fit_label}",
            reason,
            f"Job ID: {snapshot['job_id']}",
        ]
        if url:
            lines.append(url)
        return "\n".join(lines)


class NotificationService:
    def __init__(
        self,
        database: Database,
        *,
        formatter: NotificationFormatter,
        client: TelegramClient | None = None,
    ):
        self.database = database
        self.formatter = formatter
        self.client = client

    def preview(
        self,
        *,
        profile_id: UUID | str,
        ranking_version: str,
        duplicate_algorithm_version: str,
        top_n: int = 20,
        min_rank_score: float = 0,
    ) -> NotificationPreview:
        top_n = min(20, max(1, top_n))
        with self.database.read_connection() as connection:
            rows = NotificationRepository(connection).eligible_rankings(
                profile_id=profile_id, ranking_version=ranking_version,
                duplicate_algorithm_version=duplicate_algorithm_version,
                min_rank_score=min_rank_score, limit=top_n,
            )
        snapshots = tuple(
            self._snapshot(row, position) for position, row in enumerate(rows, 1)
        )
        return NotificationPreview(
            len(snapshots), self.formatter.chunks(list(snapshots)), snapshots
        )

    def send(
        self,
        *,
        profile_id: UUID | str,
        ranking_version: str,
        duplicate_algorithm_version: str,
        top_n: int = 20,
        min_rank_score: float = 0,
    ) -> NotificationExecutionReport:
        if self.client is None:
            raise ValueError("A Telegram client is required for live delivery")
        batch, chunks = self._reserve(
            profile_id=profile_id, ranking_version=ranking_version,
            duplicate_algorithm_version=duplicate_algorithm_version,
            top_n=top_n, min_rank_score=min_rank_score,
        )
        if batch is None:
            return NotificationExecutionReport(None, ())
        deliveries = tuple(
            self._deliver(batch.id, delivery, chunk.text)
            for delivery, chunk in chunks
        )
        finished = self._finalize_batch(batch.id)
        return NotificationExecutionReport(finished, deliveries)

    def retry(self, batch_id: UUID | str) -> NotificationExecutionReport:
        if self.client is None:
            raise ValueError("A Telegram client is required for live delivery")
        with self.database.read_connection() as connection:
            repository = NotificationRepository(connection)
            batch = repository.get_batch(batch_id)
            if batch is None:
                raise KeyError(f"Notification batch not found: {batch_id}")
            failed = repository.deliveries_for_batch(
                batch.id, status=NotificationStatus.FAILED
            )
            retryable = [
                (delivery, repository.items_for_delivery(delivery.id))
                for delivery in failed
            ]
            retryable = [(delivery, items) for delivery, items in retryable if items]
            all_deliveries = repository.deliveries_for_batch(batch.id)
        new_deliveries = []
        for old, items in retryable:
            snapshots = [dict(item.snapshot) for item in items]
            chunks = self.formatter.chunks(snapshots)
            if len(chunks) != 1:
                raise ValueError("Stored failed chunk no longer formats as one chunk")
            attempt = 1 + max(
                item.attempt_number
                for item in all_deliveries if item.chunk_index == old.chunk_index
            )
            delivery = NotificationDelivery(
                batch_id=batch.id, chunk_index=old.chunk_index,
                attempt_number=attempt, payload_hash=_hash(chunks[0].text),
            )
            with self.database.transaction() as connection:
                repository = NotificationRepository(connection)
                repository.create_delivery(delivery)
                repository.move_failed_items_to_delivery(old.id, delivery.id)
            new_deliveries.append(self._deliver(batch.id, delivery, chunks[0].text))
        finished = self._finalize_batch(batch.id)
        return NotificationExecutionReport(finished, tuple(new_deliveries))

    def batch_details(self, batch_id: UUID | str):
        with self.database.read_connection() as connection:
            repository = NotificationRepository(connection)
            batch = repository.get_batch(batch_id)
            if batch is None:
                raise KeyError(f"Notification batch not found: {batch_id}")
            return (
                batch,
                tuple(repository.items_for_batch(batch.id)),
                tuple(repository.deliveries_for_batch(batch.id)),
            )

    def list_batches(self, profile_id: UUID | str | None = None):
        with self.database.read_connection() as connection:
            return tuple(NotificationRepository(connection).list_batches(profile_id))

    def _reserve(self, **selection):
        selection["top_n"] = min(20, max(1, int(selection["top_n"])))
        last_error = None
        for _ in range(2):
            try:
                with self.database.transaction() as connection:
                    repository = NotificationRepository(connection)
                    rows = repository.eligible_rankings(
                        profile_id=selection["profile_id"],
                        ranking_version=selection["ranking_version"],
                        duplicate_algorithm_version=selection["duplicate_algorithm_version"],
                        min_rank_score=selection["min_rank_score"],
                        limit=selection["top_n"],
                    )
                    if not rows:
                        return None, ()
                    snapshots = [
                        self._snapshot(row, position)
                        for position, row in enumerate(rows, 1)
                    ]
                    chunks = self.formatter.chunks(snapshots)
                    batch = NotificationBatch(
                        profile_id=selection["profile_id"],
                        ranking_version=selection["ranking_version"],
                        duplicate_algorithm_version=selection["duplicate_algorithm_version"],
                        top_n=selection["top_n"],
                        status=NotificationBatchStatus.SENDING,
                        selected_count=len(snapshots), chunks_total=len(chunks),
                    )
                    repository.create_batch(batch)
                    pairs = []
                    by_position = {item["position"]: item for item in snapshots}
                    for chunk in chunks:
                        delivery = NotificationDelivery(
                            batch_id=batch.id, chunk_index=chunk.index,
                            payload_hash=_hash(chunk.text),
                        )
                        repository.create_delivery(delivery)
                        for position in chunk.positions:
                            snapshot = by_position[position]
                            repository.create_item(NotificationItem(
                                batch_id=batch.id, delivery_id=delivery.id,
                                duplicate_cluster_id=snapshot["cluster_id"],
                                duplicate_algorithm_version=selection["duplicate_algorithm_version"],
                                representative_job_id=snapshot["job_id"],
                                ranking_id=snapshot["ranking_id"],
                                profile_id=selection["profile_id"], position=position,
                                idempotency_key=_hash(
                                    f"{snapshot['cluster_id']}|{selection['duplicate_algorithm_version']}|"
                                    f"{selection['profile_id']}|telegram"
                                ),
                                snapshot=snapshot,
                            ))
                        pairs.append((delivery, chunk))
                    return batch, tuple(pairs)
            except sqlite3.IntegrityError as error:
                last_error = error
                continue
        raise last_error

    def _deliver(self, batch_id, delivery, text):
        result: TelegramSendResult = self.client.send_message(text)
        now = datetime.now(UTC)
        status = NotificationStatus.SENT if result.success else NotificationStatus.FAILED
        updated = delivery.model_copy(update={
            "status": status, "remote_message_id": result.remote_message_id,
            "attempted_at": now, "sent_at": now if result.success else None,
            "error_summary": result.error_summary,
        })
        with self.database.transaction() as connection:
            repository = NotificationRepository(connection)
            repository.update_delivery(updated)
            repository.update_items_for_delivery(
                delivery.id, status=status,
                sent_at=now if result.success else None,
                error_summary=result.error_summary,
            )
        return updated

    def _finalize_batch(self, batch_id):
        with self.database.transaction() as connection:
            repository = NotificationRepository(connection)
            batch = repository.get_batch(batch_id)
            deliveries = repository.deliveries_for_batch(batch_id)
            successful_chunks = {item.chunk_index for item in deliveries if item.status is NotificationStatus.SENT}
            failed_items = [item for item in repository.items_for_batch(batch_id) if item.status is NotificationStatus.FAILED]
            if len(successful_chunks) == batch.chunks_total:
                status = NotificationBatchStatus.COMPLETED
            elif successful_chunks:
                status = NotificationBatchStatus.PARTIAL
            elif failed_items:
                status = NotificationBatchStatus.FAILED
            else:
                status = NotificationBatchStatus.SENDING
            updated = batch.model_copy(update={
                "status": status, "chunks_sent": len(successful_chunks),
                "finished_at": datetime.now(UTC) if status is not NotificationBatchStatus.SENDING else None,
            })
            repository.update_batch(updated)
            return updated

    @staticmethod
    def _snapshot(row: dict[str, Any], position: int) -> dict[str, Any]:
        reasons = json.loads(row.get("fit_reasons_json") or "[]")
        location = row.get("location_raw") or ", ".join(
            item for item in (row.get("city"), row.get("region"), row.get("country")) if item
        )
        return {
            "position": position,
            "cluster_id": row["cluster_id"],
            "job_id": row["job_id"],
            "ranking_id": row["id"],
            "title": row["title_raw"],
            "company": row.get("company_raw"),
            "location": location,
            "rank_score": row["rank_score"],
            "fit_score": row["fit_score"],
            "reason": reasons[0] if reasons else "See stored analysis for details.",
            "url": row.get("canonical_url") or row.get("source_url"),
        }
