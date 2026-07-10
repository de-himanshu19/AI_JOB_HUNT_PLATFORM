# Roadmap

This roadmap summarizes completed milestones and the planned direction. It is
not a commitment to implement future items automatically.

## Completed

### M0-M9: Foundation Through Legacy Import

- Typed configuration, safe defaults, and secret redaction.
- Shared domain models and SQLite persistence.
- Arbeitsagentur and EnglishJobs source adapters.
- Description completeness tracking.
- Deduplication and duplicate review.
- Candidate profile import.
- Fit analysis and logical-vacancy ranking.
- Telegram preview/live-send infrastructure with explicit opt-in.
- FlowCV rule-based generation foundation.
- Streamlit dashboard.
- Legacy local-file import with backup, dry-run, apply, verify, and reconcile.

### M10: One-Command Pipeline

- Safe local pipeline orchestration for collection, deduplication, analysis,
  ranking, notification preview, top-job display, and JSON summaries.
- No external source request unless `--live-collect` is supplied.

### M11: Application Tracking CRM

- Local shortlist/status/priority/note/follow-up workflows.
- Immutable application event history.
- CV artifact link support.
- Pipeline and dashboard visibility into existing application status.

### M12: CV Workflow Dashboard

- Dashboard CV artifact listing and review.
- Copy-friendly FlowCV text and private evidence report views.
- Application attachment workflow for reviewed artifacts.

### M13: Safe API AI Polish

- OpenAI-compatible and native Ollama Cloud providers.
- Explicit live AI gates.
- Conservative prompt and safe polish mode.
- Protected-fact validation.
- Separate AI child artifacts only after validation passes.

### M14: Portfolio Polish And Demo Package

- Portfolio-quality README.
- Demo, architecture, safety, and roadmap docs.
- Screenshot placeholders without committing private images.

### M15: EnglishJobs Full-Description Extraction

- Safer EnglishJobs-hosted detail-page parsing.
- Strict full-description quality heuristics.
- External clickout/apply-only pages remain snippet-level.
- Collection and pipeline diagnostics include detail request and completeness
  counters.

### M16: Local Scheduler / Daily Job Run

- Safe `daily run` and `daily run-config` CLI workflows.
- Local JSON run history under `data/daily_runs/`.
- Conservative lock file under `data/locks/daily_run.lock`.
- PowerShell wrapper for Windows Task Scheduler.
- Passive dashboard visibility for recent daily runs.

### M17: Run-Scoped Ranking And Daily Digest Clarity

- Pipeline supports `global` and `current-run` ranking scopes.
- Existing pipeline behavior remains global by default.
- Daily search configs default to current-run ranking for clearer source/search
  review.
- Current-run notification preview uses scoped rankings, including EnglishJobs
  `prefilter_only` discovery jobs when explicitly allowed.

### M18: Application Analytics Dashboard

- Read-only Streamlit Applications Analytics page.
- Funnel, source quality, follow-up, and recent activity metrics from existing
  database records.
- Passive daily-run analytics from saved `data/daily_runs` JSON summaries.
- CLI JSON summary via `python -m app.cli analytics summary --profile-id <id>`.

### M19: Interview/Application Prep Pack

- Local evidence-backed markdown prep packs for selected jobs/applications.
- Cover letter draft, interview talking points, recruiter questions, and
  application checklist without auto-apply or send actions.
- Prefilter-only discovery packs warn when descriptions are snippet/missing.
- Dashboard Job Detail shows the exact prep-pack CLI command and latest local
  prep-pack files passively.

### M20: Manual Application Submission Workflow

- Local application package folders for final manual review.
- Checklist, job snapshot, cover letter draft, CV reference, submission notes,
  and follow-up plan files.
- CV text is referenced by default and copied only with explicit
  `--include-cv-text`.
- `applications submit-manual` records local applied status and follow-up only
  after the user applies manually.
- Dashboard Job Detail shows exact package/submission commands passively.

### M21: Follow-Up And Communication Drafts

- Local markdown drafts for follow-ups, recruiter replies, interview
  availability, thank-you notes, rejection responses, and status updates.
- Drafts use stored application/job/profile context and placeholders for
  uncertain names, dates, and reference numbers.
- Optional `--record-event` appends a local note without changing status.
- Dashboard Job Detail shows exact draft commands and latest local draft files
  passively.

## Planned

- Continue improving EnglishJobs full-description extraction where safe and
  permitted.
- Improve scheduler observability and daily-run review.
- Add stronger live Telegram safeguards and operator previews.
- Add more safe job sources behind the shared adapter contract.
- Improve analytics calibration with reviewed outcomes and longer trend windows.
- Add richer prep-pack templates after enough reviewed application feedback.
- Add richer manual-submission analytics after more tracked outcomes.
- Add richer communication templates after reviewing real reply patterns.
- Prepare final anonymized deployment/demo packaging with reviewed screenshots
  and fixture data.

## Out Of Scope For Now

- Auto-apply or direct job application submission.
- Hosted multi-user dashboard.
- Committing private job-search data or CV artifacts.
- Replacing deterministic scoring with opaque AI ranking.
