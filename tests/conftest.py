from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings, settings_from_mapping
from app.db.connection import Database
from app.db.migrations import migrate


@pytest.fixture
def master_cv_data() -> dict:
    return {
        "personal_info": {
            "full_name": "Test Candidate",
            "professional_title": "Data Analyst",
        },
        "work_experience": {"items": []},
        "skills_bank": {"technical": ["SQL", "Python"]},
        "projects": {"items": []},
    }


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return settings_from_mapping(
        {"JOBHUNT_DATABASE_PATH": "runtime/test.sqlite3"}, root=tmp_path
    )


@pytest.fixture
def database(settings: Settings) -> Database:
    db = Database.from_settings(settings)
    migrate(db)
    return db

