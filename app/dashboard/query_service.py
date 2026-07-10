"""Read-only composite queries for the dashboard.

Streamlit pages never contain SQL. This service returns bounded metadata views
and loads full job descriptions only for an explicitly selected detail page.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from app.db.connection import Database
from app.db.repositories import CandidateProfileRepository
from app.services.analytics import ApplicationAnalyticsService
from app.services.application_pack import (
    ApplicationPackService,
    latest_application_packs,
)
from app.services.communications import (
    SUPPORTED_DRAFT_TYPES,
    CommunicationDraftService,
    latest_communication_drafts,
)
from app.services.cv_generation import CV_BUILDER_CONTENT_VERSION
from app.services.deduplication import DEDUPLICATION_VERSION
from app.services.prep_pack import PrepPackService, latest_prep_packs
from app.dashboard.view_models import (
    DuplicateReviewView,
    JobDetailView,
    JobFilters,
    JobListItem,
    OverviewView,
    PageResult,
    ProfileSummary,
)


SORT_COLUMNS = {
    "rank_score": "rank_score",
    "fit_score": "fit_score",
    "published_at": "j.published_at",
    "last_seen_at": "j.last_seen_at",
    "title": "j.title_normalized",
    "company": "j.company_normalized",
}


class DashboardQueryService:
    def __init__(self, database: Database):
        self.database = database

    def profiles(self) -> tuple[ProfileSummary, ...]:
        with self.database.read_connection() as connection:
            profiles = CandidateProfileRepository(connection).list_all()
        return tuple(ProfileSummary(
            id=str(item.id), profile_key=item.profile_key, version=item.version,
            display_name=item.display_name, active=item.active,
            content_hash=item.content_hash,
        ) for item in profiles)

    def profile_detail(self, profile_id: UUID | str) -> dict[str, object]:
        with self.database.read_connection() as connection:
            profile = CandidateProfileRepository(connection).get(profile_id)
        if profile is None:
            raise KeyError(f"Candidate profile not found: {profile_id}")
        return profile.model_dump(mode="json")

    def overview(self, profile_id: UUID | str | None = None) -> OverviewView:
        profile = str(profile_id or "")
        with self.database.read_connection() as connection:
            active = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE active = 1"
            ).fetchone()[0]
            logical = connection.execute(
                """SELECT COUNT(DISTINCT COALESCE(l.cluster_id, j.id))
                FROM jobs j LEFT JOIN job_duplicate_links l
                    ON l.job_id = j.id AND l.algorithm_version = ?
                WHERE j.active = 1""", (DEDUPLICATION_VERSION,),
            ).fetchone()[0]
            analyses = connection.execute(
                """SELECT COUNT(DISTINCT job_id) FROM job_analyses
                WHERE authority = 'authoritative'
                AND (? = '' OR profile_id = ?)""", (profile, profile),
            ).fetchone()[0]
            preliminary_analyses = connection.execute(
                """SELECT COUNT(DISTINCT job_id) FROM job_analyses
                WHERE authority != 'authoritative'
                AND (? = '' OR profile_id = ?)""", (profile, profile),
            ).fetchone()[0]
            rankings = connection.execute(
                """SELECT COUNT(DISTINCT COALESCE(cluster_id, job_id)) FROM job_rankings
                WHERE authority = 'authoritative'
                AND (? = '' OR profile_id = ?)""", (profile, profile),
            ).fetchone()[0]
            preliminary_rankings = connection.execute(
                """SELECT COUNT(DISTINCT COALESCE(cluster_id, job_id))
                FROM job_rankings WHERE authority != 'authoritative'
                AND (? = '' OR profile_id = ?)""", (profile, profile),
            ).fetchone()[0]
            pending = connection.execute(
                """SELECT COUNT(*) FROM duplicate_candidates
                WHERE algorithm_version = ? AND status = 'pending'""",
                (DEDUPLICATION_VERSION,),
            ).fetchone()[0]
            application_rows = connection.execute(
                """SELECT status, COUNT(*) AS count FROM applications
                WHERE (? = '' OR profile_id = ?) GROUP BY status""",
                (profile, profile),
            ).fetchall()
            runs = connection.execute(
                """SELECT id, source, status, started_at, finished_at, jobs_found,
                    jobs_stored, error_count, error_summary
                FROM collection_runs ORDER BY created_at DESC, id DESC LIMIT 5"""
            ).fetchall()
            batches = connection.execute(
                """SELECT id, profile_id, channel, status, selected_count,
                    chunks_total, chunks_sent, created_at, finished_at
                FROM notification_batches
                WHERE (? = '' OR profile_id = ?)
                ORDER BY created_at DESC, id DESC LIMIT 5""",
                (profile, profile),
            ).fetchall()
            artifacts = connection.execute(
                """SELECT * FROM (
                    SELECT id, job_id, profile_id, source, validated,
                        artifact_path AS path, evidence_report_path, created_at,
                        'current' AS schema_kind
                    FROM cv_generation_artifacts WHERE (? = '' OR profile_id = ?)
                    UNION ALL
                    SELECT id, job_id, profile_id, source, validated, path,
                        NULL AS evidence_report_path, created_at, 'legacy' AS schema_kind
                    FROM cv_artifacts WHERE (? = '' OR profile_id = ?)
                ) ORDER BY created_at DESC, id DESC LIMIT 5""",
                (profile, profile, profile, profile),
            ).fetchall()
        return OverviewView(
            active_source_jobs=int(active), logical_vacancies=int(logical),
            authoritative_analyses=int(analyses), ranked_vacancies=int(rankings),
            preliminary_analyses=int(preliminary_analyses),
            preliminary_rankings=int(preliminary_rankings),
            pending_duplicate_reviews=int(pending),
            application_counts={row["status"]: row["count"] for row in application_rows},
            recent_runs=tuple(dict(row) for row in runs),
            recent_notification_batches=tuple(dict(row) for row in batches),
            recent_cv_artifacts=tuple(dict(row) for row in artifacts),
        )

    def jobs(
        self, filters: JobFilters, profile_id: UUID | str | None = None
    ) -> PageResult[JobListItem]:
        page_size = min(100, max(5, filters.page_size))
        page = max(1, filters.page)
        profile = str(profile_id or "")
        where = []
        parameters: list[object] = [profile, profile, profile, profile]
        if filters.active_only:
            where.append("j.active = 1")
        if filters.logical_only:
            where.append("(jk.representative_job_id = j.id OR jk.cluster_id IS NULL)")
        if filters.search.strip():
            needle = f"%{filters.search.strip().casefold()}%"
            where.append(
                "(LOWER(j.title_raw) LIKE ? OR LOWER(COALESCE(j.company_raw, '')) LIKE ? "
                "OR LOWER(COALESCE(j.location_raw, '')) LIKE ?)"
            )
            parameters.extend((needle, needle, needle))
        for value, clause in (
            (filters.source, "j.source = ?"),
            (filters.completeness, "COALESCE(ld.completeness, 'missing') = ?"),
            (filters.authority, "la.authority = ?"),
        ):
            if value:
                where.append(clause)
                parameters.append(value)
        if filters.language == "unknown":
            where.append("(j.language_detected IS NULL OR j.language_detected = '')")
        elif filters.language:
            where.append("j.language_detected = ?")
            parameters.append(filters.language)
        if filters.application_status:
            where.append("(',' || COALESCE(app.statuses, '') || ',') LIKE ?")
            parameters.append(f"%,{filters.application_status},%")
        for value, clause in (
            (filters.fit_min, "la.fit_score >= ?"),
            (filters.fit_max, "la.fit_score <= ?"),
            (filters.rank_min, "lr.rank_score >= ?"),
            (filters.rank_max, "lr.rank_score <= ?"),
        ):
            if value is not None:
                where.append(clause)
                parameters.append(value)
        where_sql = " AND ".join(where) if where else "1 = 1"
        sort_column = SORT_COLUMNS.get(filters.sort_by, SORT_COLUMNS["rank_score"])
        direction = "DESC" if filters.descending else "ASC"
        sql = f"""
            WITH latest_description AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY job_id ORDER BY fetched_at DESC, created_at DESC, id DESC
                ) AS rn FROM job_descriptions
            ), job_keys AS (
                SELECT j.id AS job_id, l.cluster_id, c.representative_job_id,
                    COALESCE(l.cluster_id, j.id) AS logical_id
                FROM jobs j
                LEFT JOIN job_duplicate_links l
                    ON l.job_id = j.id AND l.algorithm_version = ?
                LEFT JOIN duplicate_clusters c
                    ON c.id = l.cluster_id AND c.algorithm_version = l.algorithm_version
            ), latest_analysis AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY job_id ORDER BY created_at DESC, id DESC
                ) AS rn FROM job_analyses WHERE (? = '' OR profile_id = ?)
            ), latest_ranking AS (
                SELECT *, COALESCE(cluster_id, job_id) AS logical_id,
                    ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(cluster_id, job_id)
                    ORDER BY ranked_as_of DESC, created_at DESC, id DESC
                ) AS rn FROM job_rankings WHERE (? = '' OR profile_id = ?)
            ), application_statuses AS (
                SELECT jk.logical_id, GROUP_CONCAT(DISTINCT a.status) AS statuses
                FROM applications a JOIN job_keys jk ON jk.job_id = a.job_id
                WHERE (? = '' OR a.profile_id = ?) GROUP BY jk.logical_id
            )
            SELECT j.id AS job_id, jk.logical_id, jk.cluster_id,
                CASE WHEN jk.representative_job_id = j.id THEN 1 ELSE 0 END AS representative,
                j.title_raw, j.company_raw, j.location_raw, j.source,
                COALESCE(ld.completeness, 'missing') AS completeness,
                j.language_detected, j.explicit_german_requirement,
                la.authority, la.fit_score, lr.rank_score, app.statuses,
                j.published_at, j.last_seen_at, COUNT(*) OVER() AS total_count
            FROM jobs j JOIN job_keys jk ON jk.job_id = j.id
            LEFT JOIN latest_description ld ON ld.job_id = j.id AND ld.rn = 1
            LEFT JOIN latest_analysis la ON la.job_id = j.id AND la.rn = 1
            LEFT JOIN latest_ranking lr ON lr.logical_id = jk.logical_id AND lr.rn = 1
            LEFT JOIN application_statuses app ON app.logical_id = jk.logical_id
            WHERE {where_sql}
            ORDER BY ({sort_column} IS NULL), {sort_column} {direction},
                j.title_normalized, j.company_normalized, j.id
            LIMIT ? OFFSET ?
        """
        # Four parameters belong to the profile-aware CTEs after the dedup version.
        parameters = [DEDUPLICATION_VERSION, *parameters[:4], profile, profile, *parameters[4:]]
        parameters.extend((page_size, (page - 1) * page_size))
        with self.database.read_connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        total = int(rows[0]["total_count"]) if rows else 0
        items = tuple(JobListItem(
            job_id=row["job_id"], logical_id=row["logical_id"],
            cluster_id=row["cluster_id"], representative=bool(row["representative"]),
            title=row["title_raw"], company=row["company_raw"],
            location=row["location_raw"], source=row["source"],
            completeness=row["completeness"], language=row["language_detected"],
            german_requirement=row["explicit_german_requirement"],
            authority=row["authority"], fit_score=row["fit_score"],
            rank_score=row["rank_score"],
            application_statuses=tuple(sorted(filter(
                None, (row["statuses"] or "").split(",")
            ))),
            published_at=row["published_at"], last_seen_at=row["last_seen_at"],
        ) for row in rows)
        return PageResult(items=items, total=total, page=page, page_size=page_size)

    def job_detail(
        self, job_id: UUID | str, profile_id: UUID | str | None = None
    ) -> JobDetailView:
        job_key = str(job_id)
        profile = str(profile_id or "")
        with self.database.read_connection() as connection:
            job = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_key,)).fetchone()
            if job is None:
                raise KeyError(f"Job not found: {job_id}")
            description = connection.execute(
                """SELECT * FROM job_descriptions WHERE job_id = ?
                ORDER BY fetched_at DESC, created_at DESC, id DESC LIMIT 1""",
                (job_key,),
            ).fetchone()
            link = connection.execute(
                """SELECT l.*, c.representative_job_id FROM job_duplicate_links l
                JOIN duplicate_clusters c ON c.id = l.cluster_id
                WHERE l.job_id = ? AND l.algorithm_version = ?""",
                (job_key, DEDUPLICATION_VERSION),
            ).fetchone()
            if link:
                members = connection.execute(
                    """SELECT j.*, l.match_method, l.confidence, l.reasons_json,
                        CASE WHEN c.representative_job_id = j.id THEN 1 ELSE 0 END AS representative
                    FROM job_duplicate_links l JOIN jobs j ON j.id = l.job_id
                    JOIN duplicate_clusters c ON c.id = l.cluster_id
                    WHERE l.cluster_id = ? AND l.algorithm_version = ?
                    ORDER BY representative DESC, j.source, j.id""",
                    (link["cluster_id"], DEDUPLICATION_VERSION),
                ).fetchall()
                member_ids = [row["id"] for row in members]
            else:
                members = []
                member_ids = [job_key]
            placeholders = ",".join("?" for _ in member_ids)
            analysis = connection.execute(
                f"""SELECT * FROM job_analyses WHERE job_id IN ({placeholders})
                AND (? = '' OR profile_id = ?)
                ORDER BY created_at DESC, id DESC LIMIT 1""",
                (*member_ids, profile, profile),
            ).fetchone()
            ranking = connection.execute(
                f"""SELECT * FROM job_rankings WHERE job_id IN ({placeholders})
                AND (? = '' OR profile_id = ?)
                ORDER BY ranked_as_of DESC, created_at DESC, id DESC LIMIT 1""",
                (*member_ids, profile, profile),
            ).fetchone()
            applications = connection.execute(
                f"""SELECT * FROM applications WHERE job_id IN ({placeholders})
                AND (? = '' OR profile_id = ?) ORDER BY updated_at DESC, id""",
                (*member_ids, profile, profile),
            ).fetchall()
            app_ids = [row["id"] for row in applications]
            history = []
            if app_ids:
                app_placeholders = ",".join("?" for _ in app_ids)
                history = connection.execute(
                    f"""SELECT * FROM application_events
                    WHERE application_id IN ({app_placeholders})
                    ORDER BY created_at, id""", app_ids,
                ).fetchall()
            notifications = connection.execute(
                f"""SELECT ni.*, nb.status AS batch_status, nb.created_at AS batch_created_at
                FROM notification_items ni JOIN notification_batches nb ON nb.id = ni.batch_id
                WHERE ni.representative_job_id IN ({placeholders})
                ORDER BY ni.created_at DESC, ni.id""", member_ids,
            ).fetchall()
            current_artifacts = connection.execute(
                f"""SELECT id, job_id, profile_id, analysis_id, source, artifact_path AS path,
                    evidence_report_path, validated, created_at, 'current' AS schema_kind
                FROM cv_generation_artifacts WHERE job_id IN ({placeholders})
                ORDER BY created_at DESC, id""", member_ids,
            ).fetchall()
            legacy_artifacts = connection.execute(
                f"""SELECT id, job_id, profile_id, analysis_id, source, path,
                    NULL AS evidence_report_path, validated, created_at, 'legacy' AS schema_kind
                FROM cv_artifacts WHERE job_id IN ({placeholders})
                ORDER BY created_at DESC, id""", member_ids,
            ).fetchall()
        analysis_dict = self._decode_analysis(dict(analysis)) if analysis else None
        ranking_dict = self._decode_ranking(dict(ranking)) if ranking else None
        return JobDetailView(
            job=dict(job), description=self._decode_description(dict(description)) if description else None,
            cluster=dict(link) if link else None,
            cluster_members=tuple(self._decode_member(dict(row)) for row in members),
            analysis=analysis_dict, ranking=ranking_dict,
            applications=tuple(dict(row) for row in applications),
            application_history=tuple(dict(row) for row in history),
            notifications=tuple(self._decode_notification(dict(row)) for row in notifications),
            cv_artifacts=tuple(dict(row) for row in (*current_artifacts, *legacy_artifacts)),
        )

    def duplicate_reviews(self, status: str = "pending") -> tuple[DuplicateReviewView, ...]:
        with self.database.read_connection() as connection:
            rows = connection.execute(
                """SELECT * FROM duplicate_candidates
                WHERE algorithm_version = ? AND status = ?
                ORDER BY confidence DESC, created_at, id""",
                (DEDUPLICATION_VERSION, status),
            ).fetchall()
            results = []
            for row in rows:
                left = connection.execute(
                    "SELECT * FROM jobs WHERE id = ?", (row["left_job_id"],)
                ).fetchone()
                right = connection.execute(
                    "SELECT * FROM jobs WHERE id = ?", (row["right_job_id"],)
                ).fetchone()
                candidate = dict(row)
                candidate["reasons"] = json.loads(candidate.pop("reasons_json"))
                results.append(DuplicateReviewView(candidate, dict(left), dict(right)))
        return tuple(results)

    def applications(
        self, profile_id: UUID | str | None = None, status: str | None = None
    ) -> tuple[dict[str, object], ...]:
        clauses = []
        parameters: list[object] = []
        if profile_id:
            clauses.append("a.profile_id = ?")
            parameters.append(str(profile_id))
        if status:
            clauses.append("a.status = ?")
            parameters.append(status)
        where = " AND ".join(clauses) if clauses else "1 = 1"
        with self.database.read_connection() as connection:
            rows = connection.execute(
                f"""SELECT
                    a.id, a.job_id, a.profile_id, a.logical_cluster_id,
                    a.status, a.current_status, a.priority, a.notes,
                    CASE
                        WHEN length(a.notes) > 120 THEN substr(a.notes, 1, 117) || '...'
                        ELSE a.notes
                    END AS notes_preview,
                    a.follow_up_date, a.cv_artifact_id, a.source AS application_source,
                    a.created_at, a.updated_at,
                    j.title_raw, j.company_raw, j.location_raw, j.source,
                    (
                        SELECT c.id FROM cv_generation_artifacts c
                        WHERE c.profile_id = a.profile_id
                          AND (
                            c.job_id = a.job_id OR
                            (a.logical_cluster_id IS NOT NULL
                             AND c.logical_cluster_id = a.logical_cluster_id)
                          )
                        ORDER BY c.created_at DESC, c.id DESC
                        LIMIT 1
                    ) AS latest_cv_artifact_id,
                    CASE
                        WHEN a.cv_artifact_id IS NOT NULL
                         AND a.cv_artifact_id != (
                            SELECT c.id FROM cv_generation_artifacts c
                            WHERE c.profile_id = a.profile_id
                              AND (
                                c.job_id = a.job_id OR
                                (a.logical_cluster_id IS NOT NULL
                                 AND c.logical_cluster_id = a.logical_cluster_id)
                              )
                            ORDER BY c.created_at DESC, c.id DESC
                            LIMIT 1
                         )
                        THEN 1 ELSE 0
                    END AS attached_cv_differs_from_latest,
                    (
                        SELECT jr.rank_score FROM job_rankings jr
                        WHERE jr.profile_id = a.profile_id
                          AND (
                            jr.job_id = a.job_id OR
                            (a.logical_cluster_id IS NOT NULL
                             AND jr.cluster_id = a.logical_cluster_id)
                          )
                        ORDER BY jr.created_at DESC, jr.id DESC
                        LIMIT 1
                    ) AS rank_score,
                    COALESCE((
                        SELECT ja.fit_score FROM job_analyses ja
                        WHERE ja.profile_id = a.profile_id
                          AND ja.job_id = a.job_id
                        ORDER BY ja.created_at DESC, ja.id DESC
                        LIMIT 1
                    ), (
                        SELECT ja.fit_score
                        FROM job_rankings jr
                        JOIN job_analyses ja ON ja.id = jr.analysis_id
                        WHERE jr.profile_id = a.profile_id
                          AND (
                            jr.job_id = a.job_id OR
                            (a.logical_cluster_id IS NOT NULL
                             AND jr.cluster_id = a.logical_cluster_id)
                          )
                        ORDER BY jr.created_at DESC, jr.id DESC
                        LIMIT 1
                    )) AS fit_score
                FROM applications a JOIN jobs j ON j.id = a.job_id
                WHERE {where} ORDER BY a.updated_at DESC, a.id""", parameters,
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def list_cv_artifacts(
        self,
        profile_id: UUID | str | None = None,
        job_id: UUID | str | None = None,
    ) -> tuple[dict[str, object], ...]:
        clauses = []
        parameters: list[object] = []
        if profile_id:
            clauses.append("c.profile_id = ?")
            parameters.append(str(profile_id))
        if job_id:
            clauses.append("c.job_id = ?")
            parameters.append(str(job_id))
        where = " AND ".join(clauses) if clauses else "1 = 1"
        with self.database.read_connection() as connection:
            rows = connection.execute(
                f"""SELECT
                    c.id AS artifact_id, c.job_id, c.logical_cluster_id,
                    c.profile_id, p.profile_key, c.generation_mode, c.source,
                    c.generator_version, c.formatter_version,
                    ? AS builder_content_version,
                    c.parent_rule_based_artifact_id, c.provider, c.model,
                    c.prompt_version, c.ai_generated_at,
                    (
                        SELECT ca.status FROM cv_ai_attempts ca
                        WHERE ca.parent_rule_based_artifact_id =
                            COALESCE(c.parent_rule_based_artifact_id, c.id)
                        ORDER BY ca.generated_at DESC, ca.id DESC
                        LIMIT 1
                    ) AS ai_status,
                    (
                        SELECT ca.failure_category FROM cv_ai_attempts ca
                        WHERE ca.parent_rule_based_artifact_id =
                            COALESCE(c.parent_rule_based_artifact_id, c.id)
                        ORDER BY ca.generated_at DESC, ca.id DESC
                        LIMIT 1
                    ) AS ai_failure_category,
                    c.validated, c.artifact_path, c.evidence_report_path,
                    c.created_at, j.title_raw, j.company_raw, j.location_raw,
                    a.status AS application_status,
                    a.cv_artifact_id AS attached_cv_artifact_id,
                    CASE WHEN a.cv_artifact_id = c.id THEN 1 ELSE 0 END AS attached
                FROM cv_generation_artifacts c
                LEFT JOIN jobs j ON j.id = c.job_id
                LEFT JOIN candidate_profiles p ON p.id = c.profile_id
                LEFT JOIN applications a
                    ON a.profile_id = c.profile_id
                   AND (
                        a.job_id = c.job_id OR
                        (c.logical_cluster_id IS NOT NULL
                         AND a.logical_cluster_id = c.logical_cluster_id)
                   )
                WHERE {where}
                ORDER BY c.created_at DESC, c.id DESC""",
                (CV_BUILDER_CONTENT_VERSION, *parameters),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def get_cv_artifact_detail(self, artifact_id: UUID | str) -> dict[str, object]:
        rows = self.list_cv_artifacts()
        for row in rows:
            if str(row["artifact_id"]) == str(artifact_id):
                return row
        raise KeyError(f"CV artifact not found: {artifact_id}")

    def read_cv_artifact_text(self, artifact_id: UUID | str) -> dict[str, object]:
        return self._read_cv_file(artifact_id, evidence=False)

    def read_evidence_report_text(self, artifact_id: UUID | str) -> dict[str, object]:
        return self._read_cv_file(artifact_id, evidence=True)

    def list_applications_with_cv_context(
        self, profile_id: UUID | str | None = None
    ) -> tuple[dict[str, object], ...]:
        return self.applications(profile_id)

    def _read_cv_file(
        self, artifact_id: UUID | str, *, evidence: bool
    ) -> dict[str, object]:
        with self.database.read_connection() as connection:
            row = connection.execute(
                """SELECT artifact_path, evidence_report_path
                FROM cv_generation_artifacts WHERE id = ?""",
                (str(artifact_id),),
            ).fetchone()
        if row is None:
            raise KeyError(f"CV artifact not found: {artifact_id}")
        path = Path(row["evidence_report_path"] if evidence else row["artifact_path"])
        if not path.is_file():
            return {
                "artifact_id": str(artifact_id),
                "path": str(path),
                "found": False,
                "text": None,
                "message": "Stored artifact file is missing.",
            }
        return {
            "artifact_id": str(artifact_id),
            "path": str(path),
            "found": True,
            "text": path.read_text(encoding="utf-8"),
            "message": None,
        }

    def runs(self, limit: int = 100) -> tuple[dict[str, object], ...]:
        with self.database.read_connection() as connection:
            rows = connection.execute(
                """SELECT id, source, status, started_at, finished_at, jobs_found,
                    jobs_stored, jobs_inserted, jobs_updated, queries_executed,
                    pages_requested, search_requests_succeeded, search_requests_failed,
                    detail_requests_succeeded, detail_requests_failed, error_count,
                    error_summary, created_at FROM collection_runs
                ORDER BY created_at DESC, id DESC LIMIT ?""",
                (min(500, max(1, limit)),),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def diagnostics(self) -> dict[str, object]:
        with self.database.read_connection() as connection:
            migrations = connection.execute(
                "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
            ).fetchall()
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "jobs", "job_descriptions", "candidate_profiles", "applications",
                    "job_analyses", "job_rankings", "notification_batches",
                    "cv_generation_artifacts",
                )
            }
            integrity = connection.execute("PRAGMA foreign_key_check").fetchall()
        return {
            "database_name": Path(self.database.path).name,
            "migrations": tuple(dict(row) for row in migrations),
            "counts": counts, "foreign_key_issues": len(integrity),
        }

    def application_analytics(
        self,
        profile_id: UUID | str | None = None,
        *,
        daily_runs_dir: Path | str | None = None,
    ) -> dict[str, object]:
        return ApplicationAnalyticsService(
            self.database,
            daily_runs_dir=daily_runs_dir,
        ).summary(profile_id)

    def prep_pack_command(
        self,
        profile_id: UUID | str,
        job_id: UUID | str,
        cv_artifact_id: UUID | str | None = None,
    ) -> str:
        return PrepPackService(
            self.database,
            default_output_dir=Path("data/prep_packs"),
        ).preview_command(
            profile_id=profile_id,
            job_id=job_id,
            cv_artifact_id=cv_artifact_id,
        )

    def latest_prep_packs(
        self,
        prep_pack_dir: Path | str,
        *,
        job_id: UUID | str | None = None,
        limit: int = 10,
    ) -> tuple[dict[str, object], ...]:
        return latest_prep_packs(prep_pack_dir, job_id=job_id, limit=limit)

    def application_pack_command(
        self,
        profile_id: UUID | str,
        job_id: UUID | str,
        cv_artifact_id: UUID | str | None = None,
    ) -> str:
        return ApplicationPackService(
            self.database,
            default_output_dir=Path("data/application_packs"),
            prep_pack_dir=Path("data/prep_packs"),
        ).preview_command(
            profile_id=profile_id,
            job_id=job_id,
            cv_artifact_id=cv_artifact_id,
        )

    def manual_submit_command(
        self,
        profile_id: UUID | str,
        job_id: UUID | str,
        follow_up_date: str | None = None,
    ) -> str:
        return ApplicationPackService(
            self.database,
            default_output_dir=Path("data/application_packs"),
            prep_pack_dir=Path("data/prep_packs"),
        ).submit_manual_command(
            profile_id=profile_id,
            job_id=job_id,
            follow_up_date=follow_up_date,
        )

    def latest_application_packs(
        self,
        application_pack_dir: Path | str,
        *,
        job_id: UUID | str | None = None,
        limit: int = 10,
    ) -> tuple[dict[str, object], ...]:
        return latest_application_packs(
            application_pack_dir, job_id=job_id, limit=limit
        )

    def communication_draft_commands(
        self,
        profile_id: UUID | str,
        job_id: UUID | str,
    ) -> tuple[dict[str, str], ...]:
        service = CommunicationDraftService(
            self.database,
            default_output_dir=Path("data/communication_drafts"),
            prep_pack_dir=Path("data/prep_packs"),
            application_pack_dir=Path("data/application_packs"),
        )
        return tuple({
            "draft_type": draft_type,
            "command": service.preview_command(
                profile_id=profile_id,
                job_id=job_id,
                draft_type=draft_type,
            ),
        } for draft_type in SUPPORTED_DRAFT_TYPES)

    def latest_communication_drafts(
        self,
        communication_draft_dir: Path | str,
        *,
        job_id: UUID | str | None = None,
        limit: int = 10,
    ) -> tuple[dict[str, object], ...]:
        return latest_communication_drafts(
            communication_draft_dir, job_id=job_id, limit=limit
        )

    @staticmethod
    def _decode_description(value):
        value["structured_data"] = json.loads(value.pop("structured_data_json"))
        return value

    @staticmethod
    def _decode_member(value):
        value["reasons"] = json.loads(value.pop("reasons_json"))
        return value

    @staticmethod
    def _decode_analysis(value):
        for source, target in (
            ("requirements_json", "requirements"), ("evidence_json", "evidence"),
            ("missing_skills_json", "missing_skills"), ("risk_flags_json", "risk_flags"),
            ("fit_reasons_json", "fit_reasons"),
            ("positive_components_json", "positive_components"),
            ("penalties_json", "penalties"), ("score_caps_json", "score_caps"),
        ):
            value[target] = json.loads(value.pop(source))
        return value

    @staticmethod
    def _decode_ranking(value):
        value["components"] = json.loads(value.pop("components_json"))
        return value

    @staticmethod
    def _decode_notification(value):
        value["snapshot"] = json.loads(value.pop("snapshot_json"))
        return value
