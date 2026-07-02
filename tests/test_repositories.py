from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.db.connection import Database
from app.db.repositories import CandidateProfileRepository, JobRepository
from app.domain.enums import JobSource
from app.domain.job import Job


def _job(**updates) -> Job:
    values = {
        "source": JobSource.ARBEITSAGENTUR,
        "source_job_id": "source-123",
        "title_raw": "Data Analyst",
        "title_normalized": "data analyst",
        "company_raw": "Example GmbH",
        "company_normalized": "example",
    }
    values.update(updates)
    return Job(**values)


def test_job_repository_create_read_update_and_upsert(database: Database) -> None:
    original = _job()
    with database.transaction() as connection:
        repository = JobRepository(connection)
        repository.create(original)
        loaded = repository.get(original.id)
        assert loaded == original

        updated = original.model_copy(
            update={
                "title_raw": "Senior Data Analyst",
                "title_normalized": "senior data analyst",
                "updated_at": datetime.now(UTC),
            }
        )
        repository.update(updated)
        assert repository.get(original.id).title_raw == "Senior Data Analyst"

    later = datetime.now(UTC) + timedelta(minutes=1)
    incoming = _job(
        title_raw="Reporting Analyst",
        title_normalized="reporting analyst",
        last_seen_at=later,
    )
    with database.transaction() as connection:
        stored, created = JobRepository(connection).upsert(incoming)
        assert created is False
        assert stored.id == original.id
        assert stored.title_raw == "Reporting Analyst"
        assert stored.first_seen_at == original.first_seen_at


def test_source_source_job_id_is_unique_when_present(database: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            repository = JobRepository(connection)
            repository.create(_job())
            repository.create(_job(title_raw="Different", title_normalized="different"))

    with database.transaction() as connection:
        repository = JobRepository(connection)
        one = _job(source_job_id=None)
        two = _job(source_job_id=None)
        repository.create(one)
        repository.create(two)


def test_candidate_profile_versioning(database: Database, master_cv_data: dict) -> None:
    with database.transaction() as connection:
        profiles = CandidateProfileRepository(connection)
        first = profiles.create_version(master_cv_data, profile_key="candidate")
        changed = {
            **master_cv_data,
            "skills_bank": {"technical": ["SQL", "Python", "Power BI"]},
        }
        second = profiles.create_version(changed, profile_key="candidate")

        assert first.version == 1
        assert second.version == 2
        assert profiles.get_active("candidate").id == second.id
        assert profiles.get(first.id).active is False

