# Pipeline Orchestration

Milestone 10 adds a safe one-command local workflow:

```text
collect jobs -> deduplicate -> analyze -> rank -> notification preview -> top jobs -> JSON summary
```

The pipeline reuses existing services. It does not add scoring rules, source
parsers, live Telegram sending, AI polish, CV generation, auto-apply, deletion,
or dashboard rewrites.

## Safe Dry Run

Without `--live-collect`, the pipeline never contacts Arbeitsagentur or
EnglishJobs. It uses already stored jobs, rebuilds duplicate clusters, analyzes
and ranks locally, and can create an offline Telegram preview.

```powershell
python -m app.cli pipeline run `
  --profile-id 543ca73e-7c5d-44af-96f8-d3b43b463284 `
  --query "Data Analyst" `
  --location Deutschland `
  --source arbeitsagentur `
  --max-pages 1 `
  --page-size 10 `
  --top-n 10 `
  --preview-notification
```

If no jobs are stored yet, the safe dry run fails clearly and asks you to import
jobs or opt in to live collection.

## Live Collection

Live source collection is opt-in only:

```powershell
python -m app.cli pipeline run `
  --profile-id 543ca73e-7c5d-44af-96f8-d3b43b463284 `
  --query "Data Analyst" `
  --location Deutschland `
  --source arbeitsagentur `
  --max-pages 1 `
  --page-size 10 `
  --top-n 10 `
  --live-collect `
  --preview-notification
```

`--source` may be repeated or comma-separated, for example:

```powershell
python -m app.cli pipeline run `
  --profile-id 543ca73e-7c5d-44af-96f8-d3b43b463284 `
  --source arbeitsagentur,englishjobs `
  --preview-notification
```

Notification preview remains offline: no Telegram message is sent and no
notification tables are modified.

## Output

The command prints readable JSON and writes the same summary to disk. Use
`--output <path>` to choose a file. Otherwise the file is written under:

```text
data/pipeline_runs/pipeline_<timestamp>.json
```

Generated pipeline summaries are local runtime artifacts and are ignored by
Git.

## Daily Workflow

1. Run the pipeline with stored jobs for a safe local refresh.
2. Add `--live-collect` only when you want external source requests.
3. Review `top_jobs` in the JSON output or open the dashboard.
4. Generate a CV manually for a selected stored full-description job:

```powershell
python -m app.dashboard
python -m app.cli cv generate --job-id <JOB_ID> --profile-id <PROFILE_ID> --force-regenerate
```
