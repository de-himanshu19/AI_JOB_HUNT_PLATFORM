# Local Operations Dashboard

Milestone 8 adds an optional Streamlit dashboard over the existing application
services. It introduces no scoring, duplicate, lifecycle, notification, or CV
business rules and requires no migration 007.

## Install and launch on Windows

From the repository root:

```powershell
python -m pip install -e ".[dashboard,test]"
python -m app.dashboard
```

The `job-hunt-dashboard` console script is also installed, but `python -m
app.dashboard` is reliable when the user Scripts directory is not on `PATH`.
The launcher resolves `Home.py` absolutely, starts Streamlit headlessly, and
disables usage telemetry.

## Pages

- Overview summarizes logical and source jobs, analysis/ranking coverage,
  duplicate reviews, applications, runs, notifications, and CV artifacts.
- Jobs provides composable filters, stable sorting and pagination, logical
  vacancy view by default, and an explicit source-record mode.
- Job Detail shows the selected source record, full description on demand,
  original link, duplicate provenance, analysis, ranking, application history,
  notifications, and both legacy and current CV artifacts.
- Duplicate Review delegates approve/reject/split actions to the existing
  transactional deduplication service.
- Applications delegates only allowed transitions to `ApplicationService` and
  displays immutable event history.
- CV Builder delegates stored-job and manual-JD generation to Milestone 7.
- Notifications provides offline preview and notification audit history.
- Runs & Diagnostics displays safe counters, errors, migration state, and
  foreign-key status without raw payloads or private documents.

## Passive startup and safety

Opening or browsing the dashboard may initialize migrations 001-006 on an empty
database, but it never collects jobs, opens external links, generates a CV,
changes application state, reviews duplicates, or creates a live integration
client. Original vacancy links require a deliberate user click.

`TELEGRAM_ENABLED=false` and `AI_PROVIDER=rule_based` are safe defaults. Live
Telegram requires enabled credentials, acknowledgement, the exact text `SEND
TELEGRAM`, and a final click. AI polishing requires both request and live-AI
confirmation. Automated tests inject a network tripwire and use no live client.

Streamlit session state contains stable IDs, filters, confirmations, and safe
result summaries only. Read-only projections have short caches; database
connections and secrets are never cached. Every completed mutation clears read
caches, while session action tokens and service/database idempotency protect
against duplicate rerun submissions.

## Logical-vacancy policy

Jobs default to one representative per Milestone 4 cluster. Application and CV
history is aggregated across source members for display. New tracking attaches
to the representative. If multiple member-level application records exist, the
dashboard shows a conflict warning and does not merge or rewrite history.
