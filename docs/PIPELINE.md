# Pipeline Orchestration

Milestone 10 adds a safe one-command local workflow:

```text
collect jobs -> deduplicate -> analyze -> rank -> notification preview -> top jobs -> JSON summary
```

The pipeline reuses existing services. It does not add scoring rules, source
parsers, live Telegram sending, AI polish, CV generation, auto-apply, deletion,
application-status mutation, or dashboard rewrites.

The daily-run command reuses this same pipeline service and adds only local run
history, config-file iteration, and lock protection. It does not change pipeline
business rules.

## Ranking Scope

Pipeline ranking is global by default:

- `global`: rank the best overall logical vacancies currently stored in the
  database. This preserves the original pipeline behavior.
- `current-run`: rank only jobs collected or updated in this collection step, or
  logical clusters linked to those jobs.

Use current-run scope for daily source/search review:

```powershell
python -m app.cli pipeline run `
  --profile-id <PROFILE_ID> `
  --source englishjobs `
  --query "Data Analyst" `
  --location Germany `
  --live-collect `
  --include-prefilter-only `
  --ranking-scope current-run `
  --preview-notification
```

When EnglishJobs produces snippet-only descriptions, current-run ranking can
show `prefilter_only` jobs if `--include-prefilter-only` is present. These jobs
remain discovery candidates; they do not receive authoritative fit scores.

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

For EnglishJobs live collection, the collection summary includes detail-page
diagnostics such as `detail_requests_attempted`, `full_descriptions`,
`snippet_descriptions`, `missing_descriptions`, `external_redirects_seen`, and
`parsing_errors`. Authoritative analysis still depends on descriptions being
stored as `full`; snippets remain discovery/prefilter-only.

## Output

The command prints readable JSON and writes the same summary to disk. Use
`--output <path>` to choose a file. Otherwise the file is written under:

```text
data/pipeline_runs/pipeline_<timestamp>.json
```

Generated pipeline summaries are local runtime artifacts and are ignored by
Git.

`top_jobs` includes `application_status` when a ranked job is already tracked.
The pipeline does not create, shortlist, skip, or update applications. Its
`next_actions` suggest an explicit shortlist command for the top match, for
example:

```powershell
python -m app.cli applications shortlist --profile-id <PROFILE_ID> --job-id <JOB_ID> --priority high --note "Top ranked match"
```

## Daily Workflow

1. Run the pipeline with stored jobs for a safe local refresh.
2. Add `--live-collect` only when you want external source requests.
3. Review `top_jobs` in the JSON output or open the dashboard.
4. Shortlist selected jobs explicitly.
5. Generate a CV manually for a selected stored full-description job:

```powershell
python -m app.dashboard
python -m app.cli applications shortlist --profile-id <PROFILE_ID> --job-id <JOB_ID> --priority high
python -m app.cli cv generate --job-id <JOB_ID> --profile-id <PROFILE_ID> --force-regenerate
python -m app.cli cv list --profile-id <PROFILE_ID>
```

Use the dashboard CV Workflow page or `cv show --text` to copy FlowCV content,
then attach the reviewed artifact with `applications cv-ready` or
`applications attach-cv`.
