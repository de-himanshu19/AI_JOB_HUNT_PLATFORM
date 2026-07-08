# Implementation Status

Status date: 2026-07-08

## Completed

### Migration Milestone 0

- Minimal pinned `pyproject.toml` using Pydantic at runtime and pytest as the only test extra.
- Root `.gitignore` and safe `.env.example`.
- Typed root settings, one-time `.env` loading, root-relative paths, temporary aliases, feature-specific validation, and required secret-name redaction.
- Structured JSON/text logging helpers that omit full candidate profile, CV, JD, and raw source payloads.
- Reproducible setup, database initialization, and test commands in `README.md`.
- Credential-rotation and future-integration controls in `SECURITY_CHECKLIST.md`.

External credential rotation remains a manual security gate. No credential value was copied into the new root application.

### Migration Milestone 1

- Common typed models for jobs, versioned descriptions, candidate profiles, analysis placeholders, collection runs, applications/events, notification idempotency, and FlowCV TXT artifacts.
- Product-policy fields distinguish detected language from explicit German requirements and preserve configurable language penalties/banking bonuses.
- Versioned SQLite migration containing all nine required domain tables plus migration history.
- Foreign keys, WAL mode, configurable busy timeout, stable UUIDs, raw/normalized job fields, and partial source/source-job-ID uniqueness.
- Transaction-scoped repositories for jobs, descriptions, profiles, applications/events, runs, notifications, and CV artifacts.
- Job create/read/update/upsert and candidate-profile versioning.
- Validated application transitions and database-enforced immutable event history.
- Fixture-only configuration, model, database, repository, migration, and lifecycle tests.

### Migration Milestone 2

- Typed/configurable Arbeitsagentur endpoints, public client key, search plan, location, age window, page bounds, timeouts, retry count, and backoff.
- Dedicated `requests.Session` client with injectable transport, connect/read timeouts, bounded exponential retry for timeouts, connection failures, HTTP 429, and HTTP 5xx; permanent 4xx responses are not retried.
- Source-independent collection contract and typed raw summary/detail records.
- v6 summary parser and v4 structured detail parser with full/snippet/missing description semantics.
- Explicit German requirements, German level, English signals, customer-facing signals, and description-language metadata are stored without excluding jobs.
- Bounded pagination beginning at page 1, maximum-page protection, empty/repeated-page stops, failed-middle-page continuation, and stable source-reference deduplication across pages/queries.
- Collection service with atomic job/description persistence, stable internal IDs, first/last-seen behavior, run metrics, partial/failure finalization, and no application-status side effects.
- Migration 002 adds request counters and structured versioned description metadata only.
- Safe fixture dry run and explicit `--live` CLI mode.
- Opt-in live smoke test is disabled unless `RUN_ARBEITSAGENTUR_LIVE_TEST=1`.

### Migration Milestone 3

- Typed/configurable EnglishJobs base URL, state seeds, page size/bounds, connect/read timeouts, retry count, backoff, and per-request delay.
- One EnglishJobs adapter supporting both state searches and keyword/location searches through the shared collection service and SQLite repositories.
- Shared same-source identity handling using listing IDs first, then normalized listing/clickout URLs, then deterministic fingerprints.
- HTML card parsing with selector fallbacks, total-count extraction, Unicode-safe URL building, and visible invalid-card/selectors errors.
- Safe bounded pagination with empty-page stop, repeated-page detection, max-page protection, failed-middle-page continuation, and total-count fallback when no next-page selector is present.
- Safe detail behavior: full descriptions parsed only from reachable EnglishJobs-hosted detail pages; clickout resolution records canonical destination URLs without fabricating full descriptions.
- Explicit `full`, `snippet`, and `missing` description completeness for every EnglishJobs description version.
- Fixture-backed dry-run CLI for both state mode and keyword/location mode, plus an opt-in live smoke test disabled unless `RUN_ENGLISHJOBS_LIVE_TEST=1`.

### Migration Milestone 4

- Deterministic, versioned title, company, location, description, and canonical-URL normalization that preserves raw source values.
- Typed company-alias configuration with a repository-root JSON file and optional path override.
- Layered matching using exact identity, canonical URL, strong fingerprints, and conservative cross-source similarity.
- Seniority-conflict protection and explainable gray-zone candidates that remain separate until human approval.
- Versioned duplicate clusters, job links, and review candidates with one mapping per job and algorithm version.
- Idempotent offline backfill with deterministic identities and no source-row deletion.
- Transactional review merge, rejection, manual split, version rollback, and representative reassignment.
- Offline CLI commands plus normalization matrices, a gold-pair dataset, precision/recall assertions, and rollback tests.

### Migration Milestone 5

- Generic versioned candidate evidence contract covering work, projects, education/training, skills/tools, languages, domains, verified metrics, and preferences.
- Deterministic typed requirement extraction and strict evidence precedence without candidate facts in code.
- Full-description-only authoritative fit scores; snippet/missing descriptions remain explicitly prefilter-only.
- Visible positive components, penalties, score caps, missing evidence, risk flags, reasons, and all input/rule versions.
- Separate profile-driven prefilter and verified fit semantics; no source field affects analysis.
- Immutable analysis cache keyed by job, description, profile, analyzer, rules, and ranking versions.
- Logical-vacancy ranking over Milestone 4 representatives with auditable components and stable tie-breaks.
- Offline profile import/list/show, analyze, analysis-show, and rank CLI commands.
- Migration 004 preserves version-003 jobs, descriptions, profiles, clusters/reviews, applications/events, analyses, and CV-artifact foreign keys.

### Migration Milestone 6

- Source-neutral top-20 selection from latest authoritative stored rankings and active Milestone 4 representatives.
- Cluster/profile/channel reservation and successful-delivery idempotency across both sources.
- Deterministic plain-text formatting and bounded Telegram-safe chunking.
- Injected Telegram client with connect/read timeouts, bounded exponential retry, 429/5xx handling, and permanent-4xx behavior.
- Transactional notification batches, ranked item snapshots, per-chunk attempts, safe error summaries, and remote message IDs.
- Partial chunk failure handling and exact failed-chunk retry without resending successful chunks.
- Offline preview/list/show commands and explicit live-only send/retry commands.
- Concurrency tests proving pending reservations prevent duplicate external sends.
- Migration 005 is additive and preserves migrations 001–004 plus legacy notification rows.

### Migration Milestone 7

- Deterministic FlowCV TXT generation by stored `job_id`, restricted to full descriptions.
- Manual UTF-8 JD fallback with a stable input hash and no invented stored-job provenance.
- Immutable authoritative artifacts linked to exact description, profile, analysis, rules, generator, and formatter identities.
- Private evidence reports preserving evidence hierarchy, missing requirements, risks, and version provenance.
- Additive migration 006 with canonical CV-generation artifacts and durable AI-attempt outcomes while preserving legacy `cv_artifacts` rows.
- UUID-only atomic artifact storage, content-hash verification, collision protection, and cleanup after persistence failure.
- Optional Ollama derivatives behind dual explicit opt-in; validation failure always retains the rule-based artifact.
- CLI generate/manual/list/show workflows with no application-status mutation and no default network request.

### Migration Milestone 8

- Optional exact-pinned Streamlit dashboard dependency and Windows-safe launcher.
- Eight local pages covering overview, jobs, detail, duplicate review, applications, CV preparation, notifications, and runs/diagnostics.
- Thin typed query/view-model/action layers; Streamlit pages contain no SQL, scoring, matching, lifecycle, notification, or CV rules.
- Logical-vacancy default with explicit source-record mode, composable filters, stable sorting, and bounded pagination.
- Explicit confirmation and rerun protections for lifecycle, duplicate, live notification, and optional AI actions.
- Empty/populated database, Unicode, no-network, query, action, launcher, and Streamlit startup tests.
- No migration 007; migrations 001-006 and historical records remain authoritative and readable.

### Migration Milestone 9

- Additive migration 007 for legacy import backups, batches, sources, items, mappings, notification suppressions, and non-authoritative legacy artifacts.
- Verified SQLite backup gate with recorded path, size, SHA-256 hash, readability check, and apply refusal on missing or mismatched backups.
- Dry-run-first local import service for EnglishJobs scored CSVs, state-intelligence classified/scored CSVs, `sent_jobs.json`, explicit `master_cv.json` profile import, selected TXT artifacts, and fixture MySQL rows.
- Idempotent apply keyed by source type, source name, source checksum, and importer version.
- CSV jobs are imported as EnglishJobs source records with snippet descriptions only; raw legacy values and legacy scores are retained as reference metadata, not authoritative analyses/rankings.
- CSV apply routes jobs through the existing Milestone 4 deduplication backfill from the CLI.
- Sent-history import creates notification suppressions only for exact current clustered mappings; uncertain mappings do not suppress Telegram.
- Legacy TXT artifacts are copied into generated storage as immutable, content-hashed, non-authoritative records.
- Candidate profile import remains explicit and versioned.
- MySQL support is fixture-first through an injectable reader boundary; `LEGACY_MYSQL_ENABLED=false` by default and no real credentials or driver are required.

## Legacy concepts reused

- `ai_cv_tailor/data/master_cv.json`: candidate-profile shape, evidence-oriented profile direction, and deterministic/rule-based authority.
- `germany-english-job-intelligence/load/schema.sql`: jobs, profiles, scores, run-history, first-seen, and last-seen concepts—redesigned for SQLite.
- `germany-english-job-intelligence/transform/deduplicator.py`: stable-identity intent, without adopting its source-inclusive MD5 as the internal primary key.
- `job_search_agent/job_history.py`: successful-delivery idempotency intent, represented by the future-safe notifications schema.
- Audit-approved application transition graph and product decisions.

No legacy module is imported, and no file under `existing_projects/` is modified.

## Files added

- Root: `README.md`, `pyproject.toml`, `.gitignore`, `.env.example`.
- Configuration/logging: `app/__init__.py`, `app/config.py`, `app/logging_config.py`.
- Domain: `app/domain/__init__.py`, `enums.py`, `job.py`, `candidate.py`, `analysis.py`, `application.py`, `operations.py`.
- Persistence: `app/db/__init__.py`, `connection.py`, `migrations.py`, `repositories.py`, `migrations/001_initial.sql`.
- Arbeitsagentur: `app/sources/base.py`, `app/sources/arbeitsagentur/{models,client,parser,adapter}.py`.
- EnglishJobs: `app/sources/englishjobs/{models,url_builder,client,parser,adapter}.py`.
- Persistence: `migrations/002_arbeitsagentur_collection.sql` and repository extensions.
- Services/CLI: `app/services/collection.py`, `app/cli.py`.
- Tests: `tests/conftest.py`, `test_config.py`, `test_models.py`, `test_database.py`, `test_repositories.py`, `test_applications.py`.
- Milestone 2 tests/fixtures: `tests/fixtures/arbeitsagentur`, `tests/unit`, `tests/contract`, and `tests/integration`.
- Milestone 3 tests/fixtures: `tests/fixtures/englishjobs`, `tests/unit/test_englishjobs_*`, and `tests/integration/test_englishjobs_*`.
- Documentation: `docs/IMPLEMENTATION_STATUS.md`, `docs/SECURITY_CHECKLIST.md`.
- Adapter documentation: `docs/ARBEITSAGENTUR_ADAPTER.md`, `docs/ENGLISHJOBS_ADAPTER.md`.
- Milestone 4: `app/domain/duplicates.py`, `app/services/{normalization,deduplication}.py`, `migrations/003_normalization_duplicates.sql`, `config/company_aliases.json`, Milestone 4 tests/fixtures, and `docs/DUPLICATE_CLUSTERING.md`.
- Milestone 5: generic candidate/analysis domain contracts, requirements/evidence/prefilter/fit/ranking services, `migrations/004_fit_analysis_ranking.sql`, `config/fit_rules.json`, golden tests/fixtures, and `docs/FIT_ANALYSIS.md`.
- Milestone 6: Telegram integration/notification service, `migrations/005_telegram_notifications.sql`, notification tests, and `docs/TELEGRAM_NOTIFICATIONS.md`.
- Milestone 7: generic CV builder/validators/storage, optional Ollama provider boundary, CV generation service, `migrations/006_cv_generation.sql`, focused tests, and `docs/CV_GENERATION.md`.
- Milestone 8: `app/dashboard`, optional Streamlit extra/launcher, dashboard tests, `.streamlit/config.toml`, and `docs/DASHBOARD.md`.
- Milestone 9: `app/domain/legacy_import.py`, `app/services/legacy_import.py`, `migrations/007_legacy_import.sql`, legacy import CLI commands, focused tests, and `docs/LEGACY_IMPORT.md`.

`docs/MIGRATION_PLAN.md` was updated to record milestone status and the approved product decisions.

## Initialize the database

```powershell
python -m app.db.migrations
```

The command applies pending migrations to `JOBHUNT_DATABASE_PATH`, defaulting to `data/job_hunt.sqlite3`.

## Run tests

```powershell
python -m pip install -e ".[test]"
python -m pytest
```

## Verification result

- Dependency installation from `pyproject.toml`: passed.
- Fixture-only pytest suite: **225 passed, 2 explicitly disabled live smoke tests skipped** at the Milestone 9 verification point.
- Fresh database creation and repeat migration: passed.
- Runtime import/startup without integration credentials: passed.
- Static syntax scan: passed.
- SQLite foreign keys, WAL, and busy timeout: passed.
- EnglishJobs fixture CLI dry-run path: covered in integration tests for both state and keyword/location modes.
- Legacy content fingerprint: compared during final handoff; `existing_projects/` unchanged.
- External credential rotation: pending manual provider/account action and therefore remains the only open Milestone 0 security gate.

## Current limitations

- Fuzzy duplicate matches cannot be perfect; conservative gray-zone candidates require human review.
- Description-language detection and explicit language signals are metadata only; penalties/ranking are deferred.
- The detail parser is fixture-verified but the external API contract can still change; live smoke testing remains opt-in.
- EnglishJobs full-description retrieval is intentionally conservative; many listings may remain snippet-only even when a clickout destination is known.
- Bounded raw payload retention is intentionally not enabled; only parsed structured metadata and description text are stored.
- Fit rules are deterministic but intentionally small and require calibration against reviewed vacancies.
- CV generation supports FlowCV TXT only; DOCX/PDF and cover letters remain deferred.
- Real Telegram delivery remains disabled until credentials are rotated and explicit live mode is used.
- Dashboard is local and single-user; no authentication or cloud deployment exists.
- Real MySQL import is not required; the Milestone 9 boundary is fixture-first and read-only by design.
- Credential rotation must be completed externally before live integrations.

## Next recommended milestone

Stop here pending checkpoint approval. Do not begin Milestone 10 or broader scheduling/cleanup work without a separate plan.
