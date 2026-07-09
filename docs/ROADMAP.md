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

## Planned

- Continue improving EnglishJobs full-description extraction where safe and
  permitted.
- Improve scheduler observability and daily-run review.
- Add stronger live Telegram safeguards and operator previews.
- Add more safe job sources behind the shared adapter contract.
- Improve application analytics and follow-up reporting.
- Prepare final anonymized deployment/demo packaging with reviewed screenshots
  and fixture data.

## Out Of Scope For Now

- Auto-apply or direct job application submission.
- Hosted multi-user dashboard.
- Committing private job-search data or CV artifacts.
- Replacing deterministic scoring with opaque AI ranking.
