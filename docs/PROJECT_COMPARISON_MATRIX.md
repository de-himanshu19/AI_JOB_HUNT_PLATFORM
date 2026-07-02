# Project Comparison Matrix

## Legend

- **W** — available and working based on code plus prior-run evidence
- **I** — available but incomplete/fragile
- **D** — available but duplicated by another project
- **N** — not available
- **U** — unable to verify without a prohibited/unnecessary live external call

`D/W` and `D/I` retain the quality judgment while flagging duplication. “Working” is not a live-site guarantee.

| Capability | `ai_cv_tailor` | `ai-job-fit-analyzer-agent` | `englishjobs_scraper` | `germany-english-job-intelligence` | `job_search_agent` |
|---|---:|---:|---:|---:|---:|
| Arbeitsagentur search | N | N | N | N | W |
| Arbeitsagentur detail retrieval | N | N | N | N | I |
| EnglishJobs.de search | N | N | D/W | D/W | N |
| EnglishJobs.de detail retrieval | N | N | N | N | N |
| Pagination | N | N | D/W | D/W | N |
| Job normalization | N | N | I | I | I |
| Language detection | I (JD requirements) | N | N | N | I |
| English-only filtering | N | N | I (site assumption) | I (site assumption) | I |
| German-job exclusion | N | N | N | N | I |
| Bank-only filtering | N | N | N | N | I (bonus, not filter) |
| Generic role search | N | N | W | W (all state jobs) | W |
| Job-fit scoring | W | I | D/W | D/W | D/W |
| Fit reasons | W | I | D/W | D/W | D/W |
| Missing-skill analysis | W | I | N | N | N |
| Duplicate detection | N | N | D/I | D/I | I |
| Database storage | N | N | N | W (MySQL) | N |
| CSV or JSON export | I (JSON input/TXT output) | W (CSV/TXT) | W (CSV) | W (CSV) | W (sent JSON only) |
| Telegram notifications | N | N | N | N | W |
| Daily top-job report | N | N | N | I (run summaries) | W (top 10) |
| Candidate-profile storage | W | I | N (rules in code) | I (description in config/DB) | I (rules in code) |
| Job-description analysis | W | I | N | N | I (language phrases only) |
| Tailored CV generation | W | N | N | N | N |
| Rule-based CV fallback | W | N | N | N | N |
| FlowCV output | W | N | N | N | N |
| DOCX or PDF output | N | N | N | N | N |
| Application-status tracking | N | N | N | N | N |
| Local web interface | W (Streamlit) | N | N | N | N |
| Automated tests | N | N | N | N | N |

## Collection/processing emphasis

| Question | Answer |
|---|---|
| Which search EnglishJobs.de? | `englishjobs_scraper` (keyword/location pages) and `germany-english-job-intelligence` (all configured state pages). |
| Which search Arbeitsagentur? | Only `job_search_agent`. |
| Which send Telegram? | Only `job_search_agent`; `send_test_message.py` duplicates its sender. |
| Which score jobs? | Both EnglishJobs projects, `job_search_agent`, both candidate-analysis projects. The score semantics differ. |
| Which store jobs? | Only `germany-english-job-intelligence` stores full job rows in a database. `job_search_agent` stores only sent references. |
| Which contain bank-specific logic? | `job_search_agent` has the strongest explicit bank/company/title weighting; `ai_cv_tailor` has finance/banking evidence rules. No project provides a strict bank-only collector. |
| Which contain English-only logic? | EnglishJobs projects rely on source positioning; `job_search_agent` removes explicit fluent-German requirements and records English signals. None performs robust language classification. |

## Reliability leaders

| Capability | Primary source | Why / qualification |
|---|---|---|
| Arbeitsagentur collector | `job_search_agent` | Only implementation; search and detail endpoints are separated. Add pagination, structured details, retries, and persistence. |
| EnglishJobs collector | `germany-english-job-intelligence` | Broad state coverage, run metadata, and artifacts. Merge the keyword URL mode from `englishjobs_scraper`; neither has detail retrieval. |
| EnglishJobs parser | State parser, informed by keyword parser | Same brittle card model; state version matches the preferred pipeline, keyword version has slightly more metadata/dedup. Consolidate and fixture-test. |
| Pagination | State scraper | Parameterized delay and explicit totals; still assumes 20/page and lacks bounds/retries. |
| Job persistence | Intelligence schema/loader concepts | Only durable job/run schema. Port concepts—not MySQL code—to SQLite. |
| Same-source deduplication | Intelligence deduplicator | Stable IDs are better than per-run drops, but source-inclusive identity cannot dedupe across sources. |
| Collection-stage classification/scoring | Intelligence classifier/scorer | Most explicit categories and reasons. Externalize weights and treat as prefilter only. |
| English/German screening | `job_search_agent` | Only implementation that reads detail content. Refactor dictionaries and add actual language detection. |
| Telegram | `job_search_agent` | Successful-send history is sound. Decouple from collection and add per-job notification records/chunking. |
| Candidate profile | `ai_cv_tailor/data/master_cv.json` | Richest structured source of truth and explicit claim controls. |
| JD analysis/evidence/missing skills | `ai_cv_tailor` | Structured, deterministic, transparent, and AI-independent. |
| Final candidate fit | `ai_cv_tailor` | Evidence score plus risk penalties/caps is auditable; standalone analyzer score is model-generated prose. |
| CV generation/formatter/fallback | `ai_cv_tailor` | Only generator; rule-based FlowCV output is safe default and AI polishing is optional. |
| Narrative analysis/cover letter | `ai-job-fit-analyzer-agent` | Only unique capability, but retain as optional output after structured scoring, not as scoring authority. |
| Configuration | None fully sufficient | `config.py` modules are simple; dotenv use is fragmented. Build one typed root loader with legacy aliases. |
| HTTP error handling | `ai_cv_tailor/src/ollama_client.py` | Best exception/status/JSON handling. Apply its pattern plus retry policy to source adapters and Telegram. |
| Logging/run history | Intelligence `scrape_runs` and `state_scrape_summary` | Best data model; current logging is `print()` and failure finalization is weak. |

## Key matrix conclusions

1. No project already satisfies the unified platform.
2. Complete EnglishJobs descriptions, cross-source duplicate detection, SQLite, full lifecycle status, DOCX/PDF output, and tested shared contracts are genuinely missing.
3. The CV tailor contains job-fit analysis; the standalone analyzer is a different, model-driven scoring system rather than a reusable dependency.
4. Collection-stage scores should not be confused with candidate evidence scores. The future platform should retain a cheap prefilter score and an authoritative profile-fit score as separate fields.
