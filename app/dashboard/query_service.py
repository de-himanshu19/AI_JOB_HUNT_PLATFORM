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
from app.services.deduplication import DEDUPLICATION_VERSION
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
            rankings = connection.execute(
                """SELECT COUNT(DISTINCT COALESCE(cluster_id, job_id)) FROM job_rankings
                WHERE authority = 'authoritative'
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
                f"""SELECT a.*, j.title_raw, j.company_raw, j.location_raw, j.source
                FROM applications a JOIN jobs j ON j.id = a.job_id
                WHERE {where} ORDER BY a.updated_at DESC, a.id""", parameters,
            ).fetchall()
        return tuple(dict(row) for row in rows)

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
