"""Explicit dashboard actions delegating all business rules to core services."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.config import Settings
from app.db.connection import Database
from app.db.repositories import ApplicationRepository, DuplicateRepository
from app.domain.duplicates import ReviewStatus
from app.domain.enums import ApplicationStatus
from app.integrations.ai import build_ai_provider
from app.integrations.telegram import TelegramClient
from app.services.analysis_rules import AnalysisRules
from app.services.application_pack import ApplicationPackService
from app.services.applications import ALLOWED_TRANSITIONS, ApplicationService
from app.services.communications import CommunicationDraftService
from app.services.cv_generation import CVGenerationService
from app.services.deduplication import DEDUPLICATION_VERSION, DeduplicationService
from app.services.fit_analysis import FitAnalysisService
from app.services.notifications import NotificationFormatter, NotificationService
from app.services.prep_pack import PrepPackService
from app.services.ranking import RankingService


class ConfirmationRequired(ValueError):
    pass


class DashboardActions:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self.rules = AnalysisRules.from_json(settings.fit_rules_path)

    def start_tracking(self, job_id: UUID | str, profile_id: UUID | str):
        job_key, profile_key = str(job_id), str(profile_id)
        try:
            return ApplicationService(self.database).track_job(profile_key, job_key)
        except sqlite3.IntegrityError:
            with self.database.read_connection() as connection:
                row = connection.execute(
                    "SELECT id FROM applications WHERE job_id = ? AND profile_id = ?",
                    (job_key, profile_key),
                ).fetchone()
                if row is None:
                    raise
                return ApplicationRepository(connection).get(row["id"]), True

    def allowed_transitions(self, application_id: UUID | str) -> tuple[str, ...]:
        with self.database.read_connection() as connection:
            application = ApplicationRepository(connection).get(application_id)
        if application is None:
            raise KeyError(f"Application not found: {application_id}")
        return tuple(sorted(
            (status.value for status in ALLOWED_TRANSITIONS[application.status])
        ))

    def transition_application(
        self, application_id: UUID | str, status: str, *, reason: str | None = None
    ):
        return ApplicationService(self.database).transition(
            UUID(str(application_id)), ApplicationStatus(status), reason=reason
        )

    def shortlist_application(
        self,
        job_id: UUID | str,
        profile_id: UUID | str,
        *,
        priority: str | None = None,
        note: str | None = None,
    ):
        return ApplicationService(self.database).shortlist_job(
            profile_id, job_id, priority=priority, note=note
        )

    def add_to_review_tray(
        self,
        job_ids: list[UUID | str] | tuple[UUID | str, ...],
        profile_id: UUID | str,
    ) -> list[object]:
        service = ApplicationService(self.database)
        return [
            service.shortlist_job(
                profile_id,
                job_id,
                priority="medium",
                note="Added to review tray from dashboard",
            )
            for job_id in job_ids
        ]

    def set_application_status(
        self,
        job_id: UUID | str,
        profile_id: UUID | str,
        status: str,
        *,
        note: str | None = None,
    ):
        return ApplicationService(self.database).set_status(
            profile_id=profile_id, job_id=job_id, status=status, note=note
        )

    def set_application_follow_up(
        self,
        application_id: UUID | str,
        follow_up_date: str,
        *,
        note: str | None = None,
    ):
        return ApplicationService(self.database).set_follow_up(
            application_id=application_id,
            follow_up_date=follow_up_date,
            note=note,
        )

    def add_application_note(self, application_id: UUID | str, note: str):
        return ApplicationService(self.database).add_note(
            application_id=application_id,
            note=note,
        )

    def attach_cv_artifact(
        self,
        job_id: UUID | str,
        profile_id: UUID | str,
        cv_artifact_id: UUID | str,
        *,
        note: str | None = None,
    ):
        return ApplicationService(self.database).mark_cv_ready(
            profile_id,
            job_id,
            cv_artifact_id=cv_artifact_id,
            note=note,
        )

    def create_prep_pack(
        self,
        job_id: UUID | str,
        profile_id: UUID | str,
        *,
        cv_artifact_id: UUID | str | None = None,
        force: bool = False,
    ):
        return PrepPackService(
            self.database,
            default_output_dir=self.settings.data_dir / "prep_packs",
        ).create_pack(
            profile_id=profile_id,
            job_id=job_id,
            cv_artifact_id=cv_artifact_id,
            output_format="markdown",
            force=force,
        )

    def create_application_pack(
        self,
        job_id: UUID | str,
        profile_id: UUID | str,
        *,
        cv_artifact_id: UUID | str | None = None,
        force: bool = False,
    ):
        return ApplicationPackService(
            self.database,
            default_output_dir=self.settings.data_dir / "application_packs",
            prep_pack_dir=self.settings.data_dir / "prep_packs",
        ).create_pack(
            profile_id=profile_id,
            job_id=job_id,
            cv_artifact_id=cv_artifact_id,
            force=force,
        )

    def create_communication_draft(
        self,
        job_id: UUID | str,
        profile_id: UUID | str,
        *,
        draft_type: str,
        tone: str = "professional",
        force: bool = False,
        record_event: bool = False,
    ):
        return CommunicationDraftService(
            self.database,
            default_output_dir=self.settings.data_dir / "communication_drafts",
            prep_pack_dir=self.settings.data_dir / "prep_packs",
            application_pack_dir=self.settings.data_dir / "application_packs",
        ).create_draft(
            profile_id=profile_id,
            job_id=job_id,
            draft_type=draft_type,
            tone=tone,
            force=force,
            record_event=record_event,
        )

    def submit_manual_application(
        self,
        job_id: UUID | str,
        profile_id: UUID | str,
        *,
        note: str | None = None,
        follow_up_date: str | None = None,
    ):
        service = ApplicationService(self.database)
        application = service.mark_applied(
            profile_id,
            job_id,
            note=note,
        )
        follow_up_date = follow_up_date or (
            datetime.now(UTC).date() + timedelta(days=7)
        ).isoformat()
        if follow_up_date:
            application = service.set_follow_up(
                profile_id=profile_id,
                job_id=job_id,
                follow_up_date=follow_up_date,
                note="Follow-up date set after manual application submission",
            )
        return application

    def review_duplicate(
        self, candidate_id: UUID | str, decision: str, *, confirmed: bool
    ) -> None:
        if not confirmed:
            raise ConfirmationRequired("Duplicate review requires confirmation")
        review_status = ReviewStatus(decision)
        with self.database.read_connection() as connection:
            candidate = DuplicateRepository(connection).get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(f"Duplicate candidate not found: {candidate_id}")
        if candidate.status is not ReviewStatus.PENDING:
            raise ValueError("Duplicate candidate has already been reviewed")
        DeduplicationService(self.database).review_candidate(
            candidate.id, review_status
        )
        return True

    def split_duplicate(
        self, job_id: UUID | str, *, confirmation: str
    ) -> UUID:
        if confirmation.strip() != str(job_id):
            raise ConfirmationRequired("Type the exact job ID to confirm the split")
        return DeduplicationService(self.database).split_job(
            job_id, DEDUPLICATION_VERSION
        )

    def analyze_job(self, job_id: UUID | str, profile_id: UUID | str):
        return FitAnalysisService(self.database, self.rules).analyze_job(
            job_id, profile_id
        )

    def refresh_rankings(self, profile_id: UUID | str):
        return RankingService(self.database, self.rules).rank(
            profile_id, DEDUPLICATION_VERSION, as_of=datetime.now(UTC)
        )

    def generate_cv(
        self,
        job_id: UUID | str,
        profile_id: UUID | str,
        *,
        ai_polish: bool = False,
        live_ai_confirmed: bool = False,
    ):
        provider = self._ai_provider(ai_polish, live_ai_confirmed)
        return CVGenerationService(
            self.database, self.settings, self.rules, provider=provider
        ).generate_for_job(
            job_id, profile_id,
            ai_polish=ai_polish, live_ai=live_ai_confirmed,
        )

    def generate_manual_cv(
        self,
        text: str,
        profile_id: UUID | str,
        *,
        ai_polish: bool = False,
        live_ai_confirmed: bool = False,
    ):
        provider = self._ai_provider(ai_polish, live_ai_confirmed)
        return CVGenerationService(
            self.database, self.settings, self.rules, provider=provider
        ).generate_manual_text(
            text, profile_id,
            ai_polish=ai_polish, live_ai=live_ai_confirmed,
        )

    def notification_preview(
        self, profile_id: UUID | str, *, top_n: int | None = None
    ):
        return self._notifications().preview(
            profile_id=profile_id,
            ranking_version=self.rules.ranking_version,
            duplicate_algorithm_version=DEDUPLICATION_VERSION,
            top_n=top_n or self.settings.telegram_top_n,
            min_rank_score=self.settings.telegram_min_rank_score,
        )

    def notification_batches(self, profile_id: UUID | str | None = None):
        return self._notifications().list_batches(profile_id)

    def notification_batch_details(self, batch_id: UUID | str):
        return self._notifications().batch_details(batch_id)

    def send_notifications(
        self, profile_id: UUID | str, *, confirmation: str
    ):
        self._require_live_telegram(confirmation)
        return self._notifications(live=True).send(
            profile_id=profile_id,
            ranking_version=self.rules.ranking_version,
            duplicate_algorithm_version=DEDUPLICATION_VERSION,
            top_n=self.settings.telegram_top_n,
            min_rank_score=self.settings.telegram_min_rank_score,
        )

    def retry_notifications(self, batch_id: UUID | str, *, confirmation: str):
        self._require_live_telegram(confirmation)
        return self._notifications(live=True).retry(batch_id)

    def _notifications(self, *, live: bool = False) -> NotificationService:
        client = TelegramClient(self.settings) if live else None
        return NotificationService(
            self.database,
            formatter=NotificationFormatter(self.settings.telegram_message_max_chars),
            client=client,
        )

    def _require_live_telegram(self, confirmation: str) -> None:
        if not self.settings.telegram_enabled:
            raise ConfirmationRequired("TELEGRAM_ENABLED must be true")
        if confirmation.strip() != "SEND TELEGRAM":
            raise ConfirmationRequired("Type SEND TELEGRAM to confirm live delivery")

    def _ai_provider(self, requested: bool, confirmed: bool):
        if requested != confirmed:
            raise ConfirmationRequired(
                "AI polish requires both request and live-AI confirmation"
            )
        if not requested:
            return None
        if self.settings.ai_provider == "rule_based":
            return None
        return build_ai_provider(self.settings)
