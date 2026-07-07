# AI Job Hunt Platform

This repository contains the source-independent core for a local job-hunting platform. Migration Milestones 0–7 are implemented: typed configuration, shared domain models, versioned SQLite persistence, audited application-status transitions, two fixture-backed source adapters, explainable cross-source duplicate clustering, deterministic fit analysis/ranking, opt-in Telegram top-20 delivery, and truthful FlowCV generation.

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
- EnglishJobs state and keyword/location collection behind the same collection service and SQLite persistence flow.
- EnglishJobs same-source identity handling using listing IDs, normalized URLs, and deterministic fallback fingerprints.
- Explicit EnglishJobs description completeness handling: `full`, `snippet`, or `missing`.
- Offline fixture dry run and an explicitly opt-in live command.
- Versioned title, company, location, description, and URL normalization.
- Explainable cross-source duplicate clusters with conservative gray-zone review.
- Idempotent offline backfill plus transactional merge, split, and rollback operations.
- Generic versioned candidate-profile import and inspection.
- Evidence-backed full-description fit analysis with explicit missing evidence, penalties, and caps.
- Source-neutral logical-vacancy ranking with visible components and stable ties.
- Immutable analysis/ranking caches keyed by profile, description, and rule versions.
- Offline Telegram preview plus explicit live send/retry with cluster-level idempotency.
- Auditable notification batches, logical-vacancy items, and chunk delivery attempts.
- Offline, job-ID-driven FlowCV generation with immutable provenance, private evidence reports, manual-JD fallback, and optional validated Ollama derivatives.

Not implemented yet: Streamlit pages, scheduling, application submission, PDF/DOCX, cover letters, OpenAI integration, or legacy-data import.

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

## EnglishJobs fixture dry run

State mode dry run:

```powershell
python -m app.cli collect englishjobs --dry-run --state bayern
```

Keyword/location mode dry run:

```powershell
python -m app.cli collect englishjobs --dry-run --query "Data Analyst" --location Germany
```

Dry run uses saved HTML fixtures, resolves same-source identity, reports completeness and collection metrics, and does not create or modify the SQLite database.

Live HTTP and SQLite persistence require an explicit flag:

```powershell
python -m app.cli collect englishjobs --live --state bayern --max-pages 1
```

The normal suite never enables this mode. Review [the adapter guide](docs/ENGLISHJOBS_ADAPTER.md) and [the security checklist](docs/SECURITY_CHECKLIST.md) before any live run.

## Normalize and cluster stored jobs

Milestone 4 commands are offline and operate only on SQLite:

```powershell
python -m app.cli deduplicate backfill
python -m app.cli deduplicate review-list --status pending
```

See [the duplicate-clustering guide](docs/DUPLICATE_CLUSTERING.md) for review,
split, version rollback, and company-alias configuration commands.

## Analyze and rank stored jobs

Milestone 5 commands are offline:

```powershell
python -m app.cli profile import profile.json --profile-key candidate
python -m app.cli analyze --profile-id <profile-id>
python -m app.cli rank --profile-id <profile-id>
```

Only full descriptions receive authoritative fit scores. See
[the fit-analysis guide](docs/FIT_ANALYSIS.md) for profile schema, scoring,
versioning, completeness policy, and deterministic ranking behavior.

## Preview Telegram top matches

Preview is safe and offline:

```powershell
python -m app.cli notify telegram preview --profile-id <profile-id>
```

Actual delivery requires `TELEGRAM_ENABLED=true`, rotated credentials, and the
explicit `--live` flag. See [the Telegram guide](docs/TELEGRAM_NOTIFICATIONS.md)
for selection, chunking, retry, idempotency, and audit commands.

## Generate truthful CV artifacts

Rule-based generation is offline and authoritative:

```powershell
python -m app.cli cv generate --job-id <job-id> --profile-id <profile-id>
python -m app.cli cv generate-manual --description-file <path> --profile-id <profile-id>
python -m app.cli cv list --job-id <job-id>
python -m app.cli cv show <artifact-id>
```

Stored jobs require a full description. Optional Ollama polishing requires both
`--ai-polish` and `--live-ai`; failures retain the rule-based artifact. See
[the CV generation guide](docs/CV_GENERATION.md) for provenance, validation,
cache identity, and artifact-security details.

## Application lifecycle

Supported states are `new`, `shortlisted`, `cv_ready`, `applied`, `skipped`, `rejected`, and `interview`. Every accepted change appends an immutable event. Direct `new → applied` is rejected, and creating a CV artifact does not change an application’s state.

## Security

Before any live integration is enabled, complete [the security checklist](docs/SECURITY_CHECKLIST.md). The credentials found during the audit must be rotated externally; their values are not copied into the unified application or documentation.
