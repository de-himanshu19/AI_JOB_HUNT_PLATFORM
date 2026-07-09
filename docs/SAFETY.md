# Safety Model

The platform is designed for assisted review, not unsupervised job application
automation.

## Local-First Defaults

- The app starts without a `.env`.
- `TELEGRAM_ENABLED=false` by default.
- `AI_ENABLED=false` by default.
- `AI_PROVIDER=rule_based` by default.
- Local SQLite is the primary store.
- `data/`, runtime databases, private CV artifacts, and real `.env` files are
  not committed.

## No Auto-Apply

The platform never submits applications. Application tracking is a local CRM for
shortlisting, CV preparation, manual apply status, interviews, offers,
rejections, withdrawals, notes, and follow-up dates.

## Live Collection Requires Opt-In

Automated tests use fixtures and temporary databases. Source adapters do not
make live requests unless a user explicitly runs a live command such as:

```powershell
python -m app.cli collect arbeitsagentur --live --query "Data Analyst"
```

The one-command pipeline also avoids live collection unless `--live-collect` is
present.

## Telegram Safety

Telegram preview is offline. Real Telegram delivery requires all of:

- `TELEGRAM_ENABLED=true`
- A locally configured bot token and chat ID
- An explicit live send command

Notification batches include idempotency and retry records so successful chunks
are not resent during failed-chunk retry.

## AI Safety

AI is never called by default. Live AI polish requires:

- `AI_ENABLED=true`
- A supported provider such as `openai_compatible` or `ollama_cloud`
- A user-provided local `AI_API_KEY`
- Explicit `--ai-polish` and `--live-ai`, or an explicit dashboard confirmation

The rule-based CV remains the source of truth. AI output is stored only as a
separate child artifact after validation passes.

## Protected-Fact Validation

The validator rejects AI output that removes or changes protected facts such as:

- Candidate name and contact details
- Dates
- Employers
- Job titles
- Education
- Certifications
- Languages and levels
- Work authorization
- Verified tools, projects, and claims

It also rejects unsupported stronger wording, unsupported named facts, broken
characters, and unsafe structural changes.

## Secrets And Private Data

- Do not commit `.env`.
- Do not commit API keys or tokens.
- Do not commit `data/`, generated CV artifacts, private evidence reports, or
  local SQLite databases.
- Do not copy credentials from `existing_projects/`.
- Do not log raw source payloads, prompts, CV text, job descriptions, API keys,
  token-bearing URLs, or AI response bodies.

## Dashboard Safety

Dashboard startup and browsing are passive. A page load must not:

- Collect jobs
- Contact Telegram
- Contact AI providers
- Generate CVs
- Change application status
- Approve duplicate merges
- Open external vacancy links

Mutations require explicit user action. Destructive or live actions require
confirmation.
