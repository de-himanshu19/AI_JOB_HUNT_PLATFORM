"""Safe local communication draft generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db.connection import Database
from app.db.repositories import CandidateProfileRepository
from app.domain.candidate import CandidateEvidenceProfile
from app.services.application_pack import latest_application_packs
from app.services.applications import ApplicationService
from app.services.deduplication import DEDUPLICATION_VERSION
from app.services.prep_pack import latest_prep_packs


COMMUNICATION_DRAFT_VERSION = "m21-communication-draft-v1"
SUPPORTED_DRAFT_TYPES = (
    "follow_up",
    "recruiter_reply",
    "interview_availability",
    "interview_thank_you",
    "rejection_response",
    "status_update",
)
PLACEHOLDERS = {
    "recruiter": "[Recruiter Name]",
    "application_date": "[Application Date]",
    "interview_date": "[Interview Date]",
    "reference": "[Portal/Reference Number]",
}


@dataclass(frozen=True)
class CommunicationDraftResult:
    status: str
    draft_type: str
    job_id: str
    profile_id: str
    output_path: str
    warnings: tuple[str, ...]
    event_recorded: bool = False

    def as_json(self) -> dict[str, object]:
        return {
            "status": self.status,
            "draft_type": self.draft_type,
            "job_id": self.job_id,
            "profile_id": self.profile_id,
            "output_path": self.output_path,
            "warnings": list(self.warnings),
            "event_recorded": self.event_recorded,
        }


class CommunicationDraftService:
    """Generate local drafts without sending, network, or status mutation."""

    def __init__(
        self,
        database: Database,
        *,
        default_output_dir: Path,
        prep_pack_dir: Path,
        application_pack_dir: Path,
        now: Any | None = None,
    ) -> None:
        self.database = database
        self.default_output_dir = default_output_dir
        self.prep_pack_dir = prep_pack_dir
        self.application_pack_dir = application_pack_dir
        self.now = now or (lambda: datetime.now(UTC))

    def create_draft(
        self,
        *,
        profile_id: UUID | str,
        job_id: UUID | str,
        draft_type: str,
        output_dir: Path | None = None,
        tone: str = "professional",
        force: bool = False,
        record_event: bool = False,
    ) -> CommunicationDraftResult:
        if draft_type not in SUPPORTED_DRAFT_TYPES:
            raise ValueError(f"Unsupported draft type: {draft_type}")
        if tone != "professional":
            raise ValueError("communications draft currently supports professional tone")
        context = self._context(profile_id, job_id)
        text = self._markdown(context, draft_type, tone)
        directory = output_dir or self.default_output_dir
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self._filename(draft_type, str(job_id))
        if path.exists() and not force:
            raise FileExistsError(f"Communication draft already exists: {path}")
        path.write_text(text + "\n", encoding="utf-8")
        event_recorded = False
        if record_event:
            ApplicationService(self.database).add_note(
                profile_id=profile_id,
                job_id=job_id,
                note=f"Communication draft generated: {draft_type} ({path.name})",
            )
            event_recorded = True
        return CommunicationDraftResult(
            status="created",
            draft_type=draft_type,
            job_id=str(job_id),
            profile_id=str(profile_id),
            output_path=str(path.resolve(strict=False)),
            warnings=tuple(context["warnings"]),
            event_recorded=event_recorded,
        )

    def preview_command(
        self,
        *,
        profile_id: UUID | str,
        job_id: UUID | str,
        draft_type: str,
    ) -> str:
        return (
            "python -m app.cli communications draft "
            f"--profile-id {profile_id} --job-id {job_id} --type {draft_type}"
        )

    def _context(
        self,
        profile_id: UUID | str,
        job_id: UUID | str,
    ) -> dict[str, Any]:
        profile_key = str(profile_id)
        job_key = str(job_id)
        with self.database.read_connection() as connection:
            profile = CandidateProfileRepository(connection).get(profile_key)
            if profile is None:
                raise KeyError(f"Candidate profile not found: {profile_id}")
            job = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_key,)
            ).fetchone()
            if job is None:
                raise KeyError(f"Job not found: {job_id}")
            cluster = connection.execute(
                """SELECT l.cluster_id
                FROM job_duplicate_links l
                WHERE l.job_id = ? AND l.algorithm_version = ?
                ORDER BY l.created_at DESC, l.id DESC LIMIT 1""",
                (job_key, DEDUPLICATION_VERSION),
            ).fetchone()
            member_ids = self._cluster_member_ids(connection, job_key, cluster)
            placeholders = ",".join("?" for _ in member_ids)
            application = connection.execute(
                f"""SELECT * FROM applications
                WHERE job_id IN ({placeholders}) AND profile_id = ?
                ORDER BY updated_at DESC, id DESC LIMIT 1""",
                (*member_ids, profile_key),
            ).fetchone()
            artifact = self._latest_cv_artifact(
                connection,
                profile_key=profile_key,
                member_ids=member_ids,
                cluster_id=cluster["cluster_id"] if cluster else None,
                attached_artifact_id=(
                    application["cv_artifact_id"]
                    if application and application["cv_artifact_id"] else None
                ),
            )
            history = ()
            if application:
                history = connection.execute(
                    """SELECT event_type, note, reason, created_at
                    FROM application_events
                    WHERE application_id = ?
                    ORDER BY created_at DESC, id DESC LIMIT 5""",
                    (application["id"],),
                ).fetchall()
        warnings = []
        if not application:
            warnings.append("No application tracking record exists yet.")
        if not artifact:
            warnings.append("No CV artifact reference was found.")
        prep = latest_prep_packs(self.prep_pack_dir, job_id=job_key, limit=1)
        application_pack = latest_application_packs(
            self.application_pack_dir, job_id=job_key, limit=1
        )
        return {
            "profile": profile,
            "evidence": CandidateEvidenceProfile.from_candidate_profile(profile),
            "job": dict(job),
            "cluster_id": cluster["cluster_id"] if cluster else None,
            "application": dict(application) if application else None,
            "cv_artifact": artifact,
            "history": tuple(dict(row) for row in history),
            "prep_pack": prep[0] if prep else None,
            "application_pack": application_pack[0] if application_pack else None,
            "warnings": tuple(warnings),
        }

    @staticmethod
    def _cluster_member_ids(connection, job_id: str, cluster) -> tuple[str, ...]:
        if not cluster:
            return (job_id,)
        rows = connection.execute(
            """SELECT job_id FROM job_duplicate_links
            WHERE cluster_id = ? AND algorithm_version = ?
            ORDER BY job_id""",
            (cluster["cluster_id"], DEDUPLICATION_VERSION),
        ).fetchall()
        return tuple(row["job_id"] for row in rows) or (job_id,)

    @staticmethod
    def _latest_cv_artifact(
        connection,
        *,
        profile_key: str,
        member_ids: tuple[str, ...],
        cluster_id: str | None,
        attached_artifact_id: str | None,
    ) -> dict[str, Any] | None:
        if attached_artifact_id:
            row = connection.execute(
                """SELECT * FROM cv_generation_artifacts
                WHERE id = ? AND profile_id = ?""",
                (attached_artifact_id, profile_key),
            ).fetchone()
            if row:
                return dict(row)
        placeholders = ",".join("?" for _ in member_ids)
        params: list[Any] = [profile_key, *member_ids]
        cluster_clause = ""
        if cluster_id:
            cluster_clause = " OR logical_cluster_id = ?"
            params.append(cluster_id)
        row = connection.execute(
            f"""SELECT * FROM cv_generation_artifacts
            WHERE profile_id = ?
              AND (job_id IN ({placeholders}){cluster_clause})
            ORDER BY created_at DESC, id DESC LIMIT 1""",
            params,
        ).fetchone()
        return dict(row) if row else None

    def _markdown(self, context: dict[str, Any], draft_type: str, tone: str) -> str:
        job = context["job"]
        application = context["application"] or {}
        lines = [
            f"# Communication Draft: {draft_type.replace('_', ' ').title()}",
            "",
            f"_Generated locally by {COMMUNICATION_DRAFT_VERSION}. Nothing has been sent._",
            "",
            "## Context",
            f"- tone: {tone}",
            f"- title: {self._value(job.get('title_raw'))}",
            f"- company: {self._value(job.get('company_raw'))}",
            f"- job_id: {job['id']}",
            f"- application status: {self._value(application.get('current_status'))}",
            f"- follow-up date: {self._value(application.get('follow_up_date'))}",
            f"- CV artifact: {self._value((context['cv_artifact'] or {}).get('id'))}",
            f"- prep pack: {self._value((context['prep_pack'] or {}).get('path'))}",
            f"- application pack: {self._value((context['application_pack'] or {}).get('path'))}",
            "",
            "## Draft",
            "",
            self._draft_body(context, draft_type),
            "",
            "## Evidence Notes",
        ]
        lines.extend(self._evidence_notes(context))
        if context["warnings"]:
            lines.extend(["", "## Warnings"])
            lines.extend(f"- {warning}" for warning in context["warnings"])
        lines.extend([
            "",
            "## Review Checklist",
            "- Replace placeholders manually before sending.",
            "- Confirm dates, names, channel, and reference numbers.",
            "- Do not send from this system; copy text manually if appropriate.",
        ])
        return "\n".join(lines)

    def _draft_body(self, context: dict[str, Any], draft_type: str) -> str:
        job = context["job"]
        title = self._value(job.get("title_raw"))
        company = self._value(job.get("company_raw"))
        if draft_type == "follow_up":
            return (
                f"Hello {PLACEHOLDERS['recruiter']},\n\n"
                f"I hope you are well. I wanted to follow up on my application for the {title} role at {company}, submitted on {PLACEHOLDERS['application_date']}.\n\n"
                "I remain interested in the opportunity and would appreciate any update you can share on the process or next steps.\n\n"
                "Kind regards,\n"
                f"{context['profile'].display_name}"
            )
        if draft_type == "recruiter_reply":
            return (
                f"Hello {PLACEHOLDERS['recruiter']},\n\n"
                f"Thank you for reaching out regarding the {title} role at {company}. I am interested in learning more.\n\n"
                "Could you please share the next steps, role expectations, and any details about the team, location, and interview process?\n\n"
                "Kind regards,\n"
                f"{context['profile'].display_name}"
            )
        if draft_type == "interview_availability":
            return (
                f"Hello {PLACEHOLDERS['recruiter']},\n\n"
                f"Thank you for the invitation to interview for the {title} role at {company}.\n\n"
                "I am available at the following times, subject to confirmation:\n"
                "- [Availability Slot 1]\n"
                "- [Availability Slot 2]\n"
                "- [Availability Slot 3]\n\n"
                "Please confirm the timezone, interview format, and attendees.\n\n"
                "Kind regards,\n"
                f"{context['profile'].display_name}"
            )
        if draft_type == "interview_thank_you":
            return (
                f"Hello {PLACEHOLDERS['recruiter']},\n\n"
                f"Thank you for taking the time to discuss the {title} role at {company} on {PLACEHOLDERS['interview_date']}.\n\n"
                "I appreciated learning more about the role and remain interested in the opportunity. Please let me know if I can provide any additional information.\n\n"
                "Kind regards,\n"
                f"{context['profile'].display_name}"
            )
        if draft_type == "rejection_response":
            return (
                f"Hello {PLACEHOLDERS['recruiter']},\n\n"
                f"Thank you for letting me know about the decision regarding the {title} role at {company}.\n\n"
                "I appreciate the opportunity to have been considered. If possible, I would be grateful for any brief feedback, and I would be happy to stay in touch for future suitable roles.\n\n"
                "Kind regards,\n"
                f"{context['profile'].display_name}"
            )
        if draft_type == "status_update":
            return (
                "Internal status update note:\n\n"
                f"- Role: {title} at {company}\n"
                f"- Current status: {self._value((context['application'] or {}).get('current_status'))}\n"
                f"- Date: [Status Update Date]\n"
                f"- Portal/reference: {PLACEHOLDERS['reference']}\n"
                "- What changed:\n"
                "- Next action:\n"
                "- Follow-up date:"
            )
        raise ValueError(f"Unsupported draft type: {draft_type}")

    @staticmethod
    def _evidence_notes(context: dict[str, Any]) -> list[str]:
        evidence = context["evidence"]
        notes = [
            "- Use stored profile evidence only; avoid adding recruiter names or dates unless confirmed.",
        ]
        if evidence.skills:
            notes.append("- Stored skills to reference carefully: " + ", ".join(evidence.skills[:5]))
        if evidence.work_experience:
            labels = ", ".join(item.label for item in evidence.work_experience[:3])
            notes.append(f"- Stored experience evidence available: {labels}")
        if context["history"]:
            latest = context["history"][0]
            note = latest.get("note") or latest.get("reason") or latest.get("event_type")
            notes.append(f"- Latest application history note: {note}")
        return notes

    def _filename(self, draft_type: str, job_id: str) -> str:
        timestamp = self.now().strftime("%Y%m%dT%H%M%S%fZ")
        safe_job = re.sub(r"[^A-Za-z0-9-]+", "-", job_id).strip("-")
        return f"communication_{draft_type}_{safe_job}_{timestamp}.md"

    @staticmethod
    def _value(value: Any) -> str:
        return str(value) if value not in (None, "") else "not stored"


def latest_communication_drafts(
    directory: Path | str,
    *,
    job_id: UUID | str | None = None,
    limit: int = 10,
) -> tuple[dict[str, object], ...]:
    root = Path(directory)
    if not root.is_dir():
        return ()
    pattern = f"communication_*_{job_id}_*.md" if job_id else "communication_*.md"
    rows = []
    for path in sorted(root.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append({
            "name": path.name,
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        })
        if len(rows) >= limit:
            break
    return tuple(rows)
