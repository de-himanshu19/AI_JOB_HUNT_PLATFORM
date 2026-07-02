# Overlap and Duplication

## CV tailoring versus standalone job-fit analysis

The standalone `ai-job-fit-analyzer-agent` is not imported by or embedded as code in `ai_cv_tailor`. They are independent implementations. Functionally, however, the CV tailor already contains the analyzer capability and does it with a stronger contract.

| Aspect | `ai_cv_tailor` | `ai-job-fit-analyzer-agent` |
|---|---|---|
| Candidate input | Structured `master_cv.json` with evidence and claim controls | Short unstructured `profile.txt` |
| JD input | Manual UI text | Manual `job_description.txt` |
| Requirement extraction | Deterministic structured fields | Model reads raw text |
| Evidence comparison | Explicit evidence groups and unsupported items | Prompt-generated prose |
| Score | Evidence coverage + role bonus − risk penalties/caps | Model invents percentage within prompt constraints |
| Missing skills | `no_evidence_matches` plus risk flags | Model-generated bullet list |
| Explainability | Per-field matches, counts, rules, reasons | Natural-language explanation only |
| Failure behavior | Rule-based path works offline; AI polish falls back | No fallback if SDK/API fails |
| CV generation | Rule-based FlowCV + optional AI polish | Suggestions and cover letter only |
| Persistence | Output TXT files/session state | Reports and CSV rows |

The future shared analysis service should be extracted from `ai_cv_tailor`: `JobRequirementsAnalyzer`, `EvidenceMatcher`, and `FitScorer`. The model-driven agent may survive only as an optional narrative/cover-letter adapter that consumes the structured analysis. It must not calculate the canonical score or infer new evidence.

The projects’ score values are not interchangeable. A collection-stage keyword score answers “is this listing worth deeper analysis?”; the CV-tailor score answers “how well does verified candidate evidence satisfy this JD?”; the standalone model score is an uncalibrated opinion. Store them separately as `prefilter_score`, `fit_score`, and (if retained) `ai_narrative`, never in one overloaded `score` column.

## The two EnglishJobs implementations

`englishjobs_scraper` and `germany-english-job-intelligence` share the same architecture and nearly the same selectors, request headers, 20-jobs/page assumption, positional card parsing, fixed sleeps, DataFrame contract, and CSV writer. This is forked code rather than two fundamentally different sources.

| Concern | Keyword scraper | State intelligence | Authority |
|---|---|---|---|
| URL mode | Keyword + optional location | German state | Combine both in one EnglishJobs adapter. |
| Parser | Adds search keyword/location and fetch metadata; per-page URL/title drop | Adds state keys; relies on later ID dedup | Base on state parser, merge useful metadata/fallbacks from keyword parser. |
| Pagination | Reads `h1`, assumes 20/page, fixed 2s | Same, with delay argument and totals returned | State controller as base; redesign resilience. |
| Classification | None | Ordered categories | Intelligence. |
| Scoring | Static target title/skills | Category + profile keywords | Intelligence as optional prefilter only. |
| Deduplication | URL + title in-memory | MD5 of source/title/company/city | Intelligence concept, replaced for cross-source matching. |
| Persistence | CSV | CSV + MySQL + run summaries | Intelligence concepts, ported to SQLite. |
| Complete description | No | No | New implementation required. |

The keyword scraper’s huge Germany-wide output illustrates its duplication problem: the same vacancy can be returned for many query terms, and signed clickout URLs can differ by query. The state implementation reduces within-state duplicates but can still repeat one vacancy across states or fail to match it to an Arbeitsagentur posting. Canonical detail URL/source ID and cross-source fingerprints are required.

## Arbeitsagentur/EnglishJobs overlap

There is no code overlap at the protocol level, but there is duplicated downstream policy:

- Three collection projects define their own candidate-specific scoring keywords.
- English/German logic is fragmented between Arbeitsagentur filtering, source assumptions, and CV JD analysis.
- Each project invents a different job dictionary/column schema (`title` vs `job_title`, `city` vs `location`, `published` vs `published_date`, `link` vs `job_url`).
- Each project performs ad hoc duplicate handling before any shared model exists.
- Console/CSV/Telegram output is generated inside collectors rather than downstream services.

Both adapters must stop at a shared raw-to-`Job` boundary. Filtering, scoring, storage, notification, and CV generation then become source-independent.

## Feature ownership today

| Feature | Projects containing it | Authoritative legacy source |
|---|---|---|
| EnglishJobs search | `englishjobs_scraper`, intelligence | Intelligence + keyword URL builder |
| Arbeitsagentur search/detail | `job_search_agent` | `job_search_agent` |
| Telegram | `job_search_agent` sender and duplicated test sender | `telegram_sender.py` |
| Collection scoring | all three collectors | Intelligence prefilter logic, supplemented by configurable bank/location signals |
| Candidate fit scoring | both analysis projects | `ai_cv_tailor` |
| Job storage | intelligence MySQL; sent IDs in agent | Intelligence schema concepts |
| Bank logic | `job_search_agent`; finance evidence in CV tailor | Bank signal from agent; evidence truth from CV profile |
| English-only logic | EnglishJobs source assumption; agent detail rules | Agent rules plus new language detector |
| CV output | `ai_cv_tailor` | `ai_cv_tailor` |

## Main duplicated components to retire

1. Two EnglishJobs `fetch_html()` functions and two heading-count parsers.
2. Two EnglishJobs pagination loops and CSV exporters.
3. Three collection-stage scoring tables plus two unrelated candidate-fit scores.
4. Two Telegram sender functions inside one project.
5. Candidate data repeated in `master_cv.json`, `profile.txt`, config/profile descriptions, scoring tables, prompts, README text, and Python literals.
6. Job metadata expressed with incompatible field names across each pipeline.
7. Relative-path output/report writers in every application.

## Missing—not duplicated—capabilities

These require new code rather than selecting a winner:

- Complete EnglishJobs detail retrieval and canonical source identity.
- Structured Arbeitsagentur detail parsing and description persistence.
- A source-independent `Job` model and adapter contract.
- Real title/company/location/description normalization.
- Cross-source duplicate clusters with explainable match decisions.
- SQLite repositories and migrations.
- Application lifecycle/status event tracking.
- A job-centric dashboard and stored-`job_id` CV workflow.
- Notification chunking/idempotency at job level.
- DOCX/PDF formatters, if later approved.
- Automated unit, fixture, contract, integration, and migration tests.

## Decision

Do not merge entry points or copy whole projects. Extract source-specific acquisition code, define a shared job contract, and rebuild orchestration around repositories and services. The projects are a component library with uneven quality, not five applications that should continue running side by side.
