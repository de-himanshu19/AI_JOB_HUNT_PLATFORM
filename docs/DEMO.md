# Demo Guide

This guide shows a safe portfolio demo path for the AI Job Hunt Platform. It
uses placeholders for local IDs because profile, job, and artifact IDs are
database-specific.

## Prerequisites

- Python 3.11 or newer
- PowerShell on Windows
- Repository cloned locally
- Optional dashboard dependency installed through the `dashboard` extra
- Optional AI provider credentials only if demonstrating live AI polish

No Telegram, Ollama, OpenAI-compatible, MySQL, Arbeitsagentur, or EnglishJobs
credentials are required for the offline demo.

## Activate Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

If the virtual environment does not exist yet:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dashboard,test]"
```

## Initialize Database

```powershell
python -m app.db.migrations
```

The default database path is `data/job_hunt.sqlite3`. The `data/` directory is
local runtime state and should not be committed.

## Run Tests

```powershell
python -m pytest
python -m compileall app tests
```

Expected offline baseline from the latest verification:

```text
272 passed, 2 skipped
```

The skipped tests are optional live smoke tests for Arbeitsagentur and
EnglishJobs.

## Run Pipeline Safely Without Live Collection

This command uses stored jobs only and does not contact external job sources:

```powershell
python -m app.cli pipeline run `
  --profile-id <profile-id> `
  --query "Data Analyst" `
  --location Deutschland `
  --source arbeitsagentur `
  --top-n 10 `
  --preview-notification
```

Use this mode for demos where you want deterministic behavior and no network
request.

## Run Daily Wrapper Safely

The daily command wraps the pipeline and writes a JSON run summary under
`data/daily_runs/`:

```powershell
python -m app.cli daily run `
  --profile-id <profile-id> `
  --query "Data Analyst" `
  --location Deutschland `
  --source arbeitsagentur `
  --max-pages 1 `
  --page-size 10 `
  --top-n 10 `
  --preview-notification
```

Without `--live-collect`, this uses stored jobs only. For multiple configured
searches, copy `config/daily_searches.example.json` to
`config/daily_searches.local.json`, edit local IDs, and run:

```powershell
python -m app.cli daily run-config --config config/daily_searches.local.json
```

## Run Live Arbeitsagentur Collection

Live collection is explicit and bounded:

```powershell
python -m app.cli collect arbeitsagentur --live `
  --query "Data Analyst" `
  --location Deutschland `
  --max-pages 1 `
  --page-size 10
```

This contacts Arbeitsagentur only because `--live` is present. Keep page bounds
small during demos.

## Open Dashboard

```powershell
python -m app.dashboard
```

Opening the dashboard is passive. It must not collect jobs, send Telegram
messages, call AI providers, generate CVs, change application status, approve
duplicates, or open external vacancy links without explicit user action.

The `Applications Analytics` page is also passive. It reads existing jobs,
description completeness, applications, follow-up dates, and saved daily-run
JSON summaries to show funnel progress and source quality.

## Review Analytics From CLI

```powershell
python -m app.cli analytics summary --profile-id <profile-id>
```

This command prints JSON for funnel counts, source quality, due/overdue
follow-ups, recent activity, and saved daily-run summaries. It does not trigger
live collection, AI polish, Telegram delivery, or application status changes.

## Shortlist A Job

```powershell
python -m app.cli applications shortlist `
  --profile-id <profile-id> `
  --job-id <job-id> `
  --priority high `
  --note "Strong fit after review"
```

The application record is local CRM state only. It does not submit an
application.

## Generate CV

Stored-job CV generation requires a full job description:

```powershell
python -m app.cli cv generate --job-id <job-id> --profile-id <profile-id>
```

If the stored job has only a snippet or missing description, use a manual
description file:

```powershell
python -m app.cli cv generate-manual `
  --description-file <job-description.txt> `
  --profile-id <profile-id>
```

## Show CV Artifact

Metadata-only view:

```powershell
python -m app.cli cv show --artifact-id <artifact-id>
```

Copy-friendly FlowCV text:

```powershell
python -m app.cli cv show --artifact-id <artifact-id> --text
```

Private evidence report:

```powershell
python -m app.cli cv show --artifact-id <artifact-id> --evidence
```

Evidence reports are for local review only and should not be committed.

## Run Safe AI Polish

AI polish is optional and requires explicit live opt-in:

```powershell
python -m app.cli cv polish `
  --artifact-id <rule-based-artifact-id> `
  --live-ai
```

The rule-based artifact remains authoritative. A separate AI child artifact is
stored only if protected-fact validation passes.

Example Ollama Cloud configuration shape:

```text
AI_ENABLED=true
AI_PROVIDER=ollama_cloud
AI_API_KEY=
AI_BASE_URL=https://ollama.com
AI_MODEL=gpt-oss:20b
AI_TIMEOUT_SECONDS=120
AI_MAX_RETRIES=2
```

Set `AI_API_KEY` only in your local `.env`. Never commit it.

## Attach CV To Application

```powershell
python -m app.cli applications cv-ready `
  --profile-id <profile-id> `
  --job-id <job-id> `
  --cv-artifact-id <artifact-id> `
  --note "Reviewed and ready to paste into FlowCV"
```

This links the reviewed artifact to local application tracking and marks the
record as CV-ready.

## Generate Prep Pack

```powershell
python -m app.cli prep pack `
  --profile-id <profile-id> `
  --job-id <job-id> `
  --cv-artifact-id <artifact-id>
```

The prep pack is a local markdown draft under `data/prep_packs/`. It contains a
job snapshot, fit summary, evidence-backed talking points, recruiter questions,
checklists, and a cover letter draft. It is not submitted anywhere and must be
reviewed before applying manually.

## Create Manual Application Package

```powershell
python -m app.cli application-pack create `
  --profile-id <profile-id> `
  --job-id <job-id> `
  --cv-artifact-id <artifact-id>
```

The package is a local folder under `data/application_packs/` with a checklist,
job snapshot, cover letter draft, CV reference, submission notes, and follow-up
plan. By default it references CV artifact metadata only; use
`--include-cv-text` only when you intentionally want the local CV text copied
into the package.

After applying manually, record the submission:

```powershell
python -m app.cli applications submit-manual `
  --profile-id <profile-id> `
  --job-id <job-id> `
  --note "Applied manually via company website" `
  --follow-up-date YYYY-MM-DD
```

This records local CRM status and follow-up metadata only. It does not submit,
email, upload, or notify anyone.

## Draft Follow-Up Communication

```powershell
python -m app.cli communications draft `
  --profile-id <profile-id> `
  --job-id <job-id> `
  --type follow_up
```

Drafts are local markdown files under `data/communication_drafts/`. They use
stored application context and placeholders such as `[Recruiter Name]` or
`[Application Date]`. Review and replace placeholders manually before sending
anything outside the system.

## View History

```powershell
python -m app.cli applications history `
  --profile-id <profile-id> `
  --job-id <job-id>
```

Every accepted application tracking change writes an immutable event.

## Local Smoke Example

Use the real IDs from your local database when running a private smoke test:

```powershell
python -m app.cli cv generate `
  --job-id <local-job-id> `
  --profile-id <local-profile-id> `
  --force-regenerate
```

The public docs intentionally keep IDs as placeholders so the repository does
not expose private local database state.
