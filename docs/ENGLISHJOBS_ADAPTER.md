# EnglishJobs Adapter

## Scope

Migration Milestone 3 adds only the EnglishJobs.de acquisition path:

```text
typed state/query request
→ resilient HTML client
→ typed card parser
→ bounded pagination and same-source identity handling
→ safe internal-detail parsing and conservative clickout resolution
→ common Job + versioned JobDescription
→ collection service
→ SQLite
```

It does not score jobs, rank them, cluster duplicates across sources, notify Telegram, generate CVs, alter applications, write CSVs, schedule background runs, or automate applications.

## Legacy concepts reused

From `existing_projects/germany-english-job-intelligence`:

- state key and slug mapping;
- state URL shape;
- total-count extraction;
- state-page parsing and pagination structure.

From `existing_projects/englishjobs_scraper`:

- keyword/location URL shape;
- job-card parsing fallbacks;
- one-page versus all-pages orchestration concept.

The legacy DataFrame return types, CSV export, hard-coded orchestration, scoring, and standalone pipelines were not copied.

## Structure

| Module | Responsibility |
|---|---|
| `app/sources/englishjobs/url_builder.py` | State and keyword URL construction plus identity URL normalization. |
| `models.py` | Typed raw search records, detail records, and parsed-page containers. |
| `client.py` | Injectable `requests.Session`, timeouts, retries, request delay, safe redirect/clickout handling, and fixture client. |
| `parser.py` | HTML card parsing, selector fallbacks, total-count extraction, publication-date parsing, and detail parsing. |
| `adapter.py` | State/query pagination, repeated-page detection, same-source deduplication, conservative detail enrichment, and common-model conversion. |
| `app/services/collection.py` | Dry-run planning, run lifecycle, atomic upsert, versioned descriptions, and finalization. |
| `app/cli.py` | Safe non-UI entry point for dry-run and explicit live mode. |

## Configuration

Typed settings and `.env.example` expose:

- `ENGLISHJOBS_BASE_URL`
- `ENGLISHJOBS_STATES`
- `ENGLISHJOBS_PAGE_SIZE`
- `ENGLISHJOBS_MAX_PAGES`
- `ENGLISHJOBS_CONNECT_TIMEOUT_SECONDS`
- `ENGLISHJOBS_READ_TIMEOUT_SECONDS`
- `ENGLISHJOBS_MAX_RETRIES`
- `ENGLISHJOBS_BACKOFF_SECONDS`
- `ENGLISHJOBS_REQUEST_DELAY_SECONDS`

State keys are seeded from the legacy intelligence project and remain typed configuration, not hard-coded runtime branching in the adapter.

## Search modes

State mode:

```powershell
python -m app.cli collect englishjobs --dry-run --state bayern
```

Keyword/location mode:

```powershell
python -m app.cli collect englishjobs --dry-run --query "Data Analyst" --location Germany
```

The adapter accepts either mode independently or both in one request. All results still flow into the same common `Job` model and persistence path.

## HTTP and retry behavior

Every request uses explicit `(connect, read)` timeouts. Timeout, connection, HTTP 429, and HTTP 5xx failures receive bounded exponential backoff. HTTP 400–499 other than 429 are permanent and are not retried. A configurable request delay spaces logical requests without exposing headers or source payloads in routine logs.

## URL construction

- State URLs follow the legacy `/in/{state-slug}` shape.
- Keyword/location URLs follow the legacy `/in/{location}/{keyword}` or `/jobs/{keyword}` shape.
- Keywords normalize spaces to underscores.
- Locations normalize spaces to hyphens.
- Unicode characters are preserved through URL encoding.
- Page numbers append only when `page > 1`.

## Parsing and pagination safeguards

- Result cards are read from `div.job.js-job` with title-link fallbacks.
- Missing fields are tolerated; missing-title cards are counted as invalid and reported.
- Total-count extraction reads the page `<h1>` when available.
- Pagination stops on empty page, repeated page, explicit max page, or a page that clearly reports no next page. When the page has no next-link selector but the heading still implies more results, the adapter falls back to the bounded total-count calculation.
- One failed state, query, or page records an error and does not cancel unrelated scopes.

## Description completeness

- `full`: a meaningful description was parsed from an EnglishJobs-hosted detail page.
- `snippet`: only card text is available, or clickout resolution found a canonical destination without a safe full description.
- `missing`: neither detail text nor snippet text is available.

Snippets are never treated as full descriptions.

## Same-source identity behavior

EnglishJobs rows are deduplicated only within the same source in this milestone. Identity preference order is:

1. card listing identifier;
2. normalized listing URL;
3. normalized clickout URL;
4. deterministic fingerprint of title, company, location, and displayed date.

No EnglishJobs row is merged with an Arbeitsagentur row in this milestone.

## Persistence and provenance

The adapter reuses the existing SQLite repositories and collection service.

For each EnglishJobs job it:

- preserves the stable internal job ID across reruns;
- preserves `first_seen_at`;
- updates `last_seen_at`;
- updates mutable listing fields;
- versions descriptions by content hash;
- stores query/state discovery provenance in structured description metadata;
- preserves source URL and canonical destination URL separately when available;
- does not change application state.

## Offline dry run

Dry run is the safe default when `--live` is absent. It uses saved fixtures, parses real adapter code paths, reports would-insert/would-update counts, and makes no database writes.

Use a different safe fixture directory with `--fixture-dir PATH`.

## Explicit live mode

```powershell
python -m app.cli collect englishjobs --live --state bayern --max-pages 1
```

This is the only CLI mode that enables HTTP and SQLite persistence. It should be used only after reviewing source behavior and terms. The live pytest smoke case is independently gated:

```powershell
$env:RUN_ENGLISHJOBS_LIVE_TEST="1"
python -m pytest -m live tests/integration/test_englishjobs_live.py
```

## Rollback

No scheduler or background process is enabled, so stopping invocation disables collection. No Milestone 3 schema migration was required. To roll back data, restore the pre-run SQLite backup or start from a clean database; Milestones 0–2 remain intact if the EnglishJobs files are reverted.

## Current limitations

- Full descriptions are only parsed from EnglishJobs-hosted detail pages represented by the current selectors.
- Clickout resolution records a canonical destination URL conservatively and does not parse arbitrary third-party pages for full descriptions.
- HTML structure drift can still break selectors; fixture coverage and visible parser errors are the first guardrail.
- No cross-source duplicate clustering, ranking, scoring, notifications, or CV generation are included here.

## Next milestone

Stop here pending approval. The next recommended milestone is Milestone 4 normalization and cross-source duplicate clustering.
