# Application Tracking CRM

Milestone 11 turns ranked jobs into a local application workflow. It stores user
tracking metadata only; it does not submit applications, send email, send
Telegram messages, collect jobs, change scoring, or regenerate CVs unless you
run those separate commands explicitly.

## Workflow

Supported statuses:

- `new`: tracking record exists, but no decision has been made.
- `shortlisted`: worth preparing or reviewing.
- `skipped`: intentionally ignored for now.
- `cv_ready`: a CV artifact is ready for manual review/export.
- `applied`: application was manually submitted outside the platform.
- `interview`: interview process has started.
- `offer`: offer received.
- `rejected`: employer or user rejected the opportunity.
- `withdrawn`: user withdrew from the process.

Every status or CRM metadata change appends an immutable `application_events`
row. Existing application and artifact history is preserved.

## Identity

Applications are tracked per candidate profile and vacancy. When duplicate
clustering is available, the CRM stores the current `logical_cluster_id` and
prevents duplicate tracking rows for the same profile and logical vacancy.
When no cluster exists, it falls back to `profile_id + job_id`.

## CLI

Shortlist a ranked job:

```powershell
python -m app.cli applications shortlist --profile-id <PROFILE_ID> --job-id <JOB_ID> --priority high --note "Top ranked match"
```

Skip a job:

```powershell
python -m app.cli applications skip --profile-id <PROFILE_ID> --job-id <JOB_ID> --note "German C1 required"
```

Set lifecycle status:

```powershell
python -m app.cli applications set-status --profile-id <PROFILE_ID> --job-id <JOB_ID> --status applied --note "Applied via company website"
```

Link a CV artifact and mark it ready:

```powershell
python -m app.cli applications cv-ready --profile-id <PROFILE_ID> --job-id <JOB_ID> --cv-artifact-id <ARTIFACT_ID> --note "FlowCV exported"
python -m app.cli applications attach-cv --profile-id <PROFILE_ID> --job-id <JOB_ID> --cv-artifact-id <ARTIFACT_ID> --note "FlowCV reviewed"
```

Set a follow-up:

```powershell
python -m app.cli applications follow-up --profile-id <PROFILE_ID> --job-id <JOB_ID> --date 2026-07-15 --note "Follow up after one week"
```

Review tracked work:

```powershell
python -m app.cli applications list --profile-id <PROFILE_ID>
python -m app.cli applications list --profile-id <PROFILE_ID> --status shortlisted
python -m app.cli applications due --profile-id <PROFILE_ID> --date 2026-07-15
python -m app.cli applications history --profile-id <PROFILE_ID> --job-id <JOB_ID>
```

All application CLI commands print JSON.

## CV Integration

CV generation remains explicit and offline by default. To mark the generated
rule-based artifact as ready in the application tracker, opt in:

```powershell
python -m app.cli cv generate --job-id <JOB_ID> --profile-id <PROFILE_ID> --force-regenerate --mark-cv-ready
```

Without `--mark-cv-ready`, CV generation does not change application status.
The dashboard **CV Workflow** page can list generated artifacts, preview/copy
FlowCV text, explicitly reveal evidence reports, and attach a reviewed artifact
to a tracked application.

## Dashboard

The Applications page shows total tracked jobs, shortlisted/applied counts, due
follow-ups, score context, status, priority, notes preview, and immutable
history. Mutating actions require explicit confirmation and delegate to the
application service.

## Suggested Daily Use

1. Run the pipeline and review `top_jobs`.
2. Shortlist the best matches with the CLI or dashboard.
3. Generate a CV for a shortlisted full-description job.
4. Mark the CV ready only after review/export.
5. Mark applied after submitting manually on the employer site.
6. Set follow-up dates and review `applications due` daily.

See [the CV workflow guide](CV_WORKFLOW.md) for artifact preview and copy steps.
