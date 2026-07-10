# Interview Guide

## 60-Second Explanation

I built a local-first AI Job Hunt Platform to make job searching more
structured and auditable. It collects jobs from supported sources, stores them
in SQLite, deduplicates listings, analyzes fit against a versioned candidate
profile, ranks opportunities, tracks applications, and generates safe CV and
application materials.

The key design choice is safety: the app never auto-applies, never sends
messages by default, and never calls AI unless explicitly requested. AI-polished
CVs are validated against protected facts before they can be stored.

## Architecture Explanation

The application is layered:

- CLI and Streamlit dashboard are entry points.
- Services own workflows such as collection, deduplication, analysis, ranking,
  CV generation, tracking, analytics, and draft generation.
- Repositories isolate SQLite access.
- Source adapters normalize external job-source payloads.
- Artifact services write local generated files under ignored runtime paths.
- Tests use fixtures and injected clients to avoid live network calls.

## Data Flow

Candidate profile and job-source data flow into SQLite. Jobs receive versioned
descriptions, then deduplication groups source records into logical vacancies.
Fit analysis reads full descriptions and candidate evidence. Ranking produces
top opportunities. The dashboard and CLI then expose review, tracking, CV, prep,
application-package, communication-draft, and analytics workflows.

## Why Local-First

The project handles private job-search data, CV material, notes, and potential
credentials. Local-first design keeps those artifacts under user control and
makes it easier to guarantee that dashboard browsing or tests do not trigger
external actions.

## Why No Auto-Apply

Auto-applying is risky: job postings vary, portals require judgment, and
applications represent the candidate personally. The system prepares materials
and tracks status, but the user applies manually.

## Why AI Output Is Validated

CVs contain protected facts such as dates, employers, degrees, language levels,
work authorization, and contact details. AI can improve wording, but it must not
silently change facts or add unsupported claims. The rule-based artifact remains
authoritative, and AI child artifacts are stored only after validation.

## Testing Approach

The project uses fixture-first pytest coverage. Live source tests are separated
behind opt-in environment variables. Integration tests cover persistence,
pipeline behavior, CV generation, application tracking, dashboard startup,
analytics, prep packs, application packages, and communication drafts.

## Biggest Engineering Challenges

- Keeping external integrations explicit and testable.
- Separating source records from logical vacancies.
- Preserving historical analyses, rankings, CV artifacts, and application
  events.
- Preventing AI polish from changing protected facts.
- Keeping the Streamlit dashboard thin instead of embedding business logic in
  pages.
- Designing useful local automation without crossing into auto-apply behavior.

## Limitations And Next Improvements

- It is a local single-user app, not hosted SaaS.
- EnglishJobs descriptions remain conservative when full text is not safely
  available.
- Fit scoring is deterministic but should be calibrated with more reviewed
  outcomes.
- Final portfolio screenshots still need anonymized capture.
- More job sources could be added behind the existing adapter contract.

## Possible Interview Questions

### Why SQLite?

SQLite is enough for a local single-user workflow, easy to inspect, and works
well with ordered migrations and transaction-scoped repositories.

### How do you avoid accidental live actions?

Live actions require explicit CLI flags or confirmations. Tests use fake clients
and fixtures. Dashboard page loads are passive.

### What makes the AI part safe?

AI is optional, live-only when explicitly requested, and output must pass
protected-fact validation before it becomes a stored child artifact.

### How is this different from a scraper?

Scraping is only one adapter boundary. The broader system includes persistence,
deduplication, fit analysis, ranking, CRM, CV generation, analytics, scheduling,
and application preparation.

### What would you improve next?

I would add anonymized screenshots, richer analytics from real outcomes, more
source adapters, and better safe demo fixtures.
