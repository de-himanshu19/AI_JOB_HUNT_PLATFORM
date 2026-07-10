# Portfolio Summary

## Two-Line Version

AI Job Hunt Platform is a local-first Python system that collects jobs,
deduplicates listings, ranks fit, tracks applications, and prepares truthful CV
and application materials.

It emphasizes safety: no auto-apply, no hidden network calls, no default AI,
and no generated private data committed to the repository.

## Medium Version

I built a local job-search operations platform that turns scattered job hunting
tasks into an auditable workflow. It collects roles from supported sources,
stores them in SQLite, deduplicates listings, analyzes fit against a versioned
candidate profile, ranks opportunities, tracks applications, generates
FlowCV-ready CV text, and prepares local follow-up/application materials.

The project is designed as a portfolio-quality engineering artifact: typed
domain models, migrations, repositories, service layers, CLI workflows,
Streamlit dashboard pages, fixture-first tests, and strict safety gates.

## Technical Version

The platform is a Python 3.11+ local application using Pydantic settings,
SQLite migrations, repository-pattern persistence, source adapter contracts,
deterministic fit-analysis/ranking services, optional Streamlit UI, and a large
pytest suite. It includes injected clients for external integrations so tests
run offline by default.

Major modules include collection, deduplication, fit analysis, ranking,
notifications, dashboard queries/actions, application tracking, CV generation,
AI provider abstraction, legacy import, pipeline orchestration, scheduler,
analytics, prep packs, application packages, and communication drafts.

## Business / Problem Version

Job search work becomes repetitive and hard to audit: duplicate listings,
unclear job fit, inconsistent CV tailoring, missed follow-ups, and scattered
notes. This project brings those steps into a local, evidence-backed workflow
that keeps human judgment in charge while reducing manual tracking overhead.

## Key Technologies

- Python
- SQLite
- Pydantic
- Requests
- BeautifulSoup
- Streamlit
- Pytest
- Mermaid documentation
- Optional Ollama Cloud/OpenAI-compatible AI provider interface

## Measurable Scope

- Full-suite baseline at release: `315 passed, 2 skipped`.
- 20+ milestone-scale feature areas across collection, persistence,
  deduplication, analysis, ranking, dashboard, CRM, CV generation, AI validation,
  scheduling, analytics, and application preparation.
- Multiple CLI workflows plus local dashboard pages.
- Fixture-first tests with optional live smoke tests separated by environment
  gates.

## What I Built And Learned

- Designed a local-first architecture that avoids hidden external side effects.
- Built typed domain models, migrations, repositories, and service boundaries.
- Implemented deterministic fit scoring and safe AI output validation.
- Created dashboard views without duplicating business rules in Streamlit pages.
- Practiced defensive product design around privacy, credentials, and user
  control.
- Learned how to turn a personal workflow into a demonstrable engineering
  system without overclaiming production readiness.
