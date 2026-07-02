# Codebase Audit

## Scope and method

This audit covers the five legacy projects under `existing_projects/` as inspected on 2026-07-02. The legacy directories were treated as read-only. No live requests were sent to Arbeitsagentur, EnglishJobs.de, Telegram, MySQL, Ollama, or OpenAI. “Working” means the implementation is internally coherent and/or generated artifacts show that it ran previously; it does not mean the external integration was revalidated during this audit. All 40 authored Python files parse successfully. No automated test files or coverage configuration exist, so measured test coverage is 0%/not available.

Generated artifacts provide useful evidence: the EnglishJobs keyword scraper produced a 31,552-row CSV; the state pipeline produced exports for 16 states; the job agent has 180 sent references; the fit analyzer produced reports and tracker rows; and the CV tailor produced FlowCV text, an evidence report, debug output, and Streamlit printouts. These are prior-run artifacts, not current live verification.

## 1. `ai_cv_tailor`

### Purpose and actual behavior

The stated purpose is a local Streamlit CV tailor. Despite the stale README claim that AI integration is still a placeholder, the current code is a substantial application. It accepts a pasted job description, reads a structured master CV, performs deterministic JD extraction and evidence matching, calculates an evidence-based fit score, selects a CV strategy, creates a FlowCV-ready plain-text CV and private evidence report, and can optionally polish wording through local or cloud Ollama. AI output is validated and falls back to rule-based content.

This project already embeds a stronger job-fit analyzer than the standalone `ai-job-fit-analyzer-agent`: `analyze_job_description()` → `match_evidence()` → `select_cv_strategy()` produces structured, explainable results before CV generation.

### Entry points and run commands

- Main entry point: `app.py` (Streamlit script; UI and orchestration begin at lines 192 and 209).
- Install: `python -m pip install -r requirements.txt`.
- Run from this project directory: `streamlit run app.py`.
- Optional external prerequisite: an Ollama server for local AI, or `OLLAMA_API_KEY` for Ollama Cloud. Rule-based mode needs neither.

### Important files

| File | Responsibility |
|---|---|
| `app.py` | Streamlit UI, session state, manual JD input, pipeline orchestration, display, file writes, and TXT downloads. `build_job_tracker_summary()` at line 165 creates copyable metadata; generation is lines 298–430. |
| `src/jd_analyzer.py` | Rule-based role, skill, tool, responsibility, language, seniority, finance/ERP risk, and job-metadata extraction. Public function: `analyze_job_description()` at line 611. |
| `src/evidence_matcher.py` | Matches JD items against work, projects, courses, education, skills, and achievements; returns evidence groups, unsupported items, risk flags, and confidence. Public function: `match_evidence()` at line 318. |
| `src/strategy_selector.py` | Applies role bonus, risk penalties, score caps, recommendations, section priority, and CV strategy. Public function: `select_cv_strategy()` at line 98. |
| `src/cv_generator.py` | Candidate-specific skill/experience/project/certificate selection and FlowCV plain-text formatting. `generate_flowcv_text()` is line 1427; `polish_experience_section_with_ollama()` is line 1468. |
| `src/report_generator.py` | Creates a structured private evidence/fit report, including matches, risk cautions, unsupported claims, and final recommendation. `generate_evidence_report()` is line 111. |
| `src/ollama_client.py` | Local/cloud Ollama HTTP client with timeouts and readable error returns. `ask_ai()` is line 16; compatibility wrapper `ask_ollama()` is line 106. |
| `src/ai_cv_writer.py` | Optional full-CV or section-level AI polishing, response cleanup, protected-fact checks, debug output, and rule-based fallback. Public functions begin at lines 261 and 371. |
| `src/utils.py` | Empty placeholder; no current responsibility. |
| `src/__init__.py` | Package marker only. |
| `data/master_cv.json` | Rich candidate profile/evidence store: personal information, 12 role families, 4 work records, education, training, 34 certifications, 5 projects, skills, metrics, claim rules, strategies, and FlowCV preferences. |
| `prompts/*.txt` | Placeholder prompt files; no source code references them. Current prompts are embedded in Python. |
| `outputs/*` | Generated FlowCV TXT, evidence report, and last raw AI response debug file. |

### Inputs, outputs, dependencies, configuration, and storage

- Inputs: `data/master_cv.json`; a manually pasted free-text JD; UI-selected target role, provider, model, and polish mode.
- Structured internal outputs: JD-analysis, evidence-result, strategy-result, and extracted job metadata dictionaries held in Streamlit session state.
- Durable outputs: `outputs/tailored_cv_flowcv.txt`, `outputs/evidence_fit_report.txt`, `outputs/last_ai_response_debug.txt`; browser downloads for final CV, rule-based backup, and evidence report. No DOCX or PDF generator exists; PDFs in `printouts/` are prior UI printouts rather than generated resume PDFs.
- Dependencies declared: `streamlit`, `requests`, `python-dotenv`.
- Environment: optional secret `OLLAMA_API_KEY`. No `st.secrets` usage.
- Configuration: provider URLs and model defaults are hard-coded in `src/ollama_client.py`; UI defaults are duplicated in `app.py`; most candidate policy is in JSON but significant candidate rules remain in Python.
- Persistence: flat JSON input and TXT output only. There is no database and no application-status persistence.

### Current strengths

- Deterministic analysis and safe rule-based CV generation work without AI.
- Evidence is separated by source and missing evidence is explicit.
- German-language and ERP/SAP risks affect the score.
- AI failures, incomplete sections, changed numbers, lost protected text, and some stronger verbs trigger fallback or warnings.
- The candidate profile is much richer and more structured than `profile.txt` in the standalone analyzer.

### Incomplete, experimental, broken, or unused areas

- JD input is manual only; it cannot load a stored `job_id`.
- No DOCX/PDF generation, database, central status tracking, or source integration.
- Metadata extraction contains employer/location-specific rules and can misparse arbitrary JDs.
- Many candidate facts, company names, dates, headlines, language levels, and permitted metrics are duplicated in Python rather than read exclusively from `master_cv.json`.
- Full AI validation checks structure and selected facts but cannot prove semantic faithfulness; risky-word detection is heuristic.
- `prompts/` and `src/utils.py` are unused; README is materially stale.
- All relative paths assume the process starts in the project directory.

### Tests and hard-coded values

No tests exist. Important hard-coded values include local URL `http://localhost:11434/api/generate`, cloud URL `https://ollama.com/api/generate`, models `llama3.2:3b` and `gpt-oss:20b`, long timeouts (180/360 seconds), relative data/output paths, candidate/company-specific values, fixed language lines, fixed confirmed metrics, and role-specific thresholds. No hard-coded secret was found in authored source.

## 2. `ai-job-fit-analyzer-agent`

### Purpose and actual behavior

This is a console-based, model-driven job-fit analyzer. It asks for company and title, reads `profile.txt` and `job_description.txt`, sends both to an OpenAI Agents SDK `Agent`, and requests a score, decision, fit reasons, missing skills, CV suggestions, and a short cover letter. It saves timestamped analysis and cover-letter TXT files and appends an entry to `job_tracker.csv`.

### Entry points and run commands

- Entry point: `main.py:main()` at line 163.
- Install: `python -m pip install -r requirements.txt`.
- Run from the project directory: `python main.py`.
- Required external configuration: `OPENAI_API_KEY` in `.env`; network access to the SDK’s default provider/model.

### Important files

| File | Responsibility |
|---|---|
| `main.py` | Entire workflow. `load_file()` reads text; extraction helpers parse the model’s prose; `save_unique_reports()` creates TXT reports; `save_to_job_tracker()` appends CSV; `job_fit_agent` embeds the prompt; `main()` invokes `Runner.run_sync()`. |
| `profile.txt` | Unstructured candidate profile input. |
| `job_description.txt` | Manually maintained JD input. |
| `analysis_result.txt` | Older generated analysis artifact; current `main()` does not write this path. |
| `reports/*.txt` | Timestamped full analysis and extracted cover letter. |
| `job_tracker.csv` | Append-only analysis tracker, not an application lifecycle tracker. Existing artifact schema differs from the current seven-column writer, indicating version drift. |
| `requirements.txt` | `openai-agents`, `python-dotenv`. |

### Inputs, outputs, configuration, and storage

- Inputs: two console strings, `profile.txt`, and `job_description.txt`.
- Output format: free-form model text constrained by a prompt; regex-derived score/decision; TXT reports; CSV tracker rows.
- Environment: `OPENAI_API_KEY` is consumed indirectly by the Agents SDK after `load_dotenv()`.
- Model: no model name is specified, so behavior and cost depend on SDK defaults.
- Storage: TXT and CSV only; no database, deduplication, status tracking, or linkage to collected jobs.

### Current strengths and limitations

Prior reports show the workflow has run. It is simple and produces useful narrative fit reasons, missing skills, CV suggestions, and cover letters. However, score extraction uses the first percentage in model output, decision extraction is substring-based (the order can turn “Maybe Apply” into “Apply”), the section parser depends on exact headings, output is nondeterministic, there is no response schema validation, and all truthfulness depends on the prompt. There is no retry/error handling around `Runner.run_sync()` and no rule-based fallback.

No tests exist. Relative paths require project-root execution. Candidate name and prompt behavior are hard-coded. A probable OpenAI API secret exists in `.env` under `OPENAI_API_KEY`; it is documented only in masked form in `ENVIRONMENT_VARIABLES.md`.

## 3. `englishjobs_scraper`

### Purpose and actual behavior

This is a Germany-wide, keyword-driven EnglishJobs.de search scraper. It builds search URLs, downloads result HTML, parses job cards, derives page count from the heading, paginates, deduplicates by URL/title, scores snippets with static profile keywords, ranks the result, and exports CSV.

### Entry points and run commands

- Entry point: top-level block in `main.py` at line 14.
- Install: `python -m pip install -r requirements.txt`.
- Run from the project directory: `python main.py`.
- No environment values are used; the present `.env` is empty.

### Important Python files

| File | Responsibility |
|---|---|
| `main.py` | Runs 14 fixed keyword searches, combines/deduplicates, scores, previews, and exports. |
| `config.py` | EnglishJobs base URL, browser-like headers, assumed 20 jobs/page, output folder. |
| `url_builder.py` | `build_search_url()` creates Germany-wide or location/keyword URLs and page query. |
| `fetcher.py` | `fetch_html()` performs one GET with a 20-second timeout and returns HTML/`None`. |
| `parser.py` | `parse_jobs()` parses `div.job.js-job` cards into a DataFrame; `extract_total_jobs_count()` parses the first number from `h1`. |
| `scraper.py` | `scrape_one_page()` and `scrape_all_pages()` coordinate pagination and a two-second delay. |
| `scorer.py` | Static title/skill/negative scoring, fit reasons/categories/actions, and ranking. |
| `exporter.py` | Creates parent folders and writes UTF-8-SIG CSV. |

### Data contracts and persistence

- Input: fixed keyword list and optional location string.
- Output columns: source, search keyword/location, title, company, location, displayed date, clickout URL, description snippet, source/fetch metadata, timestamp, fit score/reason/category/action.
- Dependencies actually needed: `requests`, `beautifulsoup4`, `lxml`, `pandas`. The 100-line pinned requirements file is an environment dump containing many unused packages and future-dated versions.
- Persistence: CSV only. The main generated CSV contains 31,552 rows, proving a prior run.

### Working and incomplete areas

Search, pagination, card parsing, deduplication, scoring, and CSV export have prior-run evidence. It does not open each job page or retrieve a complete description. The `job_url` is often a signed clickout link, so canonical identity and longevity are weak. The scraper assumes exactly 20 items per page and a numeric `h1`; it has no retry, backoff, 429 handling, session reuse, robots/terms guard, or maximum-page safety limit. Failed middle pages are silently skipped. HTML selectors and positional parsing are brittle. It does not perform language detection; “English-only” is inferred from the website. It has no database, Telegram, daily history, status tracking, or tests.

Hard-coded values include the site URL, browser headers, fixed keyword list, relative output path, delays, timeout, score weights, and candidate-specific role preferences. No secret or machine-specific absolute path was found.

## 4. `germany-english-job-intelligence`

### Purpose and actual behavior

This is the most complete EnglishJobs pipeline. It scrapes all 16 configured German state pages, parses result cards, creates deterministic job IDs, removes duplicates, classifies roles, scores them, exports a CSV per state, upserts jobs and profile-specific scores into MySQL, and records run/state summaries.

### Entry points and run commands

- Main entry point: top-level block in `main.py` at line 20.
- Install: `python -m pip install -r requirements.txt`.
- Database initialization: execute `load/schema.sql` against MySQL, then call `load.db_loader.load_master_data()` from the project directory (there is no dedicated CLI for this step).
- Run: `python main.py`.
- All commands assume the project directory is the current directory.

### Important files

| File | Responsibility |
|---|---|
| `main.py` | Orchestrates state scrape, deduplication, classification, scoring, per-state CSV, MySQL load, and run summaries. |
| `config.py` | EnglishJobs URL/headers, page size, 16 state slugs/names, job-category reference data, and candidate profile description. |
| `extract/url_builder.py` | `build_state_url()` creates state/page URLs. |
| `extract/fetcher.py` | Single-request HTML fetch with 20-second timeout. |
| `extract/parser.py` | Parses state result cards and total count. |
| `extract/state_scraper.py` | Paginates a state and returns `(DataFrame, total_jobs, total_pages)`. |
| `transform/cleaner.py` | Empty; no normalization is implemented. |
| `transform/deduplicator.py` | Normalizes by lowercase/strip, hashes source/title/company/city with MD5, adds IDs, and drops duplicates. |
| `transform/classifier.py` | Assigns one static career category, primarily from title. |
| `transform/scorer.py` | Adds static profile/category scores, reasons, fit bands, actions, and ranking. |
| `utils/exporter.py` | Writes UTF-8-SIG CSV. |
| `load/database.py` | Builds a MySQL SQLAlchemy engine from five environment variables. |
| `load/db_loader.py` | Loads master data, upserts jobs/scores, and creates/updates run and state-summary rows. |
| `load/schema.sql` | Seven-table MySQL schema: states, runs, summaries, jobs, categories, profiles, scores. |

### Data contracts, dependencies, environment, and persistence

- Input: all configured state pages; static target profile/category configuration.
- Job output: source/state/title/company/city/date/clickout URL/snippet/timestamp/job key/job ID/category/score/reason/category/action.
- Dependencies: focused and accurate—`requests`, BeautifulSoup, `lxml`, `pandas`, SQLAlchemy, PyMySQL, dotenv.
- Environment: required `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`.
- Persistence: CSV plus MySQL upserts and run history. Existing per-state files show prior execution.

### Current strengths and limitations

It has the strongest EnglishJobs persistence, source-run logging, classification, and same-source deduplication. SQL queries are parameterized and passwords are URL-encoded. However, it still stores only card snippets and signed clickout URLs, not complete descriptions. Deduplication includes `source`, so it cannot detect cross-source duplicates; title/company/city normalization is only lowercase/strip; changed titles create new IDs. The MySQL-only implementation conflicts with the desired SQLite target. `insert_jobs_and_scores()` returns bare `None` on empty input while `main.py` unpacks two values, so an empty state can crash. Database setup/master-data ordering is undocumented and not automated. Missing env values can fail at `quote_plus(None)`. There is no exception-safe run-finalization, so failed runs may remain `started`. “new_jobs_inserted” counts upserts, not truly new rows. `README.md` and `transform/cleaner.py` are empty. No tests exist.

A probable database password is present in `.env`; it is masked in the environment report. Other hard-coded values include site URL/headers, profile name/description, states, categories, relative exports, score weights, and delays.

## 5. `job_search_agent`

### Purpose and actual behavior

This is the only Arbeitsagentur collector and the only Telegram notifier. It searches 32 fixed role terms against the v6 search endpoint, parses summary JSON, removes basic negative matches, deduplicates by Arbeitsagentur reference, fetches v4 detail JSON for every remaining job, removes explicit fluent-German requirements, derives English/German-risk flags, scores jobs with a banking/profile/location heuristic, excludes already-notified references, sends the top 10 new jobs to Telegram, and records sent references only after a successful send.

### Entry points and run commands

- Preferred daily wrapper: `python run_daily_job_agent.py`.
- Direct equivalent: `python search_arbeitsagentur.py`.
- Telegram connectivity test: `python send_test_message.py`.
- Static company-link report: `python search_company_careers.py`.
- Dependencies are not declared in a requirements file; imports require `requests`, `pandas`, and `python-dotenv`.

### Important Python files

| File | Responsibility |
|---|---|
| `run_daily_job_agent.py` | Thin wrapper around `search_arbeitsagentur.main()`. |
| `search_arbeitsagentur.py` | Search/detail requests, summary JSON parsing, language filtering, deduplication, scoring orchestration, top-job formatting, Telegram send, and console reporting. Key functions: `search_jobs_for_role()` line 40, `fetch_job_details()` line 191, `filter_german_fluent_jobs()` line 242, `main()` line 309. |
| `config.py` | Fixed target roles, negative keywords, and unused target-location list. |
| `job_scorer.py` | Banking-company, target-title, profile, city, English, and German-risk scoring. `calculate_score()` is line 118. |
| `job_history.py` | Loads/saves `sent_jobs.json`, filters new references, and marks successfully notified jobs. |
| `telegram_sender.py` | Telegram Bot API send with required env checks and 20-second timeout. |
| `send_test_message.py` | Duplicated notifier used for a live test; lacks a timeout. |
| `search_company_careers.py` | Static list of 13 bank/fintech career-site links and message formatter; it does not search those sites. |

### Data contracts, environment, and persistence

- Search input: fixed terms, location `Deutschland`, first page only, size 10, published within seven days.
- Search output fields: source, search role, title, company, city, published date, profession, reference, link. Detail JSON is immediately serialized to lowercase text and discarded; it is not stored as structured data or as a complete description.
- Environment: required secret `TELEGRAM_BOT_TOKEN` and secret/sensitive `TELEGRAM_CHAT_ID`.
- Persistence: `sent_jobs.json` only. It tracks notification IDs, not jobs or applications. No CSV/database output from the main pipeline.

### Current strengths

- Only implemented Arbeitsagentur search and detail retrieval.
- Only successful-delivery-aware notification history.
- Useful explicit German-blocker, English-signal, and customer-facing German-risk rules.
- Detail requests have timeouts and top jobs are ranked before notification.

### Incomplete, experimental, and broken areas

- Search pagination is fixed to page 1, so only up to 10 results per term are seen.
- Full detail JSON is converted to a string and thrown away; no normalized description is returned or stored.
- Requests have no exception handling, retry/backoff, rate-limit handling, or shared session. One network error can abort the run.
- The score is not capped at 100 and uses only summary fields plus two booleans; it does not score full descriptions.
- “Bank-only” is a 30-point bonus, not a strict filter. The project searches generic analyst and German terms too.
- “English-only” is not enforced: explicit fluent-German jobs are excluded, but German-heavy jobs remain with a penalty.
- Top limit is 10 rather than the future requirement of 20.
- One large Telegram message can exceed platform limits; there is no chunking or parse-mode escaping.
- The empty-results message is sent repeatedly because no run-level notification record exists.
- Static company-career functionality is currently commented out of the main flow.
- `TARGET_LOCATIONS` is unused; greeting contains the literal placeholder `USER`.
- There is no central store, job model, status tracking, dashboard, or automated tests.

### Secrets and hard-coded values

The source contains the public Arbeitsagentur client key label `X-API-Key: jobboerse-jobsuche`; this appears to be the public web-client key, but it should still be isolated in source-adapter configuration. A probable Telegram bot token and chat ID exist both in `.env` and in plaintext notes in `telegram.txt`; masked details are in `ENVIRONMENT_VARIABLES.md`. Hard-coded values also include API versions/URLs, target terms, language dictionaries, bank/company lists, cities, request sizes/time windows, relative history path, top-10 limit, and a user-specific test greeting.

## Exact workflow/function index

### Job collection

| Concern | Exact implementation | Assessment |
|---|---|---|
| Arbeitsagentur search/call/summary JSON | `job_search_agent/search_arbeitsagentur.py:search_jobs_for_role()` lines 40–86 | Working structure; first page only; no exception handling. |
| Arbeitsagentur link | `get_job_link()` lines 28–37 | External URL or reference detail URL. |
| Arbeitsagentur detail retrieval | `fetch_job_details()` lines 191–208 | Calls v4 detail endpoint; returns lowercase JSON string rather than a structured job. |
| Arbeitsagentur detail parsing | No dedicated parser; `json.dumps(data).lower()` at lines 203–208 | Incomplete. |
| EnglishJobs keyword search | `englishjobs_scraper/url_builder.py:build_search_url()` and `scraper.py:scrape_all_pages()` | Prior-run evidence; brittle HTML contract. |
| EnglishJobs state search | `germany-english-job-intelligence/extract/url_builder.py:build_state_url()` and `state_scraper.py:scrape_state_jobs()` | Strongest current collector coverage. |
| EnglishJobs request/parsing | Both projects’ `fetcher.py:fetch_html()` and parser functions | Near-duplicated; state pipeline is preferred base. |
| EnglishJobs complete description | None | Not available. Card snippet only. |
| Pagination | Both scraper controllers; none in Arbeitsagentur | Incomplete overall. |
| Failure/retry/rate limits | Fetchers return `None` on request error; fixed sleeps | Timeout exists; retries, backoff, 429 handling, and run recovery do not. |

### Job processing

| Concern | Exact implementation | Assessment |
|---|---|---|
| Title/company/location cleaning | No substantive implementation; `transform/cleaner.py` is empty | Missing. Lowercase/strip is used only locally. |
| Language detection/exclusion | Arbeitsagentur blocker/signal functions at lines 211–262; CV tailor JD language extraction at `jd_analyzer.py:254` | Phrase rules, not general language detection. |
| Banking logic | `job_search_agent/job_scorer.py:BANKING_COMPANIES` and `calculate_score()` | Bonus only, not filter. |
| Data Analyst filtering/classification | Fixed search terms in scraper mains; `transform/classifier.py:classify_job()` | Classification exists; no shared filter. |
| Location rules | `job_search_agent/job_scorer.py:GOOD_CITIES`; state URL scope | Candidate-specific scoring, not normalized eligibility rules. |
| Collection-stage scoring/ranking | Three different heuristic scorers | Duplicated and inconsistent. State intelligence scorer is the strongest collection-stage base. |
| Evidence fit/missing skills | `ai_cv_tailor/src/evidence_matcher.py:match_evidence()` | Strongest deterministic implementation. |
| Final fit score/reason | `ai_cv_tailor/src/strategy_selector.py:select_cv_strategy()` | Strongest explainable candidate-fit implementation. |
| Duplicate detection | URL/title drops; Arbeitsagentur reference; state MD5 source/title/company/city | No cross-source fuzzy/canonical duplicate detection. |

### Notifications and reporting

| Concern | Exact implementation | Assessment |
|---|---|---|
| Telegram send | `job_search_agent/telegram_sender.py:send_telegram_message()` | Best available; needs configuration injection, chunking, retries, and safe logging. |
| Top selection | `search_arbeitsagentur.py:new_jobs_df.head(10)` line 383 | Working but wrong future limit and not source-independent. |
| Message formatting | Inline at lines 372–405 | Coupled to collector and hard-coded. |
| CSV | Both EnglishJobs exporters; fit analyzer tracker | Working flat-file outputs. |
| JSON | `job_search_agent/sent_jobs.json` | Notification history only. |
| Database/run reporting | intelligence `load/db_loader.py` and schema | Best available persistence concepts; migrate to SQLite. |
| Daily intelligence summary | Console/run tables and Telegram top list | Partial; no central daily report entity. |

### Candidate analysis and CV generation

| Concern | Exact implementation | Assessment |
|---|---|---|
| Candidate profile | `ai_cv_tailor/data/master_cv.json` | Authoritative structure. |
| Manual profile/JD files | analyzer `profile.txt`, `job_description.txt` | Legacy fallback input. |
| JD analysis | `ai_cv_tailor/src/jd_analyzer.py:analyze_job_description()` | Strong deterministic base. |
| Profile comparison | `match_evidence()` | Strongest implementation. |
| Fit scoring | `select_cv_strategy()` vs model-generated analyzer score | Use CV tailor score as authority; model score is optional narrative only. |
| Relevant evidence selection | `cv_generator.py` selection helpers | Strong but heavily candidate-specific; refactor behind profile service. |
| Rule-based CV | `generate_flowcv_text()` | Best generator and mandatory fallback. |
| AI CV | `ai_cv_writer.py` plus `ollama_client.py` | Useful optional polisher with validation. |
| Formatting/output | FlowCV plain text and TXT downloads | No DOCX/PDF. |
| External AI | Ollama local/cloud in CV tailor; OpenAI Agents SDK in standalone analyzer | Two unrelated paths; central provider interface required. |

## Overall conclusion

The most valuable end-to-end foundation is split three ways: `job_search_agent` owns Arbeitsagentur and Telegram, `germany-english-job-intelligence` owns EnglishJobs persistence/run concepts, and `ai_cv_tailor` owns candidate evidence, explainable fit analysis, and truthful CV generation. The standalone analyzer is not embedded as code, but its capability is functionally superseded by the CV tailor’s structured pipeline; only its narrative analysis/cover-letter idea remains unique. The future platform should extract these capabilities behind shared contracts instead of joining the five entry points.
