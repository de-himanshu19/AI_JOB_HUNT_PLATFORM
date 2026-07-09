# Environment Variable and Secret Audit

## Findings

Only nine distinct environment-variable names are present or implied across the five projects. No code uses `os.environ[...]`, `dotenv_values()`, or `st.secrets[...]`. Four projects contain `.env` files; `englishjobs_scraper/.env` is empty. `ai_cv_tailor` calls `load_dotenv()` but has no `.env` in the audited tree. Environment names were not changed.

Probable live credentials are present inside legacy folders. They should be rotated before any code migration, removed from plaintext notes, and kept out of the future database/logs. This audit deliberately masks every value.

## Complete inventory

| Project | Existing variable | Use site | Purpose | Req. now | Secret? | Proposed unified name | Temporary alias? | Current default/fallback |
|---|---|---|---|---|---|---|---|---|
| `ai_cv_tailor` | `OLLAMA_API_KEY` | `src/ollama_client.py:46` | Bearer token for Ollama Cloud | Required only for cloud provider | Yes | `AI_OLLAMA_API_KEY` | Yes: read `AI_OLLAMA_API_KEY`, then legacy `OLLAMA_API_KEY` | Missing key returns an error string; local/rule-based modes still work. |
| `ai-job-fit-analyzer-agent` | `OPENAI_API_KEY` | `.env:1`; consumed indirectly after `main.py:8` by OpenAI Agents SDK | OpenAI authentication | Required for the only analysis path | Yes | `AI_OPENAI_API_KEY`* | Yes; SDK still expects `OPENAI_API_KEY` | No application-level validation/fallback; SDK call fails. |
| `germany-english-job-intelligence` | `MYSQL_HOST` | `load/database.py:24` | MySQL hostname | Required | No, normally | `LEGACY_MYSQL_HOST`* | Yes | No default; missing value enters malformed URL. |
| same | `MYSQL_PORT` | `load/database.py:25` | MySQL port | Required | No | `LEGACY_MYSQL_PORT`* | Yes | No default. |
| same | `MYSQL_USER` | `load/database.py:26` | MySQL username | Required | Sensitive | `LEGACY_MYSQL_USER`* | Yes | No default. |
| same | `MYSQL_PASSWORD` | `load/database.py:27` | MySQL password | Required | Yes | `LEGACY_MYSQL_PASSWORD`* | Yes | No default; `quote_plus(None)` can fail before connection. |
| same | `MYSQL_DATABASE` | `load/database.py:28` | MySQL schema | Required | No | `LEGACY_MYSQL_DATABASE`* | Yes | No default. |
| `job_search_agent` | `TELEGRAM_BOT_TOKEN` | `telegram_sender.py:7`; `send_test_message.py:8` | Telegram Bot API credential | Required to notify | Yes | `TELEGRAM_BOT_TOKEN` | No | Explicit `ValueError` if missing. |
| same | `TELEGRAM_CHAT_ID` | `telegram_sender.py:8`; `send_test_message.py:9` | Telegram destination | Required to notify | Sensitive/secret-like | `TELEGRAM_CHAT_ID` | No | Explicit `ValueError` if missing. |

\* The future unified application should use SQLite, so MySQL variables are migration-only. For OpenAI, the unified loader may expose an internal typed setting named `ai_openai_api_key`, but should continue exporting/reading the standard `OPENAI_API_KEY` expected by the SDK. It is reasonable to keep that external name authoritative rather than force a rename.

## Probable secrets and hard-coded authentication

| File | Variable/constant | Type | Masked value / status | Action |
|---|---|---|---|---|
| `existing_projects/ai-job-fit-analyzer-agent/.env:1` | `OPENAI_API_KEY` | OpenAI API key | `sk-p...YXsA` | Rotate; use root `.env`; ensure legacy `.env` never enters a new commit. |
| `existing_projects/germany-english-job-intelligence/.env:4` | `MYSQL_PASSWORD` | Database password | `Hima...2345` | Rotate immediately; it appears human-derived and is stored in plaintext. |
| `existing_projects/job_search_agent/.env:1` | `TELEGRAM_BOT_TOKEN` | Telegram bot token | `8975...sqSw` | Rotate via BotFather; move to root `.env`. |
| `existing_projects/job_search_agent/.env:2` | `TELEGRAM_CHAT_ID` | Telegram chat identifier | `7058...0901` | Treat as sensitive; move to root `.env`. |
| `existing_projects/job_search_agent/telegram.txt:7` | “token key to access HTTP API” | Duplicate hard-coded Telegram token | `8975...sqSw` | Delete during a later approved secret-remediation milestone, after rotation and backup review. |
| `existing_projects/job_search_agent/telegram.txt:9` | `TELEGRAM_CHAT_ID` note | Duplicate hard-coded chat ID | `7058...0901` | Remove during later remediation. |
| `existing_projects/job_search_agent/search_arbeitsagentur.py:15-17` | `HEADERS["X-API-Key"]` | Arbeitsagentur public web-client key label | `jobb...uche` | Keep source-specific but centralize as adapter default; do not present it as a user secret. |
| `existing_projects/ai_cv_tailor/src/ollama_client.py:49` | `Authorization` header | Runtime Bearer header | Built from env; no hard-coded value | Ensure HTTP errors/logs never print the header or token. |

The two legacy `.gitignore` files that cover secrets are useful but insufficient: `ai-job-fit-analyzer-agent` has no `.gitignore`, and plaintext `telegram.txt` is not ignored. Ignore rules also do not protect secrets already committed or copied.

## Hard-coded model, endpoint, path, and user configuration

| Project/file | Value | Classification | Future treatment |
|---|---|---|---|
| `ai_cv_tailor/src/ollama_client.py:12` | `http://localhost:11434/api/generate` | Local endpoint | `AI_OLLAMA_LOCAL_URL`, optional with same default. |
| same line 13 | `https://ollama.com/api/generate` | Cloud endpoint | `AI_OLLAMA_CLOUD_URL`, optional with same default. |
| same lines 28, 33, 106; `app.py:92-93` | `llama3.2:3b`, `gpt-oss:20b` | Model names, duplicated | `AI_LOCAL_MODEL`, `AI_CLOUD_MODEL`; UI reads typed config. |
| EnglishJobs configs | `https://englishjobs.de`, browser headers, 20/page | Source config | Keep defaults in EnglishJobs adapter; allow env override for testing. |
| Arbeitsagentur source | v6 search URL, v4 detail URL, public client key | Source config | Keep defaults in Arbeitsagentur adapter; allow test override. |
| Telegram sender | `https://api.telegram.org/bot.../sendMessage` | Service endpoint | Derived from token; optional `TELEGRAM_API_BASE_URL` for tests. |
| All projects | `data/...`, `outputs/...`, `reports/...`, CSV/JSON names | Relative paths | Resolve from an application root/data directory using `pathlib.Path`; never current-working-directory semantics. |
| CV/score modules | Candidate name, employers, dates, metrics, role weights | User-specific policy/data | Move facts to candidate profile and weights/rules to versioned config. |
| Job agent | role list, cities, banks, seven-day window, size 10, top 10 | Search policy | Typed settings; future Telegram limit defaults to 20. |

No machine-specific absolute filesystem path was found in authored source. The risk is relative-path dependence on the current working directory and Windows Task Scheduler configuration outside the repository.

## Proposed future root `.env`

The root `.env` should contain deployment-specific values, not scoring rules or candidate facts. A committed `.env.example` should contain names and safe defaults only.

```dotenv
# Runtime
APP_ENV=local
APP_LOG_LEVEL=INFO
APP_TIMEZONE=Europe/Berlin
JOBHUNT_DATA_DIR=./data
JOBHUNT_DATABASE_PATH=./data/job_hunt.sqlite3

# Source adapters (override mainly for tests/development)
ARBEITSAGENTUR_SEARCH_URL=https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs
ARBEITSAGENTUR_DETAIL_URL=https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails
ARBEITSAGENTUR_API_KEY=jobboerse-jobsuche
ENGLISHJOBS_BASE_URL=https://englishjobs.de
SOURCE_HTTP_TIMEOUT_SECONDS=20
SOURCE_MAX_RETRIES=3
SOURCE_REQUEST_DELAY_SECONDS=2

# Notifications
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_TOP_N=20

# AI CV polish (optional; rule-based CV generation remains available offline)
AI_ENABLED=false
AI_PROVIDER=rule_based
AI_API_KEY=
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4.1-mini
AI_TIMEOUT_SECONDS=30
AI_MAX_RETRIES=2
# Native Ollama Cloud alternative:
# AI_PROVIDER=ollama_cloud
# AI_BASE_URL=https://ollama.com
# AI_MODEL=gpt-oss:20b
# AI_TIMEOUT_SECONDS=120
CV_ARTIFACT_ROOT=data/cv_artifacts
CV_MANUAL_MAX_BYTES=1000000
OPENAI_API_KEY=

# Temporary legacy MySQL migration only; remove after import validation
MYSQL_HOST=
MYSQL_PORT=3306
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DATABASE=
```

## Loading and compatibility strategy

1. Load the root `.env` exactly once in `app/config.py`; libraries receive a typed settings object and never call `load_dotenv()` themselves.
2. Resolve paths relative to the repository/application root, not `cwd`.
3. Prefer the unified name, then a documented legacy alias. Emit a deprecation warning naming the variable, never its value.
4. Preserve `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OPENAI_API_KEY`, and the five `MYSQL_*` names until migration is complete.
5. Validate required settings only when the related feature is explicitly used. The dashboard and rule-based CV builder must start without Telegram, MySQL, or AI credentials.
6. Redact values whose names contain `TOKEN`, `KEY`, `SECRET`, `PASSWORD`, or `CHAT_ID` from configuration dumps and exception contexts.
7. Rotate all credentials discovered in legacy files before the first integration run.

## Milestone 13 AI polish safety

Use `AI_PROVIDER=openai_compatible` for chat-completions APIs and
`AI_PROVIDER=ollama_cloud` for native Ollama Cloud `/api/chat` requests.
For Ollama Cloud CV polish, prefer `AI_MODEL=gpt-oss:20b`, not
`gpt-oss-safeguard`.
`AI_ENABLED=false` and `AI_PROVIDER=rule_based` are safe defaults. Never commit a
real `AI_API_KEY` or `.env` file. API polish sends CV text to the configured
external service, and the resulting text is stored only if protected-fact
validation passes. `validation_failed` is expected and safe when a model changes
facts or FlowCV structure. Automated tests use fake providers and do not make
live AI, Telegram, Arbeitsagentur, EnglishJobs, email, or Ollama requests.
