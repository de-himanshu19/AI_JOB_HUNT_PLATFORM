# Local Daily Scheduler

Milestone 16 adds a local daily-run wrapper around the existing safe pipeline.
It does not add auto-apply, automatic CV generation, live AI polish, or live
Telegram sending.

## Manual Test First

Create a private local config from the template:

```powershell
Copy-Item config\daily_searches.example.json config\daily_searches.local.json
```

Edit `config\daily_searches.local.json` with your local `profile_id` values.
The `.local.json` file is ignored and should not be committed.
Daily configs default to `"ranking_scope": "current-run"` so each configured
search shows the jobs from that run/search first. Set `"ranking_scope": "global"`
when you want the best overall stored jobs instead.

Run the config manually:

```powershell
python -m app.cli daily run-config --config config\daily_searches.local.json
```

Run one search directly:

```powershell
python -m app.cli daily run `
  --profile-id <PROFILE_ID> `
  --query "Data Analyst" `
  --location Deutschland `
  --source arbeitsagentur `
  --max-pages 1 `
  --page-size 10 `
  --top-n 10 `
  --live-collect `
  --preview-notification
```

Without `--live-collect`, the daily command uses stored jobs only and makes no
source request.

## Output And Locking

Daily summaries are written under:

```text
data/daily_runs/
```

Each summary includes the run ID, start/end timestamps, status, search counts,
per-search pipeline summaries, errors, and output paths.

Overlap protection uses:

```text
data/locks/daily_run.lock
```

If the lock already exists, the command exits with a clear JSON status and does
not start another run. Stale locks are conservative: remove the lock only after
verifying that no daily run is active.

## PowerShell Wrapper

The repository includes:

```text
scripts/run_daily_jobs.ps1
```

It moves to the project root, uses `.venv\Scripts\python.exe`, runs:

```powershell
python -m app.cli daily run-config --config config\daily_searches.local.json
```

and writes logs under:

```text
data/logs/
```

Manual script test:

```powershell
.\scripts\run_daily_jobs.ps1 -ConfigPath config\daily_searches.local.json
```

## Windows Task Scheduler

Create a task with:

- Program/script: `powershell.exe`
- Arguments: `-ExecutionPolicy Bypass -File "C:\Users\himan\Desktop\personal projects\AI_JOB_HUNT_PLATFORM\scripts\run_daily_jobs.ps1"`
- Start in: `C:\Users\himan\Desktop\personal projects\AI_JOB_HUNT_PLATFORM`
- Trigger: daily at `08:00`
- Security option: run only when user is logged on

Recommended first run:

1. Run the PowerShell script manually.
2. Confirm a JSON file appears under `data/daily_runs/`.
3. Confirm a log file appears under `data/logs/`.
4. Confirm the dashboard Runs & Diagnostics page shows the latest daily run.
5. Then enable the scheduled task.

## Inspect Logs

```powershell
Get-ChildItem data\logs | Sort-Object LastWriteTime -Descending | Select-Object -First 5
Get-Content data\logs\<log-file-name>.log
```

## Disable The Task

Open Windows Task Scheduler, select the task, and choose `Disable`. Disabling
the task stops future runs; it does not delete local history files.

## Safety Guarantees

- No auto-apply.
- No CV generation unless a user runs CV commands separately.
- No AI polish.
- Notification remains preview-only unless a future milestone explicitly
  changes this behavior.
- Live source collection requires explicit `live_collect: true` in local config
  or `--live-collect` on the command line.
- Notification preview uses the configured ranking scope; current-run daily
  previews show the jobs from that search instead of older unrelated rankings.
