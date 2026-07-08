from __future__ import annotations

import csv
import json
from pathlib import Path

import app.cli as cli
from app.config import settings_from_mapping
from app.db.connection import Database


def _settings(tmp_path: Path):
    root = Path(__file__).parents[2]
    return settings_from_mapping(
        {
            "JOBHUNT_DATABASE_PATH": "legacy cli.sqlite3",
            "FIT_RULES_PATH": str(root / "config" / "fit_rules.json"),
            "DEDUP_COMPANY_ALIASES_PATH": str(root / "config/company_aliases.json"),
            "CV_ARTIFACT_ROOT": "artifacts",
        },
        root=tmp_path,
    )


def _csv(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "source", "search_keyword", "search_location", "job_title",
                "company", "location", "published_date", "job_url",
                "description_snippet", "source_type", "fetch_method", "scraped_at",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "source": "EnglishJobs.de",
            "search_keyword": "analyst",
            "search_location": "Germany",
            "job_title": "Operations Analyst",
            "company": "Example GmbH",
            "location": "Berlin",
            "published_date": "June 1",
            "job_url": "https://englishjobs.de/jobs/example-1",
            "description_snippet": "Operations reporting role.",
            "source_type": "Scraping",
            "fetch_method": "fixture",
            "scraped_at": "2026-06-19 10:29:35",
        })


def test_legacy_cli_dry_run_does_not_create_database(monkeypatch, tmp_path, capsys) -> None:
    settings = _settings(tmp_path)
    csv_path = tmp_path / "legacy source.csv"
    _csv(csv_path)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main([
        "legacy", "dry-run", "--source", "englishjobs-csv", "--path", str(csv_path),
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["database_modified"] is False
    assert output["network_requested"] is False
    assert output["records_read"] == 1
    assert not settings.database_path.exists()


def test_legacy_cli_backup_apply_reconcile_and_verify(monkeypatch, tmp_path, capsys) -> None:
    settings = _settings(tmp_path)
    csv_path = tmp_path / "legacy source.csv"
    _csv(csv_path)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main(["legacy", "backup", "--backup-dir", str(tmp_path / "backups")]) == 0
    backup = json.loads(capsys.readouterr().out)

    assert cli.main([
        "legacy", "apply", "--source", "englishjobs-csv", "--path", str(csv_path),
        "--backup-id", backup["id"],
    ]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["batch_id"]
    assert applied["database_modified"] is True
    assert applied["legacy_scores_authoritative"] is False

    assert cli.main(["legacy", "reconcile", "--batch-id", applied["batch_id"]]) == 0
    reconcile = json.loads(capsys.readouterr().out)
    assert reconcile["records_read"] == 1

    assert cli.main(["legacy", "verify", applied["batch_id"]]) == 0
    verify = json.loads(capsys.readouterr().out)
    assert verify["foreign_key_check"] == []

    with Database.from_settings(settings).read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
