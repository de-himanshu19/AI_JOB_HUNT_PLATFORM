# Implementation Status

Status date: 2026-07-10

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
- Optional AI derivatives behind dual explicit opt-in; validation failure always retains the rule-based artifact.
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

### Migration Milestone 10

- Safe one-command local pipeline orchestration reusing collection, deduplication, analysis, ranking, and notification-preview services.
- Dry-run behavior uses stored jobs only and makes no external source requests unless `--live-collect` is explicitly supplied.
- Pipeline JSON summaries include collection/completeness metrics, analysis/ranking counts, notification-preview metadata, top jobs, output path, and suggested next actions.
- Pipeline does not generate CVs, send Telegram messages, submit applications, mutate application statuses, alter scoring, or rewrite dashboard behavior.

### Migration Milestone 11

- Additive migration 008 extends application tracking with logical cluster identity, current status alias, priority, notes, follow-up date, CV artifact link, source, indexes, and cluster-aware uniqueness.
- Corrective migration 009 keeps `logical_cluster_id` as non-blocking text metadata so deduplication rebuilds can clear and recreate duplicate clusters without deleting or blocking application tracking rows.
- Application events remain immutable and now include event type and note metadata while preserving existing status history.
- Local CRM service and CLI commands support shortlist, skip, set-status, cv-ready, follow-up, list, due, and history workflows.
- Pipeline top jobs show existing application status and suggest explicit shortlist commands without mutating tracking data.
- CV generation can opt in to `--mark-cv-ready`; without that flag it still has no application-status side effect.
- Dashboard Applications page shows CRM counts, due follow-ups, score context, notes preview, and confirmation-gated actions.

### Migration Milestone 12

- Dashboard CV Workflow page lists generated CV artifacts with job/profile/application context.
- Selected artifacts expose copy-friendly FlowCV TXT content and private evidence reports only after explicit dashboard selection.
- CV artifact reads use stored artifact paths only and handle missing local files gracefully.
- Dashboard and CLI workflows can attach a reviewed CV artifact to application tracking and mark the application `cv_ready`.
- `cv list` supports profile/job filtering, and `cv show` remains metadata-only unless `--text` or `--evidence` is explicitly requested.

### Migration Milestone 13

- Optional OpenAI-compatible and native Ollama Cloud API CV polish providers with `AI_ENABLED=false` and `AI_PROVIDER=rule_based` safe defaults.
- Live AI polish requires explicit CLI/dashboard request and `--live-ai`/confirmation; rule-based CV generation remains offline and authoritative.
- API provider uses user-supplied `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`, timeout, and retry settings without logging secrets, prompts, CV text, or response bodies.
- Strict polish prompt preserves facts, dates, employers, contact details, degree names, language levels, work authorization, and FlowCV-friendly plain-text structure.
- Protected-fact validation gates AI output, rejects unsupported numbers/tools/named facts/stronger wording and broken/private-use characters, and stores AI artifacts only when validated.
- AI artifacts are separate child records linked by `parent_rule_based_artifact_id`; failed attempts keep the rule-based artifact usable and record safe failure metadata.
- Failure categories include `configuration_error`, `safety_not_enabled`, `provider_error`, `timeout`, `validation_failed`, `malformed_response`, and `rate_limited`.
- `cv polish --artifact-id <rule-based-artifact-id> --live-ai` supports polishing an existing rule-based artifact.
- Dashboard CV Workflow lists AI artifact parent/provider/model/prompt/status metadata without triggering live AI on page load.
- Application tracking accepts validated AI artifacts and rejects invalid or missing artifacts.

### Migration Milestone 14

- Portfolio-quality README focused on problem statement, workflow, safety,
  local-first design, setup, daily usage, limitations, and roadmap.
- Mermaid architecture and daily workflow diagrams added for GitHub rendering.
- Demo guide added with safe offline commands, bounded live collection example,
  dashboard launch, CV generation, optional AI polish, application attachment,
  and history review.
- Architecture, safety, and roadmap docs added without changing runtime product
  behavior.
- Screenshot placeholders only; no private images, generated CV artifacts,
  runtime data, secrets, or local database content committed.

### Migration Milestone 15

- EnglishJobs detail extraction now applies strict full-description quality
  checks before marking a description as authoritative `full`.
- EnglishJobs-hosted detail pages can contribute title/company/location metadata
  and full body text when the page contains enough meaningful job content.
- Snippet-only, metadata-only, malformed, redirect, and apply-only detail pages
  remain `snippet` or `missing`; snippets are never promoted to full.
- External clickout/apply URLs are recorded as metadata where available, but
  arbitrary company pages are not broadly scraped.
- Collection and pipeline summaries include detail attempts, success/failure,
  completeness counts, external redirect counts, and parsing error counts.
- Optional `--max-detail-requests` bounds detail fetching for collection demos
  and diagnostics.

### Migration Milestone 16

- Local `daily run` and `daily run-config` CLI commands wrap the existing
  pipeline service without changing scoring, source adapters, CV generation,
  AI polish, Telegram delivery, or application tracking behavior.
- Daily run summaries are written as ignored JSON artifacts under
  `data/daily_runs/` with run/search counts, per-search pipeline summaries,
  errors, timestamps, and output paths.
- A conservative lock file under `data/locks/daily_run.lock` prevents overlap
  and requires manual stale-lock review.
- `config/daily_searches.example.json` documents multiple local search
  configurations; `config/daily_searches.local.json` is ignored for private IDs.
- `scripts/run_daily_jobs.ps1` provides a Windows Task Scheduler entry point
  and writes local logs under `data/logs/`.
- Dashboard Runs & Diagnostics shows recent daily-run summaries passively; page
  browsing never starts a run.

### Migration Milestone 17

- Pipeline requests support explicit `ranking_scope` values: `global` preserves
  existing whole-database ranking behavior, while `current-run` filters ranked
  output to jobs touched by the current collection step or their linked logical
  clusters.
- Pipeline JSON now includes `ranking_scope`, `top_jobs_global`,
  `top_jobs_current_run`, and selected-scope `top_jobs` for backward-compatible
  clarity.
- Daily search configs default to current-run ranking so multi-search daily
  digests show the jobs from each source/search instead of unrelated older
  global results.
- Current-run notification preview is built from scoped ranked jobs and can show
  EnglishJobs `prefilter_only` discovery jobs when `include_prefilter_only` is
  enabled; global notification preview behavior is preserved.
- Dashboard daily-run summaries display ranking scope passively and never start
  a run.

### Migration Milestone 18

- Read-only application analytics service shared by CLI and dashboard.
- Dashboard Applications Analytics page shows job inventory, logical vacancies,
  description completeness, application funnel counts, source quality,
  follow-up tables, recent activity, and saved daily-run summaries.
- CLI `analytics summary --profile-id <id>` emits JSON for the same funnel,
  source, follow-up, recent activity, and daily-run metrics.
- Daily-run JSON parsing skips missing or malformed files safely and never
  starts live runs from dashboard browsing.
- No schema migration, scoring change, source-adapter change, CV/AI change,
  Telegram behavior change, application write-behavior change, or
  `existing_projects/` modification was required.

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
- Milestone 7: generic CV builder/validators/storage, optional AI provider boundary, CV generation service, `migrations/006_cv_generation.sql`, focused tests, and `docs/CV_GENERATION.md`.
- Milestone 8: `app/dashboard`, optional Streamlit extra/launcher, dashboard tests, `.streamlit/config.toml`, and `docs/DASHBOARD.md`.
- Milestone 9: `app/domain/legacy_import.py`, `app/services/legacy_import.py`, `migrations/007_legacy_import.sql`, legacy import CLI commands, focused tests, and `docs/LEGACY_IMPORT.md`.
- Milestone 10: `app/services/pipeline.py`, pipeline CLI command, pipeline tests, and `docs/PIPELINE.md`.
- Milestone 11: application tracking migration/service/repository/CLI/dashboard extensions, focused CRM tests, and `docs/APPLICATION_TRACKING.md`.
- Milestone 12: CV workflow dashboard/query/action extensions, CV artifact CLI improvements, focused tests, and `docs/CV_WORKFLOW.md`.
- Milestone 13: OpenAI-compatible and native Ollama Cloud AI providers, protected-fact validation extensions, `cv polish` CLI workflow, focused provider/CV/dashboard/application tests, and AI configuration docs.
- Milestone 14: portfolio README plus `docs/DEMO.md`,
  `docs/ARCHITECTURE.md`, `docs/SAFETY.md`, and `docs/ROADMAP.md`.
- Milestone 15: EnglishJobs detail extraction heuristics, bounded detail
  diagnostics, updated EnglishJobs tests/fixtures, and `docs/SOURCES.md`.
- Milestone 16: daily-run service/CLI, example config, PowerShell wrapper,
  scheduler docs, daily-run dashboard visibility, and focused tests.
- Milestone 17: pipeline ranking-scope support, current-run daily defaults,
  scoped notification preview, dashboard scope visibility, and focused tests.
- Milestone 18: read-only analytics service, CLI summary command, dashboard
  Applications Analytics page, safe daily-run summary parsing, focused tests,
  and docs.

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
- Fixture-only pytest suite: latest Milestone 14 verification target is
  `python -m pytest`; live smoke tests remain explicitly disabled unless opted
  in.
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
- The Arbeitsagentur detail parser supports the current `stellenangebotsBeschreibung`
  field plus legacy description aliases; the value-safe
  `diagnose arbeitsagentur-detail --live` command reports only field shapes and
  lengths when future contract drift must be investigated.
- EnglishJobs full-description retrieval is intentionally conservative; many listings may remain snippet-only even when a clickout destination is known.
- Bounded raw payload retention is intentionally not enabled; only parsed structured metadata and description text are stored.
- Fit rules are deterministic but intentionally small and require calibration against reviewed vacancies.
- CV generation supports FlowCV TXT only; DOCX/PDF and cover letters remain deferred.
- Real Telegram delivery remains disabled until credentials are rotated and explicit live mode is used.
- Dashboard is local and single-user; no authentication or cloud deployment exists.
- Real MySQL import is not required; the Milestone 9 boundary is fixture-first and read-only by design.
- Credential rotation must be completed externally before live integrations.

## Next recommended milestone

Stop here pending checkpoint approval. Do not begin scheduling, deployment, or
new product functionality without a separate plan.
