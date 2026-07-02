from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import settings_from_mapping
from app.db.connection import Database
from app.db.migrations import migrate
from app.db.repositories import JobRepository
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
}


def test_database_creation_from_zero_and_repeatable_migrations(tmp_path: Path) -> None:
    db = Database(tmp_path / "new/db.sqlite3")
    assert migrate(db) == [1]
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
        ).fetchone()["count"] == 1


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

