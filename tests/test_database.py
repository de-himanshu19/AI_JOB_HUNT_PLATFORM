from __future__ import annotations

import sqlite3
import shutil
from pathlib import Path

import pytest

from app.config import settings_from_mapping
from app.db.connection import Database
from app.db.migrations import migrate
from app.db.repositories import CandidateProfileRepository, JobRepository
from app.domain.enums import JobSource
from app.domain.job import Job


EXPECTED_TABLES = {
    "jobs",
    "job_descriptions",
    "candidate_profiles",
    "collection_runs",
    "applications",
    "application_events",
    "job_analyses",
    "notifications",
    "cv_artifacts",
    "schema_migrations",
    "duplicate_clusters",
    "job_duplicate_links",
    "duplicate_candidates",
    "job_rankings",
    "notification_batches",
    "notification_deliveries",
    "notification_items",
}


def test_database_creation_from_zero_and_repeatable_migrations(tmp_path: Path) -> None:
    db = Database(tmp_path / "new/db.sqlite3")
    assert migrate(db) == [1, 2, 3, 4, 5]
    assert migrate(db) == []

    with db.read_connection() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert EXPECTED_TABLES <= tables
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations"
        ).fetchone()["count"] == 5


def test_migration_003_upgrades_existing_database_without_losing_jobs(
    tmp_path: Path,
) -> None:
    legacy_migrations = tmp_path / "legacy_migrations"
    legacy_migrations.mkdir()
    migration_root = Path(__file__).parents[1] / "migrations"
    for name in ("001_initial.sql", "002_arbeitsagentur_collection.sql"):
        shutil.copy2(migration_root / name, legacy_migrations / name)

    database = Database(tmp_path / "existing.sqlite3")
    assert migrate(database, directory=legacy_migrations) == [1, 2]
    existing_job = Job(
        source=JobSource.MANUAL,
        source_job_id="pre-m4-job",
        title_raw="Existing Analyst",
        title_normalized="existing analyst",
    )
    with database.transaction() as connection:
        JobRepository(connection).create(existing_job)

    assert migrate(database) == [3, 4, 5]
    with database.read_connection() as connection:
        assert JobRepository(connection).get(existing_job.id) == existing_job
        job_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(jobs)")
        }
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "normalization_version" in job_columns
    assert {"duplicate_clusters", "job_duplicate_links", "duplicate_candidates"} <= tables


def test_migration_004_preserves_version_003_data_and_foreign_keys(
    tmp_path: Path, master_cv_data: dict,
) -> None:
    through_003 = tmp_path / "through_003"
    through_003.mkdir()
    migration_root = Path(__file__).parents[1] / "migrations"
    for name in (
        "001_initial.sql", "002_arbeitsagentur_collection.sql",
        "003_normalization_duplicates.sql",
    ):
        shutil.copy2(migration_root / name, through_003 / name)
    database = Database(tmp_path / "m4.sqlite3")
    assert migrate(database, directory=through_003) == [1, 2, 3]

    ids = {
        "job": "00000000-0000-0000-0000-000000000401",
        "description": "00000000-0000-0000-0000-000000000402",
        "cluster": "00000000-0000-0000-0000-000000000403",
        "link": "00000000-0000-0000-0000-000000000404",
        "candidate": "00000000-0000-0000-0000-000000000405",
        "other_job": "00000000-0000-0000-0000-000000000406",
        "application": "00000000-0000-0000-0000-000000000407",
        "event": "00000000-0000-0000-0000-000000000408",
        "analysis": "00000000-0000-0000-0000-000000000409",
        "artifact": "00000000-0000-0000-0000-000000000410",
    }
    now = "2026-07-06T12:00:00+00:00"
    with database.transaction() as connection:
        profile = CandidateProfileRepository(connection).create_version(
            master_cv_data, profile_key="migration-candidate"
        )
        for job_id, source_id in (
            (ids["job"], "m4-job"), (ids["other_job"], "m4-other"),
        ):
            connection.execute(
                """INSERT INTO jobs (
                    id, source, source_job_id, title_raw, title_normalized,
                    first_seen_at, last_seen_at, active, created_at, updated_at,
                    normalization_version
                ) VALUES (?, 'manual', ?, 'Analyst', 'analyst', ?, ?, 1, ?, ?, 'm4')""",
                (job_id, source_id, now, now, now, now),
            )
        connection.execute(
            """INSERT INTO job_descriptions (
                id, job_id, raw_text, normalized_text, completeness, content_hash,
                structured_data_json, fetched_at, created_at, normalization_version
            ) VALUES (?, ?, 'Full description', 'full description', 'full',
                      'description-hash', '{}', ?, ?, 'm4')""",
            (ids["description"], ids["job"], now, now),
        )
        connection.execute(
            "INSERT INTO duplicate_clusters VALUES (?, ?, 'm4-dedup-v1', ?, ?)",
            (ids["cluster"], ids["job"], now, now),
        )
        connection.execute(
            """INSERT INTO job_duplicate_links VALUES
            (?, ?, ?, 'm4-dedup-v1', 'singleton', 1, '[]', 0, ?)""",
            (ids["link"], ids["job"], ids["cluster"], now),
        )
        connection.execute(
            """INSERT INTO duplicate_candidates VALUES
            (?, ?, ?, 'm4-dedup-v1', 0.75, '[]', 'pending', NULL, ?)""",
            (ids["candidate"], ids["job"], ids["other_job"], now),
        )
        connection.execute(
            """INSERT INTO applications
            VALUES (?, ?, ?, 'new', ?, ?)""",
            (ids["application"], ids["job"], str(profile.id), now, now),
        )
        connection.execute(
            """INSERT INTO application_events
            VALUES (?, ?, NULL, 'new', 'created', ?)""",
            (ids["event"], ids["application"], now),
        )
        connection.execute(
            """INSERT INTO job_analyses (
                id, job_id, profile_id, profile_version, analyzer_version,
                description_completeness, requirements_json, evidence_json,
                missing_skills_json, risk_flags_json, prefilter_score, fit_score,
                fit_reasons_json, language_risk_penalty,
                banking_preference_bonus, created_at
            ) VALUES (?, ?, ?, 1, 'legacy-v1', 'full', '{}', '{}', '[]', '[]',
                      60, 70, '["legacy reason"]', 0, 0, ?)""",
            (ids["analysis"], ids["job"], str(profile.id), now),
        )
        connection.execute(
            """INSERT INTO cv_artifacts VALUES
            (?, ?, ?, ?, 1, 'flowcv_txt', 'rule_based', 'legacy.txt', 1, 'ok', ?)""",
            (ids["artifact"], ids["job"], str(profile.id), ids["analysis"], now),
        )

    assert migrate(database) == [4, 5]
    with database.read_connection() as connection:
        for table in (
            "jobs", "job_descriptions", "candidate_profiles",
            "duplicate_clusters", "job_duplicate_links", "duplicate_candidates",
            "applications", "application_events", "job_analyses", "cv_artifacts",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
        analysis = connection.execute(
            "SELECT * FROM job_analyses WHERE id = ?", (ids["analysis"],)
        ).fetchone()
        artifact = connection.execute(
            "SELECT * FROM cv_artifacts WHERE id = ?", (ids["artifact"],)
        ).fetchone()
        assert analysis["fit_score"] == 70
        assert analysis["rules_version"] == "legacy"
        assert artifact["analysis_id"] == ids["analysis"]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_005_preserves_version_004_rankings_and_notifications(
    tmp_path: Path,
) -> None:
    through_004 = tmp_path / "through_004"
    through_004.mkdir()
    migration_root = Path(__file__).parents[1] / "migrations"
    for name in (
        "001_initial.sql", "002_arbeitsagentur_collection.sql",
        "003_normalization_duplicates.sql", "004_fit_analysis_ranking.sql",
    ):
        shutil.copy2(migration_root / name, through_004 / name)
    database = Database(tmp_path / "m5.sqlite3")
    assert migrate(database, directory=through_004) == [1, 2, 3, 4]

    from app.db.repositories import NotificationRepository
    from app.domain.operations import Notification
    from tests.notification_helpers import seed_ranked_vacancies

    profile, seeded = seed_ranked_vacancies(database, 1)
    old_notification = Notification(
        job_id=seeded[0][0].id,
        profile_id=profile.id,
        idempotency_key="legacy-notification-key",
    )
    with database.transaction() as connection:
        NotificationRepository(connection).create(old_notification)

    assert migrate(database) == [5]
    assert migrate(database) == []
    with database.read_connection() as connection:
        assert connection.execute(
            "SELECT id FROM notifications WHERE id = ?", (str(old_notification.id),)
        ).fetchone()["id"] == str(old_notification.id)
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM job_analyses").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM job_rankings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM duplicate_clusters").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_required_sqlite_pragmas(database: Database) -> None:
    with database.read_connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_transaction_rolls_back_on_error(database: Database) -> None:
    job = Job(
        source=JobSource.MANUAL,
        title_raw="Rollback Analyst",
        title_normalized="rollback analyst",
    )
    with pytest.raises(RuntimeError, match="force rollback"):
        with database.transaction() as connection:
            JobRepository(connection).create(job)
            raise RuntimeError("force rollback")

    with database.read_connection() as connection:
        assert JobRepository(connection).get(job.id) is None


def test_foreign_keys_are_enforced(database: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """INSERT INTO applications
                (id, job_id, profile_id, status, created_at, updated_at)
                VALUES ('a', 'missing-job', 'missing-profile', 'new', 'now', 'now')"""
            )


def test_database_path_comes_from_typed_settings(tmp_path: Path) -> None:
    settings = settings_from_mapping(
        {"JOBHUNT_DATABASE_PATH": "custom/jobs.db"}, root=tmp_path
    )
    database = Database.from_settings(settings)
    migrate(database)
    assert database.path == (tmp_path / "custom/jobs.db").resolve()
    assert database.path.exists()
