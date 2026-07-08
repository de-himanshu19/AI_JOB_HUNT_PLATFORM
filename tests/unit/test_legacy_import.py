from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.db.connection import Database
from app.db.repositories import LegacyImportRepository
from app.domain.enums import DescriptionCompleteness
from app.domain.legacy_import import LegacySourceType
from app.services.legacy_import import (
    FixtureMySQLReader,
    LegacyImportError,
    LegacyImportService,
    SelectOnlyMySQLReader,
)
from app.services.notifications import NotificationFormatter, NotificationService
from tests.notification_helpers import DUPLICATE_VERSION, RANKING_VERSION, seed_ranked_vacancies


def _service(database: Database, settings) -> LegacyImportService:
    return LegacyImportService(database, settings)


def _englishjobs_csv(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "source", "search_keyword", "search_location", "job_title",
                "company", "location", "published_date", "job_url",
                "description_snippet", "source_type", "fetch_method",
                "scraped_at", "fit_score", "fit_reason", "fit_category",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "source": "EnglishJobs.de",
            "search_keyword": "data analyst",
            "search_location": "muenchen",
            "job_title": "Data Analyst",
            "company": "Example GmbH",
            "location": "Munich",
            "published_date": "June 1",
            "job_url": "https://englishjobs.de/clickout/abc123?sig=secret&e=tracking",
            "description_snippet": "Analyze reporting data with SQL.",
            "source_type": "Scraping",
            "fetch_method": "fixture",
            "scraped_at": "2026-06-19 10:29:35",
            "fit_score": "42",
            "fit_reason": "legacy reason",
            "fit_category": "Medium Match",
        })


def test_englishjobs_csv_dry_run_apply_and_idempotency(
    database: Database, settings, tmp_path: Path,
) -> None:
    csv_path = tmp_path / "legacy englishjobs.csv"
    _englishjobs_csv(csv_path)
    service = _service(database, settings)

    dry_run = service.dry_run(LegacySourceType.ENGLISHJOBS_CSV, csv_path)

    assert dry_run.database_modified is False
    assert dry_run.network_requested is False
    assert dry_run.records_read == 1
    assert dry_run.creates == 1
    assert "CSV descriptions are imported as snippets only" in dry_run.warnings

    backup = service.create_backup(tmp_path / "backups")
    applied = service.apply(
        LegacySourceType.ENGLISHJOBS_CSV, csv_path, backup_id=backup.id
    )

    assert applied.batch_id is not None
    assert applied.creates == 1
    with database.read_connection() as connection:
        jobs = connection.execute("SELECT * FROM jobs").fetchall()
        assert len(jobs) == 1
        assert jobs[0]["source"] == "englishjobs"
        assert jobs[0]["source_job_id"].startswith("clickout_url:")
        description = connection.execute(
            "SELECT * FROM job_descriptions WHERE job_id = ?", (jobs[0]["id"],)
        ).fetchone()
        assert description["completeness"] == DescriptionCompleteness.SNIPPET.value
        structured = json.loads(description["structured_data_json"])
        assert structured["legacy_scores_reference_only"]["fit_score"] == "42"
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_import_items"
        ).fetchone()[0] == 1

    replay = service.apply(
        LegacySourceType.ENGLISHJOBS_CSV, csv_path, backup_id=backup.id
    )

    assert replay.idempotent_replay is True
    with database.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_sent_jobs_json_is_uncertain_without_exact_current_mapping(
    database: Database, settings, tmp_path: Path,
) -> None:
    sent_path = tmp_path / "sent_jobs.json"
    sent_path.write_text(json.dumps(["legacy-ref-1"]), encoding="utf-8")
    service = _service(database, settings)

    dry_run = service.dry_run(LegacySourceType.SENT_JOBS_JSON, sent_path)
    backup = service.create_backup(tmp_path / "backups")
    applied = service.apply(
        LegacySourceType.SENT_JOBS_JSON, sent_path, backup_id=backup.id
    )

    assert dry_run.uncertain == 1
    assert applied.uncertain == 1
    with database.read_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_notification_suppressions"
        ).fetchone()[0] == 0


def test_reliable_sent_history_mapping_suppresses_future_notification_preview(
    database: Database, settings, tmp_path: Path,
) -> None:
    profile, seeded = seed_ranked_vacancies(database, 1)
    sent_path = tmp_path / "sent_jobs.json"
    sent_path.write_text(
        json.dumps([seeded[0][0].source_job_id]), encoding="utf-8"
    )
    service = _service(database, settings)
    backup = service.create_backup(tmp_path / "backups")

    service.apply(LegacySourceType.SENT_JOBS_JSON, sent_path, backup_id=backup.id)

    preview = NotificationService(
        database, formatter=NotificationFormatter()
    ).preview(
        profile_id=profile.id,
        ranking_version=RANKING_VERSION,
        duplicate_algorithm_version=DUPLICATE_VERSION,
    )
    assert preview.selected_count == 0
    with database.read_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_notification_suppressions"
        ).fetchone()[0] == 1


def test_legacy_txt_artifact_is_copied_as_non_authoritative(
    database: Database, settings, tmp_path: Path,
) -> None:
    source = tmp_path / "tailored_cv_flowcv.txt"
    source.write_text("legacy cv text", encoding="utf-8")
    service = _service(database, settings)
    backup = service.create_backup(tmp_path / "backups")

    applied = service.apply(
        LegacySourceType.LEGACY_ARTIFACT, source, backup_id=backup.id
    )

    assert applied.batch_id is not None
    with database.read_connection() as connection:
        row = connection.execute("SELECT * FROM legacy_artifacts").fetchone()
        assert row["authoritative"] == 0
        stored_path = Path(row["stored_path"])
        assert stored_path.exists()
        assert stored_path.read_text(encoding="utf-8") == "legacy cv text"


def test_master_cv_import_creates_explicit_profile_version(
    database: Database, settings, tmp_path: Path, master_cv_data: dict,
) -> None:
    profile_path = tmp_path / "master_cv.json"
    profile_path.write_text(json.dumps(master_cv_data), encoding="utf-8")
    service = _service(database, settings)
    backup = service.create_backup(tmp_path / "backups")

    applied = service.apply(
        LegacySourceType.MASTER_CV_JSON,
        profile_path,
        backup_id=backup.id,
        profile_key="legacy-candidate",
    )

    assert applied.creates == 1
    with database.read_connection() as connection:
        row = connection.execute(
            "SELECT profile_key, version FROM candidate_profiles"
        ).fetchone()
        assert row["profile_key"] == "legacy-candidate"
        assert row["version"] == 1


def test_fixture_mysql_reader_is_reference_only(database: Database, settings) -> None:
    service = _service(database, settings)
    reader = FixtureMySQLReader({"jobs": [{"job_id": "legacy", "job_title": "Analyst"}]})

    plan = service.dry_run(
        LegacySourceType.MYSQL_FIXTURE,
        Path("fixture://mysql"),
        mysql_reader=reader,
    )

    assert plan.records_read == 1
    assert plan.skips == 1
    assert "fixture mysql rows are reference-only" in plan.warnings


def test_select_only_mysql_reader_rejects_write_statements() -> None:
    SelectOnlyMySQLReader.validate_select("SELECT * FROM jobs LIMIT 10")
    with pytest.raises(LegacyImportError, match="SELECT statements only"):
        SelectOnlyMySQLReader.validate_select("DELETE FROM jobs")
