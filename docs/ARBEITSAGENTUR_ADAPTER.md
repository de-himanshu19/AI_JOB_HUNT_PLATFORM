# Arbeitsagentur Adapter

## Scope

Migration Milestone 2 adds only the Arbeitsagentur acquisition path:

```text
typed search request
→ resilient v6 search client
→ typed summary parser
→ bounded pagination and reference deduplication
→ resilient v4 detail client
→ structured detail/language parser
→ common Job + versioned JobDescription
→ collection service
→ SQLite
```

It does not filter German jobs, score or rank vacancies, apply banking preferences, notify Telegram, generate CVs, alter applications, write CSVs, or expose a UI.

## Legacy concepts reused

From `existing_projects/job_search_agent/search_arbeitsagentur.py`:

- v6 search and v4 detail endpoints;
- public `X-API-Key` web-client header;
- first work-location extraction concept;
- external/original job-link fallback;
- URL-safe base64 reference encoding;
- separate summary and detail requests;
- explicit high-German, English-friendly, and customer-facing phrase dictionaries.

The legacy DataFrame orchestration, negative filtering, score, Telegram sender, sent-history JSON, and “remove fluent German” behavior were not copied.

## Structure

| Module | Responsibility |
|---|---|
| `app/sources/base.py` | Source-independent request/result/error/collected-job contract. |
| `app/sources/arbeitsagentur/models.py` | Typed source summary, details, search page, and language signals. |
| `client.py` | Injectable `requests.Session`, endpoints, reference encoding, timeouts, retries, and fixture client. |
| `parser.py` | Summary/detail structural parsing and language-signal extraction. |
| `adapter.py` | Pagination, exact reference deduplication, detail enrichment, common-model conversion, metrics/status. |
| `app/services/collection.py` | Dry-run planning, run lifecycle, atomic upsert, description versioning, finalization. |
| `app/cli.py` | Safe non-UI command. |

## Configuration

Typed settings and `.env.example` expose:

- `ARBEITSAGENTUR_SEARCH_URL`
- `ARBEITSAGENTUR_DETAIL_URL`
- `ARBEITSAGENTUR_API_KEY`
- `ARBEITSAGENTUR_QUERIES` (optional comma-separated override)
- `ARBEITSAGENTUR_LOCATION`
- `ARBEITSAGENTUR_PUBLISHED_WITHIN_DAYS`
- `ARBEITSAGENTUR_PAGE_SIZE`
- `ARBEITSAGENTUR_MAX_PAGES`
- `ARBEITSAGENTUR_CONNECT_TIMEOUT_SECONDS`
- `ARBEITSAGENTUR_READ_TIMEOUT_SECONDS`
- `ARBEITSAGENTUR_MAX_RETRIES`
- `ARBEITSAGENTUR_BACKOFF_SECONDS`

Default queries are a de-duplicated seed from the legacy search configuration and remain separate from future ranking preferences. CLI `--query` values override the plan for that run.

## HTTP and retry behavior

Every request uses explicit `(connect, read)` timeouts. Timeout, connection, HTTP 429, and HTTP 5xx failures receive bounded exponential backoff. HTTP 400–499 other than 429 are permanent and are not retried. Exhaustion produces a typed error; it does not terminate unrelated queries or details. Logs contain operation, attempt, status, and delay—not headers, API-key values, or response payloads.

## Pagination and exact deduplication

- Source page numbering begins at 1, matching the legacy working request.
- Pagination stops on a reported final page, empty page, repeated page, or configured maximum.
- A failed middle page is recorded and later bounded pages continue.
- Metrics count every page request and successful/failed search/detail request.
- Repeated references across pages or query terms become one source job; all matching search terms remain in structured metadata.
- No title/company similarity or cross-source deduplication occurs.

## Parsed fields

Summary parsing preserves reference, title, company, displayed location/city/region/country, publication date, profession, external URL, source detail URL, search term(s), and optional snippet.

Detail parsing preserves readable combined sections plus responsibilities, requirements, employer description, work locations, employment/contract type, working time, start date, application deadline, original application URL, and source URL. Contact details are intentionally omitted from current persistence.

The adapter stores raw display values separately from conservative lowercase/whitespace normalized title/company fields. The complete raw API payload is not retained.

## Description completeness

- `full`: meaningful text came from the detail response.
- `snippet`: detail text was absent/failed, but a search summary snippet exists.
- `missing`: neither detail text nor snippet exists.

Descriptions are content-hashed and versioned. Repeating identical content does not create another version; changed content does.

## Language behavior

Language metadata separates:

- conservative detected description language/confidence;
- explicit German requirement and level such as C1;
- matched high-German phrases;
- English-language/international signals;
- customer-facing German signals and matched reasons.

No signal excludes a job. `STRICT_GERMAN_EXCLUSION` remains disabled and is not consulted by this adapter. Penalties and ranking are later work.

## Collection-run states

The source result uses `started`, `completed`, `completed_with_errors`, and `failed`. SQLite retains the Milestone 1 enum:

- `running` = started;
- `completed` = completed;
- `partial` = completed_with_errors;
- `failed` = failed.

Runs persist query/page/search/detail counters, jobs found/stored/inserted/updated, error count, bounded error summary, and safe configuration snapshot. Finalization occurs after success, partial collection, adapter exceptions, or persistence rollback.

## Offline dry run

```powershell
python -m app.cli collect arbeitsagentur --dry-run --query "Data Analyst"
```

Dry run is also the default when `--live` is absent. It loads saved JSON fixtures, parses/enriches jobs, optionally reads an existing database in read-only mode to classify would-insert/would-update, and does not migrate, create, or change the database.

Use a different safe fixture directory with `--fixture-dir PATH`.

## Explicit live mode

```powershell
python -m app.cli collect arbeitsagentur --live --query "Data Analyst" --max-pages 1 --page-size 5
```

This is the only CLI mode that enables HTTP and persistence. It was not executed during Milestone 2 implementation.

The pytest smoke case is independently gated:

```powershell
$env:RUN_ARBEITSAGENTUR_LIVE_TEST="1"
python -m pytest -m live tests/integration/test_arbeitsagentur_live.py
```

Do not set this variable during ordinary tests.

## Rollback

No scheduler or background process is enabled, so stopping invocation disables collection. Migration 002 is additive. To roll back data/schema, restore the pre-migration SQLite backup or start with a new clean database; do not hand-edit migration history. Reverting the Milestone 2 application files leaves Milestones 0–1 lifecycle behavior intact.

## Current limitations

- API field variants are fixture-tested but not live-verified in this milestone.
- Language detection is deliberately conservative and is not a general language model.
- No raw-payload archive or contact persistence.
- No source-run-item table; errors and aggregate page/request metrics are retained.
- No scoring, ranking, notifications, fuzzy duplicates, or EnglishJobs.

## Next milestone

Stop pending approval. The next recommended milestone is EnglishJobs after technical/legal review of full-description retrieval.
