# Migration Plan

## Principles

- Add the unified application beside `existing_projects/`; do not modify legacy code during extraction.
- Move one capability at a time behind tested contracts.
- Keep rule-based operation available throughout.
- Import data only after dry-run counts and backups.
- A milestone is complete only when its acceptance tests pass; prior entry points remain rollback references until parity is established.

## Milestone 0 — Security and reproducible baseline

**Goal:** make subsequent integration safe and measurable.

**Reuse:** legacy run commands, generated artifacts, `.gitignore` intent, focused dependency lists.

**Add/change:** root `README.md`, `pyproject.toml`, `.gitignore`, `.env.example`, typed `app/config.py`, logging config, CI/local test commands; credential rotation checklist. Do not edit legacy folders without separate approval.

**Acceptance criteria:** root environment installs from one manifest; app config starts with no secrets; secret scanner does not find active credentials outside intentionally excluded legacy evidence; every discovered credential has been rotated; baseline fixture/artifact counts are recorded.

**Tests:** configuration precedence/alias/redaction tests; syntax/lint/test collection.

**Rollback:** remove only newly added root files; legacy projects remain untouched.

**Known limitations:** no unified runtime behavior yet; old credentials may remain in historical repository objects until separately purged.

## Milestone 1 — Domain model, SQLite, and status tracking

**Goal:** establish the source-independent core before any collector migration.

**Reuse:** intelligence `schema.sql`, job upsert/first-seen/last-seen ideas, run tables, CV tailor profile structure, job-agent sent-history semantics.

**Add/change:** `app/domain/*`, `app/repositories/*`, SQLite migrations, profile importer, status transition service, minimal CLI for DB initialization and profile import.

**Acceptance criteria:** SQLite creates from zero; one `Job` shape supports either source; candidate profile is versioned; jobs can be stored/retrieved; allowed statuses and event history work; migrations are repeatable; no MySQL is required.

**Tests:** model validation, repository CRUD/upsert, uniqueness, transaction rollback, migration up/down or forward/backup restore, status transition table tests, Windows path tests.

**Rollback:** restore pre-migration DB backup or delete the newly created local DB; no legacy storage changes.

**Known limitations:** jobs are inserted from fixtures/manual CLI only; no dashboard.

## Milestone 2 — Arbeitsagentur adapter

**Goal:** collect, fully detail, normalize, and store Arbeitsagentur jobs without Telegram coupling.

**Reuse:** `job_search_agent/search_arbeitsagentur.py` endpoint logic, reference encoding, summary parsing, and German/English rules.

**Add/change:** adapter/client/parser, collection service, HTTP retry policy, saved JSON fixtures, source-run records.

**Acceptance criteria:** pagination is bounded and complete for fixture scenarios; every stored job has source identity and original URL; detail JSON is structurally parsed; failures produce partial/completed-with-errors runs; repeated runs update `last_seen_at` rather than duplicate rows.

**Tests:** search/detail parser fixtures, pagination, empty results, malformed JSON, timeout/429/5xx retry, partial failure, idempotent upsert. One opt-in live smoke test, disabled by default.

**Rollback:** disable adapter via config and retain stored rows/provenance; revert new modules/migration only.

**Known limitations:** EnglishJobs absent; language detection remains rule-based initially.

## Milestone 3 — EnglishJobs adapter

**Goal:** collect EnglishJobs state and optional keyword searches into the same model, including the fullest legally/technically available description.

**Reuse:** intelligence state scraper/parser as base; keyword `build_search_url()` and parser metadata from `englishjobs_scraper`.

**Add/change:** EnglishJobs adapter/client/parser, HTML fixtures, detail/canonical URL resolver, completeness flag, per-page run metrics.

**Acceptance criteria:** both URL modes return `JobDraft`; page loops have max/repetition guards; selector failure is visible; stored records distinguish snippets from full descriptions; second run is idempotent.

**Tests:** representative card/heading/detail fixtures, selector fallbacks, zero count, repeated page, failed middle page, signed/tracking URL normalization, Unicode German locations, opt-in live smoke test.

**Rollback:** disable the adapter; retain source rows and runs. No change to Arbeitsagentur data.

**Known limitations:** site/redirect policy may prevent full description retrieval for some listings; mark rather than fabricate completeness.

## Milestone 4 — Normalization and cross-source duplicates

**Goal:** identify the same logical vacancy across both sources while preserving source provenance.

**Reuse:** intelligence stable-ID idea and all raw fields from adapters.

**Add/change:** normalization service, company alias configuration, duplicate clusters/links, review CLI/UI stub, backfill command with versioning.

**Acceptance criteria:** exact source IDs and canonical URLs match deterministically; known cross-source fixture pairs cluster; known near-miss pairs do not; uncertain pairs remain reviewable; rerunning a version is idempotent.

**Tests:** title/company/location normalization matrix, URL normalization, duplicate gold dataset with precision/recall targets, cluster merge/split transaction tests.

**Rollback:** clear links produced by the new algorithm version and restore previous representative mapping; source jobs are never deleted.

**Known limitations:** fuzzy matches cannot be perfect; human review remains necessary for gray-zone scores.

## Milestone 5 — Shared fit analysis and ranking

**Goal:** score stored jobs against the candidate profile with transparent evidence and rank all sources together.

**Reuse:** CV tailor JD analyzer, evidence matcher, strategy selector; intelligence classifier/prefilter; job-agent bank/location signals.

**Add/change:** typed requirements/evidence models, profile-version linkage, analysis/ranking services, configurable/versioned weights, analysis cache.

**Acceptance criteria:** stored full descriptions generate structured requirements, evidence, missing skills, risks, fit score, reasons, and rank components; same input/version is deterministic; unsupported claims never count as evidence; source does not affect fit semantics.

**Tests:** port representative legacy JDs as golden fixtures; unit-test German/ERP/finance risks, evidence precedence, score caps, ranking tie-breaks, profile/version invalidation, snippet-only behavior.

**Rollback:** select previous analysis/ranking version; stored jobs remain intact.

**Known limitations:** rule dictionaries need calibration; snippet-only jobs should receive a completeness warning or deferred deep score.

## Milestone 6 — Telegram top 20

**Goal:** notify only the top 20 new logical vacancies after successful storage/scoring.

**Reuse:** `telegram_sender.py` request shape and successful-send-only history behavior.

**Add/change:** Telegram integration, notification query/formatter/chunker, notification table, CLI/scheduled use case.

**Acceptance criteria:** at most 20 new unnotified logical vacancies across both sources; duplicate cluster sends once; successful messages are not resent; failed sends are retryable; secrets and full response bodies are not logged.

**Tests:** fake Telegram server/client, message length/chunking, ordering, empty set, partial chunk failure, unique constraints, concurrent runs, HTML/special-character content.

**Rollback:** set `TELEGRAM_ENABLED=false`; notification records remain auditable and can be manually reset by an explicit command.

**Known limitations:** Telegram availability and bot permissions are external; no email channel.

## Milestone 7 — CV service by stored `job_id`

**Goal:** generate a truthful tailored CV directly from a stored vacancy, with manual JD fallback.

**Reuse:** CV tailor master profile, analyzer/evidence/strategy, rule-based generator, evidence report, FlowCV formatter, and AI validation/fallback.

**Add/change:** candidate-generalized CV modules, artifact repository, `generate_for_job()` and manual-source path, provider interface, FlowCV TXT output.

**Acceptance criteria:** selecting a stored job requires no copy/paste; rule-based generation works offline; artifacts link job/profile/analysis versions; AI failure preserves the rule-based file; manual JD input still works; no unsupported fact passes configured validators.

**Tests:** golden FlowCV outputs, protected facts/dates/numbers, missing description, provider timeout/invalid JSON/incomplete response, path/collision handling, manual-source workflow.

**Rollback:** disable AI and/or revert formatter/analysis version; prior artifacts are immutable and rule-based output remains available.

**Known limitations:** first release is TXT/FlowCV only. Add DOCX/PDF as a later isolated formatter milestone after template requirements are agreed.

## Milestone 8 — Streamlit dashboard

**Goal:** expose jobs, filters, details, statuses, runs, notifications, and CV Builder in one local UI.

**Reuse:** CV tailor’s Streamlit interaction patterns and result presentation, not its monolithic script.

**Add/change:** dashboard pages/controllers calling application services only.

**Acceptance criteria:** all stored jobs display; filters and duplicate provenance work; original vacancy opens in browser; statuses persist with history; CV Builder receives `job_id`; manual fallback is visible; run/errors and notification state are inspectable; no automatic application action exists.

**Tests:** service/controller unit tests, Streamlit app smoke test, critical UI interaction tests, Windows launch/path test, accessibility/basic layout review.

**Rollback:** CLI/services remain fully usable if dashboard is disabled or reverted.

**Known limitations:** single local user; no auth or cloud deployment.

## Milestone 9 — Legacy import and retirement

**Goal:** optionally import useful legacy job/history/artifact data and stop scheduling legacy entry points.

**Reuse:** EnglishJobs CSVs, `sent_jobs.json`, fit reports/tracker, CV outputs, intelligence MySQL data if still available.

**Add/change:** dry-run importers, reconciliation report, backup/export tooling, operator runbook.

**Acceptance criteria:** source counts/checksums reconcile; imports are idempotent; uncertain mappings are reported; Telegram history prevents unwanted resend where mappings are reliable; legacy schedulers are disabled only after two successful unified runs.

**Tests:** importer fixtures, malformed/old schemas, duplicate imports, interrupted transaction, MySQL-to-SQLite sample, notification mapping.

**Rollback:** restore SQLite backup and re-enable legacy scheduler; imported data is never the only copy until sign-off.

**Known limitations:** old signed EnglishJobs links may be expired; historic data lacks full descriptions and may not map cleanly across sources.

## Recommended first implementation milestone

Begin with Milestone 0 and then Milestone 1 as the first functional slice: typed configuration, the common `Job`/candidate/application models, SQLite migrations/repositories, and fixture-driven tests. Starting with a collector would merely reproduce the existing schema fragmentation. A stable core lets every later adapter return the same object and makes status/notification/CV linkage correct from day one.

