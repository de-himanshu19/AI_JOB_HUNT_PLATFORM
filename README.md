# AI Job Hunt Platform

This repository contains the source-independent core for a local job-hunting platform. Migration Milestones 0–2 are implemented: typed configuration, shared domain models, versioned SQLite persistence, audited application-status transitions, and a resilient Arbeitsagentur source adapter.

The five projects under `existing_projects/` are read-only legacy references. The unified core does not import or modify them.

## Current scope

Implemented:

- Root-relative, typed settings with one-time `.env` loading and secret redaction.
- Approved policy defaults: retain German jobs, configurable language-risk penalty, optional strict exclusion disabled, and banking as a ranking bonus.
- Common job, description, candidate, analysis, application, run, notification, and FlowCV-artifact models.
- SQLite with foreign keys, WAL mode, busy timeout, ordered migrations, and transaction rollback.
- Versioned candidate profiles and source/source-job-ID uniqueness.
- Application states and immutable transition history.
- Fixture-only tests with no external calls.
- Arbeitsagentur v6 search and v4 detail parsing behind a source-independent contract.
- Bounded pagination, retries/backoff, source-ID deduplication, description versioning, and collection-run metrics.
- Offline fixture dry run and an explicitly opt-in live command.

Not implemented yet: EnglishJobs, Telegram delivery, scoring/ranking, CV generation integration, AI calls, Streamlit pages, duplicate clustering, or legacy-data import.

## Requirements

- Python 3.11 or newer
- No MySQL, Telegram, OpenAI, Ollama, or source credentials are required

## Setup

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

The exact direct runtime, test, and build dependencies are pinned in `pyproject.toml`.

## Configuration

The application starts safely without a `.env`. To customize local paths or policy:

```powershell
Copy-Item .env.example .env
```

Relative paths are resolved from the repository root, not the shell’s current directory. Feature-specific credentials are validated only when that feature is enabled. Do not copy credentials from `existing_projects/`.

## Initialize or upgrade the database

```powershell
python -m app.db.migrations
```

The default database is `data/job_hunt.sqlite3`. Re-running the command is safe; only unapplied migrations run.

## Run tests

```powershell
python -m pytest
```

Tests use temporary SQLite databases and fixtures only. They do not call Arbeitsagentur, EnglishJobs, Telegram, OpenAI, Ollama, or MySQL.

## Arbeitsagentur fixture dry run

Dry run is the safe default. It parses saved fixtures and reports inserts/updates without creating or changing a database:

```powershell
python -m app.cli collect arbeitsagentur --dry-run --query "Data Analyst"
```

Useful bounded overrides include `--location`, `--published-within-days`, `--max-pages`, and `--page-size`.

Live HTTP and SQLite persistence require an explicit flag:

```powershell
python -m app.cli collect arbeitsagentur --live --query "Data Analyst" --max-pages 1
```

The ordinary test suite never enables live mode. See [the adapter guide](docs/ARBEITSAGENTUR_ADAPTER.md) before any live run.

## Application lifecycle

Supported states are `new`, `shortlisted`, `cv_ready`, `applied`, `skipped`, `rejected`, and `interview`. Every accepted change appends an immutable event. Direct `new → applied` is rejected, and creating a CV artifact does not change an application’s state.

## Security

Before any live integration is enabled, complete [the security checklist](docs/SECURITY_CHECKLIST.md). The credentials found during the audit must be rotated externally; their values are not copied into the unified application or documentation.
