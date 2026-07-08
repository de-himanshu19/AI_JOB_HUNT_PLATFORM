# Legacy Import

Milestone 9 adds a dry-run-first import layer for local legacy files. It does
not modify `existing_projects/`, does not read legacy `.env` files, does not
make network requests, and does not require real MySQL access.

## Supported Sources

- `englishjobs-csv`: scored CSV exports from `englishjobs_scraper`.
- `state-intelligence-csv`: classified/scored state CSV exports from
  `germany-english-job-intelligence`.
- `sent-jobs-json`: `job_search_agent/sent_jobs.json` notification history.
- `master-cv-json`: explicit candidate-profile import from `master_cv.json`.
- `legacy-artifact`: selected TXT CV, evidence, analysis, cover-letter, or
  debug artifacts copied as legacy non-authoritative files.
- `mysql-fixture`: fixture/sample rows through the injectable MySQL reader
  boundary.

CSV job descriptions are imported as `snippet` unless source evidence proves
otherwise. Legacy scores are retained only as reference metadata inside
description structured data; current Milestone 5 analyses and rankings must be
recalculated after import, normalization, and deduplication.

## Workflow

```powershell
python -m app.cli legacy inventory
python -m app.cli legacy dry-run --source englishjobs-csv --path <path>
python -m app.cli legacy backup
python -m app.cli legacy apply --source englishjobs-csv --path <path> --backup-id <id>
python -m app.cli legacy reconcile --batch-id <batch-id>
python -m app.cli legacy verify <batch-id>
python -m app.cli legacy batches
python -m app.cli legacy show <batch-id>
```

Dry-run reads and validates the source, calculates checksums, estimates
creates/updates/skips/conflicts/uncertain records, and writes no database data.
Apply requires a verified backup ID. Re-importing the same source checksum with
the same importer version reuses the prior completed batch and does not create
duplicate jobs, descriptions, profiles, notification mappings, or artifacts.

## Backup Gate

`legacy backup` creates a SQLite backup with the SQLite backup API, records the
path, size, and SHA-256 hash in `legacy_import_backups`, and verifies the file
with `PRAGMA integrity_check`. Apply refuses to run if the backup is missing,
unverified, unreadable, or hash-mismatched.

## Provenance

Migration 007 adds durable import backups, batches, sources, items, mappings,
notification suppressions, and legacy artifacts. Every applied item records the
legacy source type, source checksum, importer version, original identifier,
content checksum, mapping confidence, action, warnings, and target table/id
where applicable.

## Notification History

`sent_jobs.json` records are imported conservatively. Uncertain mappings remain
reviewable and do not suppress future Telegram sends. A suppression is recorded
only when a sent-history identifier maps exactly to one current job that already
has a duplicate-cluster link. Suppressions are stored separately from Milestone
6 delivery rows, so no fake Telegram delivery is created.

## MySQL Boundary

`LEGACY_MYSQL_ENABLED=false` by default. Ordinary implementation and automated
tests use `FixtureMySQLReader`; no real credentials are required. The approved
safe environment names for any later real read-only import are:

- `LEGACY_MYSQL_ENABLED`
- `LEGACY_MYSQL_HOST`
- `LEGACY_MYSQL_PORT`
- `LEGACY_MYSQL_DATABASE`
- `LEGACY_MYSQL_USER`
- `LEGACY_MYSQL_PASSWORD`
- `LEGACY_MYSQL_CONNECT_TIMEOUT_SECONDS`

The real reader boundary permits `SELECT` statements only. Write, DDL, and
migration statements are rejected by design, and no MySQL driver is required by
the core/test installation.

## Scheduler Retirement

Legacy schedulers are not disabled automatically. The safe runbook is:

1. Inventory each legacy scheduler command, working directory, and frequency.
2. Run the unified collectors, deduplication, analysis/ranking, notifications,
   and artifact workflows successfully twice.
3. Compare imported/reconciled legacy state with unified outcomes.
4. Disable one legacy scheduler at a time manually.
5. Record rollback instructions and keep original scripts until final sign-off.
