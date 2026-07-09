"""Read-only application analytics for CLI and dashboard views."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db.connection import Database
from app.domain.enums import ApplicationStatus, DescriptionCompleteness
from app.services.deduplication import DEDUPLICATION_VERSION


FOLLOW_UP_LIMIT = 50


def read_daily_run_summaries(
    daily_runs_dir: Path | str,
    *,
    limit: int = 7,
) -> tuple[dict[str, Any], ...]:
    """Read ignored local daily-run JSON summaries without failing the page."""
    directory = Path(daily_runs_dir)
    if not directory.is_dir():
        return ()
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("daily_*.json"), reverse=True)[: max(1, limit)]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        rows.append(_daily_run_row(path, payload))
    return tuple(rows)


class ApplicationAnalyticsService:
    """Compose passive progress metrics from existing persisted records."""

    def __init__(
        self,
        database: Database,
        *,
        daily_runs_dir: Path | str | None = None,
        today: date | None = None,
    ) -> None:
        self.database = database
        self.daily_runs_dir = Path(daily_runs_dir) if daily_runs_dir else None
        self.today = today or date.today()

    def summary(self, profile_id: UUID | str | None = None) -> dict[str, Any]:
        profile = str(profile_id) if profile_id else None
        with self.database.read_connection() as connection:
            total_jobs = _scalar(connection, "SELECT COUNT(*) FROM jobs")
            logical_vacancies = self._logical_vacancies(connection)
            jobs_by_source = _pairs(
                connection,
                "SELECT source, COUNT(*) FROM jobs GROUP BY source ORDER BY source",
            )
            completeness_by_source = self._description_completeness(connection)
            description_counts = {
                item.value: sum(row[item.value] for row in completeness_by_source)
                for item in DescriptionCompleteness
            }
            applications_by_status = self._applications_group(
                connection, "current_status", profile
            )
            applications_by_priority = self._applications_group(
                connection, "COALESCE(priority, 'unset')", profile
            )
            source_quality = self._source_quality(connection, profile)
            due = self._followups(connection, profile, operator="<=", days=0)
            overdue = self._followups(connection, profile, operator="<", days=0)
            upcoming = self._followups(
                connection, profile, operator="between", days=7
            )
            metrics = {
                "total_jobs_stored": total_jobs,
                "total_logical_vacancies": logical_vacancies,
                "cv_ready_count": applications_by_status["cv_ready"],
                "applied_count": applications_by_status["applied"],
                "interview_count": applications_by_status["interview"],
                "rejected_count": applications_by_status["rejected"],
                "due_followups": len(due),
                "overdue_followups": len(overdue),
                "jobs_collected_last_7_days": self._recent_jobs(connection, 7),
                "jobs_collected_last_30_days": self._recent_jobs(connection, 30),
                "applications_created_last_7_days": self._recent_applications(
                    connection, profile, 7
                ),
                "applications_created_last_30_days": self._recent_applications(
                    connection, profile, 30
                ),
            }
        daily_runs = self._daily_runs()
        return {
            "profile_id": profile,
            "metrics": metrics,
            "jobs_by_source": jobs_by_source,
            "description_completeness": description_counts,
            "description_completeness_by_source": completeness_by_source,
            "applications_by_status": applications_by_status,
            "applications_by_priority": applications_by_priority,
            "funnel": self._funnel(logical_vacancies, applications_by_status),
            "source_quality": source_quality,
            "followups": {
                "due": due,
                "overdue": overdue,
                "next_7_days": upcoming,
            },
            "daily_runs": daily_runs,
        }

    def _logical_vacancies(self, connection) -> int:
        return _scalar(
            connection,
            """
            SELECT COUNT(DISTINCT COALESCE(l.cluster_id, jobs.id))
            FROM jobs
            LEFT JOIN job_duplicate_links l
              ON l.job_id = jobs.id AND l.algorithm_version = ?
            WHERE jobs.active = 1
            """,
            (DEDUPLICATION_VERSION,),
        )

    def _description_completeness(self, connection) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            WITH latest_description AS (
                SELECT job_id, completeness,
                       ROW_NUMBER() OVER (
                           PARTITION BY job_id
                           ORDER BY fetched_at DESC, created_at DESC, id DESC
                       ) AS row_number
                FROM job_descriptions
            )
            SELECT jobs.source,
                   SUM(CASE WHEN latest_description.completeness = 'full' THEN 1 ELSE 0 END) AS full,
                   SUM(CASE WHEN latest_description.completeness = 'snippet' THEN 1 ELSE 0 END) AS snippet,
                   SUM(CASE WHEN latest_description.completeness = 'missing'
                            OR latest_description.completeness IS NULL THEN 1 ELSE 0 END) AS missing
            FROM jobs
            LEFT JOIN latest_description
              ON latest_description.job_id = jobs.id
             AND latest_description.row_number = 1
            GROUP BY jobs.source
            ORDER BY jobs.source
            """
        ).fetchall()
        return [
            {
                "source": row["source"],
                "full": int(row["full"] or 0),
                "snippet": int(row["snippet"] or 0),
                "missing": int(row["missing"] or 0),
            }
            for row in rows
        ]

    def _applications_group(
        self,
        connection,
        expression: str,
        profile_id: str | None,
    ) -> dict[str, int]:
        values: dict[str, int] = {}
        where, params = _profile_filter(profile_id)
        for row in connection.execute(
            f"""
            SELECT {expression} AS key, COUNT(*) AS count
            FROM applications
            {where}
            GROUP BY key
            ORDER BY key
            """,
            params,
        ):
            values[str(row["key"])] = int(row["count"])
        if expression == "current_status":
            for status in ApplicationStatus:
                values.setdefault(status.value, 0)
        return values

    def _source_quality(
        self,
        connection,
        profile_id: str | None,
    ) -> tuple[dict[str, Any], ...]:
        app_filter = "AND (? IS NULL OR applications.profile_id = ?)"
        rows = connection.execute(
            """
            WITH latest_description AS (
                SELECT job_id, completeness,
                       ROW_NUMBER() OVER (
                           PARTITION BY job_id
                           ORDER BY fetched_at DESC, created_at DESC, id DESC
                       ) AS row_number
                FROM job_descriptions
            )
            SELECT jobs.source,
                   COUNT(DISTINCT jobs.id) AS jobs,
                   COUNT(DISTINCT CASE WHEN latest_description.completeness = 'full'
                                       THEN jobs.id END) AS full_descriptions,
                   COUNT(DISTINCT CASE WHEN latest_description.completeness = 'snippet'
                                       THEN jobs.id END) AS snippet_descriptions,
                   COUNT(DISTINCT CASE WHEN latest_description.completeness = 'missing'
                                          OR latest_description.completeness IS NULL
                                       THEN jobs.id END) AS missing_descriptions,
                   COUNT(DISTINCT applications.id) AS applications,
                   COUNT(DISTINCT CASE WHEN applications.current_status = 'cv_ready'
                                       THEN applications.id END) AS cv_ready,
                   COUNT(DISTINCT CASE WHEN applications.current_status = 'applied'
                                       THEN applications.id END) AS applied
            FROM jobs
            LEFT JOIN latest_description
              ON latest_description.job_id = jobs.id
             AND latest_description.row_number = 1
            LEFT JOIN applications
              ON applications.job_id = jobs.id
             """ + app_filter + """
            GROUP BY jobs.source
            ORDER BY jobs.source
            """,
            (profile_id, profile_id),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def _followups(
        self,
        connection,
        profile_id: str | None,
        *,
        operator: str,
        days: int,
    ) -> tuple[dict[str, Any], ...]:
        today = self.today.isoformat()
        params: list[Any] = []
        profile_clause = ""
        if operator == "between":
            date_clause = "applications.follow_up_date > ? AND applications.follow_up_date <= ?"
            params.extend([today, (self.today + timedelta(days=days)).isoformat()])
        else:
            date_clause = f"applications.follow_up_date {operator} ?"
            params.append(today)
        if profile_id:
            profile_clause = "AND applications.profile_id = ?"
            params.append(profile_id)
        rows = connection.execute(
            f"""
            SELECT applications.id AS application_id,
                   applications.job_id,
                   jobs.title_raw AS title,
                   jobs.company_raw AS company,
                   jobs.source,
                   applications.current_status AS status,
                   applications.priority,
                   applications.follow_up_date,
                   CASE
                     WHEN length(applications.notes) > 160
                     THEN substr(applications.notes, 1, 157) || '...'
                     ELSE applications.notes
                   END AS last_note
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.follow_up_date IS NOT NULL
              AND {date_clause}
              {profile_clause}
            ORDER BY applications.follow_up_date ASC, applications.updated_at DESC
            LIMIT ?
            """,
            (*params, FOLLOW_UP_LIMIT),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def _recent_jobs(self, connection, days: int) -> int:
        cutoff = (self.today - timedelta(days=days)).isoformat()
        return _scalar(
            connection,
            "SELECT COUNT(*) FROM jobs WHERE first_seen_at >= ?",
            (cutoff,),
        )

    def _recent_applications(
        self,
        connection,
        profile_id: str | None,
        days: int,
    ) -> int:
        cutoff = (self.today - timedelta(days=days)).isoformat()
        where, params = _profile_filter(profile_id, prefix="WHERE")
        connector = "AND" if where else "WHERE"
        return _scalar(
            connection,
            f"SELECT COUNT(*) FROM applications {where} {connector} created_at >= ?",
            (*params, cutoff),
        )

    def _daily_runs(self) -> dict[str, Any]:
        if not self.daily_runs_dir:
            rows: tuple[dict[str, Any], ...] = ()
        else:
            rows = read_daily_run_summaries(self.daily_runs_dir, limit=7)
        return {
            "latest": rows[0] if rows else None,
            "last_7": rows,
            "total_searches": sum(int(row.get("searches", 0) or 0) for row in rows),
            "successful_searches": sum(
                int(row.get("successful_searches", 0) or 0) for row in rows
            ),
            "failed_searches": sum(
                int(row.get("failed_searches", 0) or 0) for row in rows
            ),
            "jobs_collected": sum(
                int(row.get("jobs_collected", 0) or 0) for row in rows
            ),
            "top_jobs": sum(int(row.get("top_jobs", 0) or 0) for row in rows),
            "errors": sum(int(row.get("errors", 0) or 0) for row in rows),
        }

    @staticmethod
    def _funnel(
        logical_vacancies: int,
        applications_by_status: dict[str, int],
    ) -> tuple[dict[str, Any], ...]:
        tracked = sum(applications_by_status.get(item.value, 0) for item in ApplicationStatus)
        return (
            {"stage": "new/discovered", "count": max(logical_vacancies - tracked, 0)},
            {"stage": "shortlisted", "count": applications_by_status["shortlisted"]},
            {"stage": "cv_ready", "count": applications_by_status["cv_ready"]},
            {"stage": "applied", "count": applications_by_status["applied"]},
            {"stage": "interview", "count": applications_by_status["interview"]},
            {"stage": "offer", "count": applications_by_status["offer"]},
            {
                "stage": "rejected/withdrawn",
                "count": (
                    applications_by_status["rejected"]
                    + applications_by_status["withdrawn"]
                ),
            },
        )


def _daily_run_row(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    searches = [
        item for item in payload.get("searches", [])
        if isinstance(item, dict)
    ]
    scopes = [
        item.get("pipeline_summary", {}).get("ranking_scope")
        for item in searches
        if isinstance(item.get("pipeline_summary"), dict)
    ]
    return {
        "status": payload.get("status"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "ranking_scope": ", ".join(
            dict.fromkeys(str(scope) for scope in scopes if scope)
        ),
        "searches": int(payload.get("total_searches", len(searches)) or 0),
        "successful_searches": int(payload.get("successful_searches", 0) or 0),
        "failed_searches": int(payload.get("failed_searches", 0) or 0),
        "jobs_collected": sum(
            int(item.get("jobs_collected", 0) or 0) for item in searches
        ),
        "top_jobs": sum(
            int(item.get("top_jobs_count", 0) or 0) for item in searches
        ),
        "errors": len(payload.get("errors", []) or []),
        "path": str(path),
    }


def _pairs(connection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in connection.execute(sql, params).fetchall()
    }


def _scalar(connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(connection.execute(sql, params).fetchone()[0] or 0)


def _profile_filter(
    profile_id: str | None,
    *,
    prefix: str = "WHERE",
) -> tuple[str, tuple[str, ...]]:
    if not profile_id:
        return "", ()
    return f"{prefix} profile_id = ?", (profile_id,)
