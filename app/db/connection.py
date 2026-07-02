"""SQLite connection factory with required safety and concurrency pragmas."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import Settings


class Database:
    def __init__(self, path: Path, busy_timeout_ms: int = 5000):
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        return cls(settings.database_path, settings.sqlite_busy_timeout_ms)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Provide one explicit transaction and always close its connection."""
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

