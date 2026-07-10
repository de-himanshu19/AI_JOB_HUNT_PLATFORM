# Release Notes

## v0.1.0-local-portfolio

Release date: 2026-07-10

This release packages the AI Job Hunt Platform as a local-first GitHub
portfolio project. It is designed for demonstration, learning, and personal
job-search operations, not as a hosted production SaaS product.

## Completed Milestone Summary

- M0-M9: typed settings, SQLite persistence, source adapters, deduplication,
  fit analysis, ranking, dashboard foundation, and legacy import.
- M10: one-command local pipeline.
- M11: application tracking CRM.
- M12: CV workflow dashboard.
- M13: safe API-based AI CV polish with protected-fact validation.
- M14: portfolio/demo documentation package.
- M15: improved EnglishJobs detail extraction.
- M16: local daily scheduler.
- M17: run-scoped ranking for clearer daily digests.
- M18: application analytics dashboard.
- M19: evidence-backed prep packs.
- M20: manual application package workflow.
- M21: safe communication draft generation.
- M22: final portfolio release documentation and cleanup.

## Major Capabilities

- Collect jobs from Arbeitsagentur and EnglishJobs with explicit live opt-in.
- Persist jobs, descriptions, profiles, analyses, rankings, applications, CV
  artifacts, and notification history in SQLite.
- Deduplicate source records into logical vacancies.
- Analyze job fit deterministically from stored candidate evidence.
- Rank vacancies globally or scoped to a current run.
- Preview Telegram notifications without sending by default.
- Track applications, priorities, notes, follow-ups, CV readiness, and history.
- Generate FlowCV-ready rule-based CV text and optional validated AI-polished
  child artifacts.
- Prepare local prep packs, application packages, and communication drafts.
- Review jobs, applications, analytics, CV artifacts, and diagnostics in a
  local Streamlit dashboard.

## Safety Guarantees

- No auto-apply.
- No email sending.
- No Telegram send unless explicitly configured and invoked.
- No AI call unless explicitly requested with live AI flags.
- No hidden live collection during ordinary tests or dashboard browsing.
- `.env`, databases, generated artifacts, logs, daily runs, and local configs
  are ignored.
- AI-polished CVs are stored only when protected-fact validation passes.

## Known Limitations

- The dashboard is local and single-user only.
- EnglishJobs full descriptions remain conservative; many listings are
  snippet-only.
- Fit scores are deterministic and explainable, but still require human review.
- FlowCV output is plain text; PDF/DOCX export is handled outside the app.
- Live integrations require manual opt-in and careful credential handling.
- No application is submitted automatically.

## Not Implemented / Future Work

- Hosted multi-user deployment.
- Auto-apply or portal automation.
- Broader source coverage.
- Richer analytics calibrated against real outcomes.
- More polished anonymized screenshots and fixture demo data.
- Stronger live Telegram operator safeguards.

## Test Status

Latest release verification target:

```text
python -m pytest
python -m compileall app tests
git diff --check
git diff -- existing_projects
```

Current verified full-suite baseline: `315 passed, 2 skipped`.

The skipped tests are optional live smoke tests for Arbeitsagentur and
EnglishJobs and require explicit environment opt-in.

## Local Demo

```powershell
python -m pip install -e ".[dashboard,test]"
python -m app.db.migrations
python -m pytest
python -m app.dashboard
```

See [DEMO.md](DEMO.md) for a complete end-to-end walkthrough.
