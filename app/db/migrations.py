"""Small ordered SQL migration runner for the local SQLite database."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from app.config import Settings, repository_root
from app.db.connection import Database


MIGRATION_NAME = re.compile(r"^(?P<version>\d+)_.*\.sql$")


def migration_directory() -> Path:
    return repository_root() / "migrations"


def _available_migrations(directory: Path) -> list[tuple[int, Path]]:
    migrations: list[tuple[int, Path]] = []
    for path in directory.glob("*.sql"):
        match = MIGRATION_NAME.match(path.name)
        if match:
            migrations.append((int(match.group("version")), path))
    migrations.sort(key=lambda item: item[0])
    versions = [version for version, _ in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError("Migration versions must be unique")
    return migrations


def migrate(
    database: Database, *, directory: Path | None = None
) -> list[int]:
    """Apply pending migrations atomically and return versions applied now."""
    directory = directory or migration_directory()
    connection = database.connect()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {
            int(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        applied_now: list[int] = []
        for version, path in _available_migrations(directory):
            if version in applied:
                continue
            sql = path.read_text(encoding="utf-8-sig")
            escaped_name = path.name.replace("'", "''")
            script = (
                "BEGIN IMMEDIATE;\n"
                + sql
                + "\nINSERT INTO schema_migrations(version, name) "
                + f"VALUES ({version}, '{escaped_name}');\nCOMMIT;"
            )
            try:
                connection.executescript(script)
            except sqlite3.Error:
                connection.rollback()
                raise
            applied_now.append(version)
        return applied_now
    finally:
        connection.close()


def initialize_database(settings: Settings) -> tuple[Database, list[int]]:
    database = Database.from_settings(settings)
    return database, migrate(database)


def main() -> int:
    """Initialize the configured local database from the command line."""
    from app.config import get_settings

    settings = get_settings()
    database, applied = initialize_database(settings)
    if applied:
        print(f"Initialized {database.path} (applied migrations: {applied})")
    else:
        print(f"Database is current: {database.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
