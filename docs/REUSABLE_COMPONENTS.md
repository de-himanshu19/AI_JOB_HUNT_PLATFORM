# Reusable Components

## Classification rules

- **Reuse unchanged**: logic and contract are already narrow and suitable.
- **Reuse with minor modification**: useful implementation with local hard-coding or a small contract change.
- **Refactor into a shared module**: authoritative logic currently coupled to a legacy app/data shape.
- **Retain as a fallback**: valuable safe/secondary behavior, not the primary path.
- **Replace because incomplete or broken**: concept is needed but implementation cannot meet the target.
- **Remove because it duplicates a stronger implementation**: do not carry this copy into the unified app.
- **Keep source-specific**: preserve behind a source/service adapter; do not generalize its protocol details.

## `ai_cv_tailor`

| Component | Classification | Reason / destination |
|---|---|---|
| `data/master_cv.json` schema and evidence/claim rules | **Refactor into a shared module** | Best candidate source of truth. Validate with a `CandidateProfile` model and separate personal facts from selection policy. |
| `jd_analyzer.analyze_job_description()` and helpers | **Refactor into a shared module** | Strong deterministic analyzer; remove employer-specific extraction and return a typed `JobRequirements`. |
| `evidence_matcher.match_evidence()` and normalization/related-term helpers | **Refactor into a shared module** | Authoritative evidence comparison and missing-skill base. Add tests and configurable synonym taxonomy. |
| ERP and language risk helpers | **Reuse with minor modification** | Useful conservative logic; read candidate language/claims from typed profile and generalize requirement levels. |
| `strategy_selector.select_cv_strategy()` | **Refactor into a shared module** | Best final fit score, but role bonus, thresholds, penalties, and candidate-specific caps need versioned configuration. |
| `cv_generator.generate_flowcv_text()` | **Refactor into a shared module** | Best/only CV generator. Split evidence selection from formatting and remove employer/name/metric literals. |
| `cv_generator` selection helpers | **Refactor into a shared module** | Useful relevance ranking, currently tightly bound to one profile and role taxonomy. |
| FlowCV format helpers | **Reuse with minor modification** | Preserve plain-text output as first formatter; consume a structured `TailoredCV` object. |
| `clean_experience_labels()` | **Reuse with minor modification** | Safe cleanup, but label rules belong to formatter policy. |
| `generate_evidence_report()` | **Refactor into a shared module** | Strong reporting content; replace candidate-specific narrative with data-driven templates. |
| `ollama_client.ask_ai()` | **Keep source-specific** | Best HTTP handling pattern. Place behind `AIProvider`; inject URL/key/model/session and add retry policy/redaction. |
| `ask_ollama()` wrapper | **Retain as a fallback** | Temporary compatibility only; remove after all callers use provider interface. |
| `ai_cv_writer` section/full polish | **Retain as a fallback** | Optional enhancement after rule-based generation. Keep validation, but AI must never become the evidence authority. |
| Streamlit `app.py` UI | **Replace because incomplete or broken** | Useful UX reference only. Future dashboard is job-centric and must load by `job_id`; do not transplant the monolith. |
| `build_job_tracker_summary()` | **Reuse with minor modification** | Useful display/export helper; source data should come from stored `Job`. |
| `prompts/*.txt`, `src/utils.py` | **Remove because it duplicates a stronger implementation** | Placeholder/unused. Keep prompts only after centralizing actual embedded prompts. |

## `ai-job-fit-analyzer-agent`

| Component | Classification | Reason / destination |
|---|---|---|
| `job_fit_agent` prompt and `Runner.run_sync()` score | **Remove because it duplicates a stronger implementation** | CV tailor provides structured deterministic scoring. A model-generated number must not be authoritative. |
| Narrative “why fit / missing skills / CV suggestions” concept | **Retain as a fallback** | Optional AI explanation generated from already-computed structured evidence. |
| Short cover-letter concept/parser | **Reuse with minor modification** | Unique capability, but request structured output and store as an optional artifact; cover letter is not required for milestone 1. |
| `profile.txt` | **Remove because it duplicates a stronger implementation** | Superseded by `master_cv.json`; preserve only as migration input if it contains unique facts. |
| `job_description.txt` manual input | **Retain as a fallback** | Manual JD remains explicitly required as a fallback, but the primary path is a stored `job_id`. |
| `load_file()` | **Remove because it duplicates a stronger implementation** | Trivial and cwd-dependent; use shared repositories/path service. |
| `clean_filename()` | **Reuse with minor modification** | Useful artifact slug helper; add collision resistance, max length, Unicode handling, and job ID. |
| `extract_match_score()` / `extract_decision()` | **Replace because incomplete or broken** | Fragile prose parsing; decision substring order is incorrect. Use typed/JSON output if AI narrative remains. |
| `save_unique_reports()` | **Reuse with minor modification** | Artifact naming idea is useful; central artifact repository should own persistence. |
| `save_to_job_tracker()` | **Replace because incomplete or broken** | CSV tracker is not lifecycle status and current artifact schema has drifted. Use SQLite applications/status events. |

## `englishjobs_scraper`

| Component | Classification | Reason / destination |
|---|---|---|
| `url_builder.build_search_url()` | **Keep source-specific** | Preserve keyword/location URL mode and combine it with the state adapter. Use URL encoding and adapter config. |
| `fetcher.fetch_html()` | **Remove because it duplicates a stronger implementation** | Same behavior exists in state project. Replace both with one resilient shared HTTP client used by the adapter. |
| `parser.parse_jobs()` | **Refactor into a shared module** | Useful keyword metadata and parser fallbacks; unify with state parser and test against saved fixtures. |
| `extract_total_jobs_count()` | **Remove because it duplicates a stronger implementation** | Consolidate one implementation in EnglishJobs adapter. |
| `scrape_one_page()` / `scrape_all_pages()` | **Reuse with minor modification** | Useful keyword pagination mode; add retry policy, bounds, page observations, and normalized output. |
| `scorer.py` | **Remove because it duplicates a stronger implementation** | Intelligence scorer/classifier and CV-tailor fit service are stronger. Do not keep a third score. |
| `exporter.save_to_csv()` | **Remove because it duplicates a stronger implementation** | CSV export belongs to one shared reporting/export service. |
| `main.py` | **Replace because incomplete or broken** | Hard-coded orchestration and huge overlapping result sets; represent search plans as configuration/run records. |
| `requirements.txt` | **Replace because incomplete or broken** | It is an environment freeze with many unused packages. Define minimal root dependencies. |

## `germany-english-job-intelligence`

| Component | Classification | Reason / destination |
|---|---|---|
| `config.py` state mapping | **Reuse with minor modification** | Good complete state list; move to source configuration and add tests. |
| static categories/profile constants | **Refactor into a shared module** | Categories may seed config; candidate profile must come from shared profile store. |
| `extract/url_builder.py` | **Keep source-specific** | State URL mode belongs in EnglishJobs adapter alongside keyword mode. |
| `extract/fetcher.py` | **Refactor into a shared module** | Replace body with shared resilient HTTP client while preserving adapter-specific headers. |
| `extract/parser.py` | **Keep source-specific** | Preferred parser base; unify keyword metadata and return raw source records, not DataFrames. |
| `extract/state_scraper.py` | **Keep source-specific** | Preferred EnglishJobs orchestration base; return a source-run result and normalized records. |
| `transform/cleaner.py` | **Replace because incomplete or broken** | Empty. Implement shared title/company/location/description normalization. |
| `transform/classifier.py` | **Refactor into a shared module** | Useful prefilter taxonomy; remove candidate coupling and make ordered rules configurable/tested. |
| `transform/scorer.py` | **Refactor into a shared module** | Retain only as cheap collection/prefilter score; do not call it profile-fit score. |
| `transform/deduplicator.py` | **Refactor into a shared module** | Stable-ID concept is useful. Replace source-inclusive MD5 identity with canonical URL/source ID plus cross-source fingerprints and match records. |
| `utils/exporter.py` | **Reuse with minor modification** | One shared exporter can use this simple pattern; path service and explicit schema required. |
| `load/schema.sql` | **Refactor into a shared module** | Best schema concepts (jobs, profiles, scores, runs); redesign for SQLite, sources, descriptions, notifications, applications, and events. |
| `load/database.py` | **Replace because incomplete or broken** | Target is SQLite, not MySQL; config validation is weak. |
| `load/db_loader.py` master-data functions | **Refactor into a shared module** | Seed categories/states through migrations or repositories rather than ad hoc calls. |
| job/score upsert functions | **Refactor into a shared module** | Preserve upsert/first-seen/last-seen intent; implement repositories with accurate inserted/updated counts. |
| scrape-run functions | **Refactor into a shared module** | Strongest logging model. Add per-source run items, error fields, and guaranteed finalization. |
| `main.py` | **Replace because incomplete or broken** | Sequential script cannot recover per state and is MySQL-coupled. Replace with application service/CLI runner. |

## `job_search_agent`

| Component | Classification | Reason / destination |
|---|---|---|
| `search_jobs_for_role()` | **Keep source-specific** | Only Arbeitsagentur search implementation. Add pagination, exception handling, typed raw records, and injected HTTP/config. |
| `get_city()` / `get_job_link()` | **Keep source-specific** | Useful summary JSON mapping; fold into adapter parser. |
| `encode_ref_number()` / `fetch_job_details()` | **Keep source-specific** | Only detail implementation. Return structured JSON and canonical description rather than lowercased dump. |
| language blocker/signal dictionaries and functions | **Refactor into a shared module** | Strong source of screening rules; combine with shared language service while retaining explicit hard blockers. |
| `remove_bad_jobs()` | **Remove because it duplicates a stronger implementation** | Mixes source collection and preference policy. Replace with normalized filter/ranking service. |
| `job_scorer.calculate_score()` | **Refactor into a shared module** | Retain bank/company and location preferences as configurable signals, not authoritative score or bank-only filter. |
| `job_history.py` | **Refactor into a shared module** | Successful-send semantics are good; implement notification records/unique constraints in SQLite. |
| `telegram_sender.send_telegram_message()` | **Keep source-specific** | Primary notifier base. Add dependency injection, retries, chunking, safe errors, and result IDs. |
| `send_test_message.py` sender copy | **Remove because it duplicates a stronger implementation** | Test command should call the single notification service. |
| inline top-job selection/formatting | **Refactor into a shared module** | Notification service should query top 20 new, unnotified jobs after central scoring. |
| `search_company_careers.py` | **Remove because it duplicates a stronger implementation** | Static bookmarks are outside the two-source scope and are not collectors. Preserve externally if desired, not in core app. |
| `config.py` target roles | **Reuse with minor modification** | Seed search-plan config; de-duplicate and separate source query terms from candidate preferences. |
| `run_daily_job_agent.py` | **Replace because incomplete or broken** | Future scheduler/CLI calls a source-independent collection use case. |

## Authoritative component set

The unified implementation should have one authoritative component per concern:

- Arbeitsagentur protocol: `job_search_agent` adapter code.
- EnglishJobs protocol: intelligence state pipeline plus keyword URL mode from `englishjobs_scraper`.
- HTTP resilience: pattern from `ai_cv_tailor/ollama_client.py`, generalized.
- Normalization and cross-source deduplication: new shared code (none is sufficient).
- Persistence and run history: intelligence schema concepts, reimplemented for SQLite.
- Prefilter classification: intelligence classifier/scorer, renamed and externalized.
- Candidate evidence, job requirements, missing skills, final fit: `ai_cv_tailor` analysis stack.
- CV: `ai_cv_tailor` rule-based generator first, AI polisher optional.
- Telegram: `job_search_agent`, decoupled and backed by database notification history.

