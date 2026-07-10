"""Local manual-application package generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db.connection import Database
from app.db.repositories import CandidateProfileRepository
from app.domain.candidate import CandidateEvidenceProfile
from app.domain.enums import DescriptionCompleteness
from app.services.deduplication import DEDUPLICATION_VERSION
from app.services.prep_pack import latest_prep_packs


APPLICATION_PACK_VERSION = "m20-application-pack-v1"
REQUIRED_APPLICATION_PACK_FILES = (
    "README_CHECKLIST.md",
    "job_snapshot.md",
    "cover_letter_draft.md",
    "cv_reference.md",
    "submission_notes.md",
    "follow_up_plan.md",
)


@dataclass(frozen=True)
class ApplicationPackResult:
    status: str
    job_id: str
    profile_id: str
    output_path: str
    cv_artifact_id: str | None
    prep_pack_path: str | None
    warnings: tuple[str, ...]
    files: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "status": self.status,
            "job_id": self.job_id,
            "profile_id": self.profile_id,
            "output_path": self.output_path,
            "cv_artifact_id": self.cv_artifact_id,
            "prep_pack_path": self.prep_pack_path,
            "warnings": list(self.warnings),
            "files": list(self.files),
        }


class ApplicationPackService:
    """Create local-only application package folders for manual submission."""

    def __init__(
        self,
        database: Database,
        *,
        default_output_dir: Path,
        prep_pack_dir: Path,
        now: Any | None = None,
    ) -> None:
        self.database = database
        self.default_output_dir = default_output_dir
        self.prep_pack_dir = prep_pack_dir
        self.now = now or (lambda: datetime.now(UTC))

    def create_pack(
        self,
        *,
        profile_id: UUID | str,
        job_id: UUID | str,
        cv_artifact_id: UUID | str | None = None,
        prep_pack_path: Path | None = None,
        output_dir: Path | None = None,
        include_cv_text: bool = False,
        force: bool = False,
    ) -> ApplicationPackResult:
        context = self._context(profile_id, job_id, cv_artifact_id, prep_pack_path)
        warnings = list(context["warnings"])
        directory = output_dir or self.default_output_dir
        directory.mkdir(parents=True, exist_ok=True)
        folder = directory / self._folder_name(context)
        if folder.exists() and not force:
            raise FileExistsError(f"Application pack already exists: {folder}")
        folder.mkdir(parents=True, exist_ok=True)
        files = self._write_files(folder, context)
        if include_cv_text:
            copied = self._write_cv_text(folder, context, warnings)
            if copied:
                files.append(copied)
        result = ApplicationPackResult(
            status="created",
            job_id=str(job_id),
            profile_id=str(profile_id),
            output_path=str(folder.resolve(strict=False)),
            cv_artifact_id=(
                str(context["cv_artifact"]["id"]) if context["cv_artifact"] else None
            ),
            prep_pack_path=(
                str(context["prep_pack_path"].resolve(strict=False))
                if context["prep_pack_path"] else None
            ),
            warnings=tuple(dict.fromkeys(warnings)),
            files=tuple(files),
        )
        return result

    def preview_command(
        self,
        *,
        profile_id: UUID | str,
        job_id: UUID | str,
        cv_artifact_id: UUID | str | None = None,
    ) -> str:
        command = (
            "python -m app.cli application-pack create "
            f"--profile-id {profile_id} --job-id {job_id}"
        )
        if cv_artifact_id:
            command += f" --cv-artifact-id {cv_artifact_id}"
        return command

    def submit_manual_command(
        self,
        *,
        profile_id: UUID | str,
        job_id: UUID | str,
        follow_up_date: date | str | None = None,
    ) -> str:
        command = (
            "python -m app.cli applications submit-manual "
            f"--profile-id {profile_id} --job-id {job_id} "
            '--note "Applied manually via company website"'
        )
        if follow_up_date:
            command += f" --follow-up-date {follow_up_date}"
        return command

    def _context(
        self,
        profile_id: UUID | str,
        job_id: UUID | str,
        cv_artifact_id: UUID | str | None,
        prep_pack_path: Path | None,
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
            description = connection.execute(
                """SELECT * FROM job_descriptions WHERE job_id = ?
                ORDER BY fetched_at DESC, created_at DESC, id DESC LIMIT 1""",
                (job_key,),
            ).fetchone()
            cluster = connection.execute(
                """SELECT l.cluster_id, c.representative_job_id
                FROM job_duplicate_links l
                JOIN duplicate_clusters c ON c.id = l.cluster_id
                WHERE l.job_id = ? AND l.algorithm_version = ?
                ORDER BY l.created_at DESC, l.id DESC LIMIT 1""",
                (job_key, DEDUPLICATION_VERSION),
            ).fetchone()
            member_ids = self._cluster_member_ids(connection, job_key, cluster)
            placeholders = ",".join("?" for _ in member_ids)
            analysis = connection.execute(
                f"""SELECT * FROM job_analyses
                WHERE job_id IN ({placeholders}) AND profile_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1""",
                (*member_ids, profile_key),
            ).fetchone()
            ranking = connection.execute(
                f"""SELECT * FROM job_rankings
                WHERE job_id IN ({placeholders}) AND profile_id = ?
                ORDER BY ranked_as_of DESC, created_at DESC, id DESC LIMIT 1""",
                (*member_ids, profile_key),
            ).fetchone()
            application = connection.execute(
                f"""SELECT * FROM applications
                WHERE job_id IN ({placeholders}) AND profile_id = ?
                ORDER BY updated_at DESC, id DESC LIMIT 1""",
                (*member_ids, profile_key),
            ).fetchone()
            artifact = self._resolve_cv_artifact(
                connection,
                profile_key=profile_key,
                member_ids=member_ids,
                cluster_id=cluster["cluster_id"] if cluster else None,
                explicit_artifact_id=str(cv_artifact_id) if cv_artifact_id else None,
                attached_artifact_id=(
                    application["cv_artifact_id"]
                    if application and application["cv_artifact_id"] else None
                ),
            )
        selected_prep = self._resolve_prep_pack(job_key, prep_pack_path)
        analysis_data = self._decode_analysis(dict(analysis)) if analysis else None
        completeness = (
            description["completeness"] if description else DescriptionCompleteness.MISSING.value
        )
        warnings = []
        if selected_prep is None:
            warnings.append("No prep pack found; generated conservative cover letter draft.")
        if artifact is None:
            warnings.append("No CV artifact found; package references CV generation command.")
        if completeness != DescriptionCompleteness.FULL.value:
            warnings.append("Stored job description is incomplete; verify original posting before applying.")
        return {
            "profile": profile,
            "evidence": CandidateEvidenceProfile.from_candidate_profile(profile),
            "job": dict(job),
            "description": dict(description) if description else None,
            "cluster_id": cluster["cluster_id"] if cluster else None,
            "analysis": analysis_data,
            "ranking": self._decode_ranking(dict(ranking)) if ranking else None,
            "application": dict(application) if application else None,
            "cv_artifact": artifact,
            "prep_pack_path": selected_prep,
            "cover_letter": self._cover_letter(selected_prep, profile, dict(job), CandidateEvidenceProfile.from_candidate_profile(profile)),
            "description_completeness": str(completeness),
            "authority": str(analysis_data.get("authority")) if analysis_data else "prefilter_only",
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
    def _resolve_cv_artifact(
        connection,
        *,
        profile_key: str,
        member_ids: tuple[str, ...],
        cluster_id: str | None,
        explicit_artifact_id: str | None,
        attached_artifact_id: str | None,
    ) -> dict[str, Any] | None:
        if explicit_artifact_id:
            row = connection.execute(
                """SELECT * FROM cv_generation_artifacts
                WHERE id = ? AND profile_id = ?""",
                (explicit_artifact_id, profile_key),
            ).fetchone()
            if row is None:
                raise KeyError(f"CV artifact not found for profile: {explicit_artifact_id}")
            return dict(row)
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

    def _resolve_prep_pack(self, job_id: str, path: Path | None) -> Path | None:
        if path:
            resolved = path.expanduser().resolve(strict=False)
            if not resolved.is_file():
                raise FileNotFoundError(f"Prep pack not found: {resolved}")
            return resolved
        rows = latest_prep_packs(self.prep_pack_dir, job_id=job_id, limit=1)
        return Path(rows[0]["path"]) if rows else None

    @staticmethod
    def _decode_analysis(value: dict[str, Any]) -> dict[str, Any]:
        for source, target in (
            ("requirements_json", "requirements"),
            ("evidence_json", "evidence"),
            ("missing_skills_json", "missing_skills"),
            ("risk_flags_json", "risk_flags"),
            ("fit_reasons_json", "fit_reasons"),
            ("positive_components_json", "positive_components"),
            ("penalties_json", "penalties"),
            ("score_caps_json", "score_caps"),
        ):
            value[target] = json.loads(value.pop(source))
        return value

    @staticmethod
    def _decode_ranking(value: dict[str, Any]) -> dict[str, Any]:
        value["components"] = json.loads(value.pop("components_json"))
        return value

    def _write_files(self, folder: Path, context: dict[str, Any]) -> list[str]:
        payloads = {
            "README_CHECKLIST.md": self._checklist(context),
            "job_snapshot.md": self._job_snapshot(context),
            "cover_letter_draft.md": self._cover_letter_file(context),
            "cv_reference.md": self._cv_reference(context),
            "submission_notes.md": self._submission_notes(),
            "follow_up_plan.md": self._follow_up_plan(context),
        }
        for name, text in payloads.items():
            (folder / name).write_text(text + "\n", encoding="utf-8")
        return list(payloads)

    @staticmethod
    def _write_cv_text(
        folder: Path,
        context: dict[str, Any],
        warnings: list[str],
    ) -> str | None:
        artifact = context["cv_artifact"]
        if not artifact:
            warnings.append("CV text was requested but no CV artifact was found.")
            return None
        path = Path(str(artifact.get("artifact_path") or ""))
        if not path.is_file():
            warnings.append("CV text was requested but the local artifact file is missing.")
            return None
        text = path.read_text(encoding="utf-8")
        name = "cv_text.md"
        (folder / name).write_text(text + "\n", encoding="utf-8")
        return name

    def _checklist(self, context: dict[str, Any]) -> str:
        return "\n".join((
            "# Manual Application Checklist",
            "",
            f"_Generated locally by {APPLICATION_PACK_VERSION}. Nothing has been submitted._",
            "",
            "- [ ] Open original job posting.",
            "- [ ] Confirm role is still active.",
            "- [ ] Confirm location, work mode, and language requirement.",
            "- [ ] Review CV.",
            "- [ ] Review cover letter draft.",
            "- [ ] Manually apply on the company or job portal.",
            "- [ ] Save confirmation/reference number if available.",
            "- [ ] Run the command to mark as applied.",
            "- [ ] Set follow-up date.",
            "- [ ] Update notes after recruiter response.",
            "",
            "## Commands",
            "",
            f"- Mark applied: `{self.submit_manual_command(profile_id=context['profile'].id, job_id=context['job']['id'])}`",
            f"- View history: `python -m app.cli applications history --profile-id {context['profile'].id} --job-id {context['job']['id']}`",
        ))

    def _job_snapshot(self, context: dict[str, Any]) -> str:
        job = context["job"]
        application = context["application"] or {}
        ranking = context["ranking"] or {}
        return "\n".join((
            "# Job Snapshot",
            "",
            f"- title: {self._value(job.get('title_raw'))}",
            f"- company: {self._value(job.get('company_raw'))}",
            f"- location: {self._value(job.get('location_raw'))}",
            f"- source: {self._value(job.get('source'))}",
            f"- job_id: {job['id']}",
            f"- cluster_id: {self._value(context.get('cluster_id'))}",
            f"- authority: {context['authority']}",
            f"- rank_score: {self._value(ranking.get('rank_score'))}",
            f"- description completeness: {context['description_completeness']}",
            f"- current application status: {self._value(application.get('current_status'))}",
            f"- priority: {self._value(application.get('priority'))}",
            f"- follow-up date: {self._value(application.get('follow_up_date'))}",
            f"- source URL/reference: {self._value(job.get('canonical_url') or job.get('source_url') or job.get('source_job_id'))}",
        ))

    def _cover_letter_file(self, context: dict[str, Any]) -> str:
        warning = (
            "> Warning: Review and edit this draft before sending. It is not "
            "submitted anywhere by this system."
        )
        return "\n".join((
            "# Cover Letter Draft",
            "",
            warning,
            "",
            context["cover_letter"],
        ))

    def _cv_reference(self, context: dict[str, Any]) -> str:
        artifact = context["cv_artifact"]
        job_id = context["job"]["id"]
        profile_id = context["profile"].id
        lines = ["# CV Reference", ""]
        if artifact:
            lines.extend([
                f"- selected CV artifact ID: {artifact['id']}",
                f"- source: {artifact.get('source')}",
                f"- artifact path: {artifact.get('artifact_path')}",
                f"- evidence report path: {artifact.get('evidence_report_path')}",
                f"- validated: {artifact.get('validated')}",
            ])
            lines.append(
                f"- safe AI polish command: python -m app.cli cv polish --artifact-id {artifact['id']} --live-ai"
            )
        else:
            lines.extend([
                "- warning: no CV artifact was found.",
                f"- generate CV: python -m app.cli cv generate --job-id {job_id} --profile-id {profile_id}",
                "- safe AI polish: generate and review a rule-based CV artifact first.",
            ])
        lines.append("- CV text is not copied into this package unless `--include-cv-text` is used.")
        return "\n".join(lines)

    @staticmethod
    def _submission_notes() -> str:
        return "\n".join((
            "# Submission Notes",
            "",
            "- application portal used:",
            "- application URL:",
            "- submitted date:",
            "- confirmation/reference number:",
            "- recruiter/contact:",
            "- documents submitted:",
            "- notes:",
        ))

    def _follow_up_plan(self, context: dict[str, Any]) -> str:
        profile_id = context["profile"].id
        job_id = context["job"]["id"]
        suggested = (self.now().date() + timedelta(days=7)).isoformat()
        return "\n".join((
            "# Follow-Up Plan",
            "",
            f"- suggested follow-up date: {suggested} or 7 days after the actual applied date.",
            "",
            "## Follow-Up Message Draft",
            "",
            "Hello, I wanted to follow up on my manual application for this role. "
            "I remain interested and would be happy to provide any additional information.",
            "",
            "## CLI Commands",
            "",
            f"- set follow-up: python -m app.cli applications follow-up --profile-id {profile_id} --job-id {job_id} --date {suggested} --note \"Follow up after manual application\"",
            f"- view history: python -m app.cli applications history --profile-id {profile_id} --job-id {job_id}",
        ))

    def _cover_letter(
        self,
        prep_pack_path: Path | None,
        profile,
        job: dict[str, Any],
        evidence: CandidateEvidenceProfile,
    ) -> str:
        if prep_pack_path:
            text = prep_pack_path.read_text(encoding="utf-8")
            extracted = _extract_section(text, "## Cover Letter Draft")
            if extracted:
                return extracted
        company = job.get("company_raw") or "[company]"
        title = job.get("title_raw") or "[role]"
        skills = ", ".join(evidence.skills[:4]) or "data analysis and reporting"
        examples = ", ".join(item.label for item in evidence.work_experience[:2]) or "my professional experience"
        return "\n".join((
            f"Dear {company} hiring team,",
            "",
            f"I am applying for the {title} role. Based on stored profile evidence, my relevant strengths include {skills}.",
            f"I can discuss concrete examples from {examples} and related project work.",
            "Please treat this as a draft to review against the original vacancy before sending.",
            "",
            "Kind regards,",
            str(profile.display_name),
        ))

    def _folder_name(self, context: dict[str, Any]) -> str:
        job = context["job"]
        date_part = self.now().strftime("%Y%m%d")
        company = _slug(str(job.get("company_raw") or "company"))
        title = _slug(str(job.get("title_raw") or "role"))
        short_id = str(job["id"]).split("-")[0]
        return f"{date_part}_{company}_{title}_{short_id}"[:120]

    @staticmethod
    def _value(value: Any) -> str:
        return str(value) if value not in (None, "") else "not stored"


def latest_application_packs(
    directory: Path | str,
    *,
    job_id: UUID | str | None = None,
    limit: int = 10,
) -> tuple[dict[str, object], ...]:
    root = Path(directory)
    if not root.is_dir():
        return ()
    rows = []
    marker = str(job_id).split("-")[0] if job_id else None
    for path in sorted(
        (item for item in root.iterdir() if item.is_dir()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        if marker and marker not in path.name:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append({
            "name": path.name,
            "path": str(path),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        })
        if len(rows) >= limit:
            break
    return tuple(rows)


def _extract_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    capture = False
    results: list[str] = []
    for line in lines:
        if line.strip() == heading:
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture:
            results.append(line)
    return "\n".join(results).strip()


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return normalized or "item"
