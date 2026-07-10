"""Local evidence-backed application and interview prep packs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db.connection import Database
from app.db.repositories import CandidateProfileRepository
from app.domain.candidate import CandidateEvidenceProfile
from app.domain.enums import DescriptionCompleteness
from app.services.deduplication import DEDUPLICATION_VERSION


PREP_PACK_VERSION = "m19-prep-pack-v1"
REQUIRED_PREP_PACK_SECTIONS = (
    "# Application Prep Pack",
    "## Job Snapshot",
    "## Fit Summary",
    "## Why I Fit",
    "## Gaps / Risks",
    "## Tailored CV Reference",
    "## Cover Letter Draft",
    "## Interview Talking Points",
    "## Questions to Ask Recruiter",
    "## Application Checklist",
    "## Suggested CLI Next Actions",
)


@dataclass(frozen=True)
class PrepPackResult:
    status: str
    job_id: str
    profile_id: str
    authority: str
    cv_artifact_id: str | None
    output_path: str
    warnings: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "status": self.status,
            "job_id": self.job_id,
            "profile_id": self.profile_id,
            "authority": self.authority,
            "cv_artifact_id": self.cv_artifact_id,
            "output_path": self.output_path,
            "warnings": list(self.warnings),
        }


class PrepPackService:
    """Generate local markdown prep packs without network or application writes."""

    def __init__(
        self,
        database: Database,
        *,
        default_output_dir: Path,
        now: Any | None = None,
    ) -> None:
        self.database = database
        self.default_output_dir = default_output_dir
        self.now = now or (lambda: datetime.now(UTC))

    def create_pack(
        self,
        *,
        profile_id: UUID | str,
        job_id: UUID | str,
        cv_artifact_id: UUID | str | None = None,
        output_dir: Path | None = None,
        output_format: str = "markdown",
        force: bool = False,
    ) -> PrepPackResult:
        if output_format != "markdown":
            raise ValueError("prep pack supports only markdown format")
        context = self._context(profile_id, job_id, cv_artifact_id)
        warnings = list(context["warnings"])
        text = self._markdown(context)
        directory = output_dir or self.default_output_dir
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / self._filename(str(job_id))
        if path.exists() and not force:
            raise FileExistsError(f"Prep pack already exists: {path}")
        path.write_text(text + "\n", encoding="utf-8")
        return PrepPackResult(
            status="created",
            job_id=str(job_id),
            profile_id=str(profile_id),
            authority=str(context["authority"]),
            cv_artifact_id=(
                str(context["cv_artifact"]["id"]) if context["cv_artifact"] else None
            ),
            output_path=str(path.resolve(strict=False)),
            warnings=tuple(warnings),
        )

    def preview_command(
        self,
        *,
        profile_id: UUID | str,
        job_id: UUID | str,
        cv_artifact_id: UUID | str | None = None,
    ) -> str:
        command = (
            "python -m app.cli prep pack "
            f"--profile-id {profile_id} --job-id {job_id}"
        )
        if cv_artifact_id:
            command += f" --cv-artifact-id {cv_artifact_id}"
        return command

    def _context(
        self,
        profile_id: UUID | str,
        job_id: UUID | str,
        cv_artifact_id: UUID | str | None,
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
        evidence = CandidateEvidenceProfile.from_candidate_profile(profile)
        analysis_data = self._decode_analysis(dict(analysis)) if analysis else None
        authority = (
            str(analysis_data.get("authority"))
            if analysis_data else "prefilter_only"
        )
        completeness = (
            description["completeness"] if description else DescriptionCompleteness.MISSING.value
        )
        warnings = self._warnings(
            authority=authority,
            completeness=str(completeness),
            description=description,
            analysis=analysis_data,
            cv_artifact=artifact,
        )
        return {
            "profile": profile,
            "evidence": evidence,
            "job": dict(job),
            "description": dict(description) if description else None,
            "cluster_id": cluster["cluster_id"] if cluster else None,
            "analysis": analysis_data,
            "ranking": self._decode_ranking(dict(ranking)) if ranking else None,
            "application": dict(application) if application else None,
            "cv_artifact": artifact,
            "authority": authority,
            "description_completeness": str(completeness),
            "warnings": warnings,
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
        ids = tuple(row["job_id"] for row in rows)
        return ids or (job_id,)

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

    @staticmethod
    def _warnings(
        *,
        authority: str,
        completeness: str,
        description,
        analysis: dict[str, Any] | None,
        cv_artifact: dict[str, Any] | None,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if completeness != DescriptionCompleteness.FULL.value:
            warnings.append(
                "Stored job description is incomplete; open the original vacancy before applying."
            )
        if authority != "authoritative":
            warnings.append(
                "Fit is prefilter-only; do not treat this prep pack as a final fit assessment."
            )
        if description is None or not str(description["raw_text"] or "").strip():
            warnings.append("No usable stored description text is available.")
        if analysis is None:
            warnings.append("No fit analysis is stored for this profile/job yet.")
        if cv_artifact is None:
            warnings.append("No matching CV artifact was found.")
        return tuple(dict.fromkeys(warnings))

    def _markdown(self, context: dict[str, Any]) -> str:
        job = context["job"]
        analysis = context["analysis"]
        ranking = context["ranking"]
        application = context["application"]
        cv_artifact = context["cv_artifact"]
        evidence = context["evidence"]
        lines: list[str] = [
            "# Application Prep Pack",
            "",
            f"_Generated locally by {PREP_PACK_VERSION}. Review before applying._",
            "",
            "## Job Snapshot",
            f"- title: {self._value(job.get('title_raw'))}",
            f"- company: {self._value(job.get('company_raw'))}",
            f"- location: {self._value(job.get('location_raw'))}",
            f"- source: {self._value(job.get('source'))}",
            f"- job_id: {job['id']}",
            f"- cluster_id: {self._value(context['cluster_id'])}",
            f"- authority: {context['authority']}",
            f"- description completeness: {context['description_completeness']}",
            f"- application status: {self._value(application.get('current_status') if application else None)}",
            f"- priority: {self._value(application.get('priority') if application else None)}",
            f"- follow-up date: {self._value(application.get('follow_up_date') if application else None)}",
            "",
            "## Fit Summary",
            f"- rank score: {self._value(ranking.get('rank_score') if ranking else None)}",
            f"- fit score: {self._fit_score(analysis)}",
            f"- prefilter label: {self._prefilter_label(context)}",
        ]
        lines.extend(self._bullets(self._fit_reasons(analysis), fallback="No stored fit reasons yet."))
        lines.extend([
            "",
            "## Why I Fit",
            "Based on stored profile evidence and the deterministic fit analysis:",
        ])
        lines.extend(self._bullets(self._match_points(context), fallback="Add deterministic analysis before using detailed fit claims."))
        lines.extend([
            "",
            "## Gaps / Risks",
        ])
        lines.extend(self._bullets(self._gaps(context), fallback="No specific stored risks were found; still verify the vacancy manually."))
        lines.extend([
            "",
            "## Tailored CV Reference",
        ])
        lines.extend(self._bullets(self._cv_reference(context), fallback="No CV artifact found."))
        lines.extend([
            "",
            "## Cover Letter Draft",
        ])
        lines.extend(self._cover_letter(context))
        lines.extend([
            "",
            "## Interview Talking Points",
        ])
        lines.extend(self._bullets(self._talking_points(context), fallback="Prepare examples after reviewing the full job description."))
        lines.extend([
            "",
            "## Questions to Ask Recruiter",
        ])
        lines.extend(self._bullets(self._recruiter_questions(context)))
        lines.extend([
            "",
            "## Application Checklist",
        ])
        lines.extend(self._bullets((
            "Review the stored job description and open the original vacancy before applying.",
            "Confirm location, work mode, contract type, and language expectations.",
            "Generate or attach a reviewed CV artifact.",
            "Review and edit the cover letter draft manually.",
            "Apply manually outside this system.",
            "Update local application status only after applying.",
            "Set a follow-up date.",
        )))
        lines.extend([
            "",
            "## Suggested CLI Next Actions",
        ])
        lines.extend(self._bullets(self._next_actions(context)))
        if context["warnings"]:
            lines.extend(["", "## Warnings"])
            lines.extend(self._bullets(context["warnings"]))
        return "\n".join(lines)

    @staticmethod
    def _fit_score(analysis: dict[str, Any] | None) -> str:
        if not analysis:
            return "not available"
        if analysis.get("authority") != "authoritative":
            return "not authoritative"
        return str(analysis.get("fit_score") or "not available")

    @staticmethod
    def _prefilter_label(context: dict[str, Any]) -> str:
        analysis = context["analysis"]
        if not analysis:
            return "not available"
        score = analysis.get("prefilter_score")
        if context["authority"] == "prefilter_only":
            return f"prefilter_only ({score})" if score is not None else "prefilter_only"
        return "authoritative full-description analysis"

    @staticmethod
    def _fit_reasons(analysis: dict[str, Any] | None) -> tuple[str, ...]:
        if not analysis:
            return ()
        reasons = tuple(str(item) for item in analysis.get("fit_reasons", ()) if item)
        components = tuple(
            f"{item.get('name')}: {item.get('reason')}"
            for item in analysis.get("positive_components", ())
            if isinstance(item, dict) and item.get("reason")
        )
        return tuple(dict.fromkeys((*reasons, *components)))[:6]

    def _match_points(self, context: dict[str, Any]) -> tuple[str, ...]:
        if context["authority"] != "authoritative":
            return (
                "Based on stored profile evidence, prepare broad examples only until the full vacancy text is reviewed.",
                "Confirm the original job posting before making tailored fit claims.",
            )
        analysis = context["analysis"] or {}
        points = [
            f"Based on stored profile evidence: {item.get('label') or item.get('reason')}"
            for item in analysis.get("evidence", ())
            if isinstance(item, dict)
            and item.get("evidence_type") != "no_evidence"
            and (item.get("label") or item.get("reason"))
        ]
        return tuple(dict.fromkeys(points))[:8]

    def _gaps(self, context: dict[str, Any]) -> tuple[str, ...]:
        analysis = context["analysis"] or {}
        gaps = [
            f"Potential gap: {item}"
            for item in analysis.get("missing_skills", ())
            if item
        ]
        gaps.extend(
            f"Potential risk: {item}"
            for item in analysis.get("risk_flags", ())
            if item
        )
        if context["description_completeness"] != DescriptionCompleteness.FULL.value:
            gaps.append("Potential gap: stored job description is incomplete.")
        return tuple(dict.fromkeys(gaps))[:8]

    def _cv_reference(self, context: dict[str, Any]) -> tuple[str, ...]:
        artifact = context["cv_artifact"]
        if artifact:
            return (
                f"CV artifact: {artifact['id']}",
                f"source: {artifact.get('source')}",
                f"path: {artifact.get('artifact_path')}",
                "Confirm the artifact is reviewed before submitting manually.",
            )
        job_id = context["job"]["id"]
        profile_id = context["profile"].id
        return (
            "No attached or matching CV artifact was found.",
            "Suggested command: "
            f"python -m app.cli cv generate --job-id {job_id} --profile-id {profile_id}",
        )

    def _cover_letter(self, context: dict[str, Any]) -> tuple[str, ...]:
        job = context["job"]
        profile = context["profile"]
        evidence = context["evidence"]
        company = job.get("company_raw") or "[company]"
        title = job.get("title_raw") or "[role]"
        availability = self._profile_fact(
            profile.profile_data,
            ("available", "availability", "immediate"),
        )
        authorization = self._profile_fact(
            profile.profile_data,
            ("authorization", "authorised", "authorized", "blue card", "visa"),
        )
        lines = [
            f"Dear {company} hiring team,",
            "",
            f"I am applying for the {title} role. Based on stored profile evidence, my strongest fit is in {self._compact_list(evidence.skills[:4], fallback='data analysis and reporting')}.",
            f"I can discuss concrete examples from {self._compact_list(tuple(item.label for item in evidence.work_experience[:2]), fallback='my professional experience')} and related project work.",
        ]
        if authorization:
            lines.append(f"Stored profile evidence notes: {authorization}.")
        if availability:
            lines.append(f"Stored profile evidence notes: {availability}.")
        lines.extend([
            "I would welcome the opportunity to discuss the role expectations, data environment, and how my experience maps to the team's needs.",
            "",
            "Kind regards,",
            str(profile.display_name),
        ])
        return tuple(lines)

    def _talking_points(self, context: dict[str, Any]) -> tuple[str, ...]:
        evidence = context["evidence"]
        points = [
            f"Based on stored profile evidence: {item.label} - {item.summary}"
            for item in (*evidence.work_experience, *evidence.projects, *evidence.education_training)
            if item.summary
        ]
        for metric in evidence.verified_metrics:
            points.append(f"Stored verified metric to discuss carefully: {metric}")
        if context["authority"] != "authoritative":
            points.append("For this prefilter-only job, keep examples broad until the full job description is reviewed.")
        for skill in evidence.skills[:5]:
            points.append(
                f"Prepare a concrete example for stored skill evidence: {skill}."
            )
        return tuple(dict.fromkeys(points))[:8]

    @staticmethod
    def _recruiter_questions(context: dict[str, Any]) -> tuple[str, ...]:
        return (
            "What are the top expectations for the first 90 days in this role?",
            "Which tools, databases, and reporting workflows does the team use most?",
            "How is the data environment structured, and who are the main stakeholders?",
            "How is the team organized, and who would this role work with day to day?",
            "What level of German and English is expected in meetings, documentation, and stakeholder work?",
            "What is the expected hybrid setup, location flexibility, and travel requirement?",
        )

    def _next_actions(self, context: dict[str, Any]) -> tuple[str, ...]:
        job_id = context["job"]["id"]
        profile_id = context["profile"].id
        follow_up = (self.now() + timedelta(days=7)).date().isoformat()
        actions = [
            f"Shortlist: python -m app.cli applications shortlist --profile-id {profile_id} --job-id {job_id} --priority high --note \"Prep pack reviewed\"",
            f"Generate CV: python -m app.cli cv generate --job-id {job_id} --profile-id {profile_id}",
        ]
        artifact = context["cv_artifact"]
        if artifact:
            actions.append(
                f"Optional AI polish: python -m app.cli cv polish --artifact-id {artifact['id']} --live-ai"
            )
            actions.append(
                f"Attach CV: python -m app.cli applications cv-ready --profile-id {profile_id} --job-id {job_id} --cv-artifact-id {artifact['id']} --note \"CV reviewed for application\""
            )
        else:
            actions.append("Optional AI polish: run only after generating a rule-based CV artifact and reviewing it.")
        actions.extend([
            f"Set applied: python -m app.cli applications set-status --profile-id {profile_id} --job-id {job_id} --status applied --note \"Applied manually\"",
            f"Set follow-up: python -m app.cli applications follow-up --profile-id {profile_id} --job-id {job_id} --date {follow_up} --note \"Follow up after manual application\"",
            f"View history: python -m app.cli applications history --profile-id {profile_id} --job-id {job_id}",
        ])
        return tuple(actions)

    def _filename(self, job_id: str) -> str:
        timestamp = self.now().strftime("%Y%m%dT%H%M%S%fZ")
        safe_job = re.sub(r"[^A-Za-z0-9-]+", "-", job_id).strip("-")
        return f"prep_{safe_job}_{timestamp}.md"

    @staticmethod
    def _profile_fact(profile_data: dict[str, Any], keywords: tuple[str, ...]) -> str | None:
        for value in _walk_strings(profile_data):
            lower = value.casefold()
            if any(keyword in lower for keyword in keywords):
                return value
        return None

    @staticmethod
    def _bullets(
        values: tuple[str, ...] | list[str],
        *,
        fallback: str | None = None,
    ) -> list[str]:
        items = [str(value).strip() for value in values if str(value).strip()]
        if not items and fallback:
            items = [fallback]
        return [f"- {item}" for item in items]

    @staticmethod
    def _compact_list(values: tuple[str, ...], *, fallback: str) -> str:
        filtered = [value for value in values if value]
        if not filtered:
            return fallback
        return ", ".join(filtered[:4])

    @staticmethod
    def _value(value: Any) -> str:
        return str(value) if value not in (None, "") else "not stored"


def latest_prep_packs(
    directory: Path | str,
    *,
    job_id: UUID | str | None = None,
    limit: int = 10,
) -> tuple[dict[str, object], ...]:
    root = Path(directory)
    if not root.is_dir():
        return ()
    pattern = f"prep_{job_id}_*.md" if job_id else "prep_*.md"
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


def _walk_strings(value: Any):
    if isinstance(value, str):
        text = value.strip()
        if text:
            yield text
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _walk_strings(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            yield from _walk_strings(nested)
