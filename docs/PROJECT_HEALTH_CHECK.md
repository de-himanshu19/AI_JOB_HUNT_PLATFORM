# Project Health Check

Use this checklist before creating a release checkpoint or sharing the project.

## Git State

```powershell
git status --short
git diff --check
git diff -- existing_projects
```

Expected:

- Only intentional source/docs/test changes are present.
- No whitespace errors.
- No changes under `existing_projects/`.

## Tests And Syntax

```powershell
python -m pytest
python -m compileall app tests
```

Optional focused regression smoke:

```powershell
python -m pytest tests/integration/test_pipeline.py tests/integration/test_cv_generation.py tests/integration/test_applications.py
```

## Ignore Rules

```powershell
git check-ignore .env
git check-ignore data/job_hunt.sqlite3
git check-ignore data/cv_artifacts/example.txt
git check-ignore data/application_packs/example.txt
git check-ignore data/communication_drafts/example.txt
```

Also confirm private local configs remain ignored:

```powershell
git check-ignore config/daily_searches.local.json
```

## Secret Scan Reminder

Scan changed files for common secret patterns before committing:

```powershell
git diff --name-only
```

Review changed docs/code for API keys, tokens, passwords, private CV text,
database content, local job-search notes, and generated artifact paths.

## Runtime Data Check

Do not commit:

- `.env`
- SQLite databases
- `data/`
- CV artifacts
- prep packs
- application packs
- communication drafts
- daily runs
- logs
- local scheduler config

## Optional Live Smokes

Only run these when you intentionally want live network calls:

```powershell
$env:RUN_ARBEITSAGENTUR_LIVE_TEST="1"
python -m pytest tests/integration/test_arbeitsagentur_live.py
```

```powershell
$env:RUN_ENGLISHJOBS_LIVE_TEST="1"
python -m pytest tests/integration/test_englishjobs_live.py
```

Manual bounded source smoke:

```powershell
python -m app.cli collect arbeitsagentur --live --query "Data Analyst" --location Deutschland --max-pages 1 --page-size 10
```

Do not run live smokes during ordinary portfolio verification.
