# Security Checklist

## Required before any live integration

- [ ] Rotate the legacy OpenAI API key discovered during the audit.
- [ ] Rotate the legacy Telegram bot token discovered during the audit.
- [ ] Review and, if appropriate, replace the legacy Telegram chat destination.
- [ ] Rotate the legacy MySQL password and review the associated database user privileges.
- [ ] Remove plaintext credential notes from active working copies after rotation and after any required evidence/backup review.
- [ ] Confirm the rotated credentials are not present in repository history, issue attachments, terminal transcripts, logs, or generated reports. If they are, follow an approved history-remediation procedure.
- [ ] Enable provider-side usage alerts and inspect recent usage for the retired credentials.

This repository does not copy or display any discovered credential value. Rotation must be performed through the relevant provider/account and cannot be completed by local code alone.

## Unified root controls implemented

- [x] Root `.env` and local variants are ignored; `.env.example` contains safe placeholders only.
- [x] The settings loader starts without credentials and validates them only when their feature is enabled.
- [x] Names containing `TOKEN`, `KEY`, `PASSWORD`, `SECRET`, or `CHAT_ID` are redacted from settings diagnostics.
- [x] Structured logging omits full CV, candidate-profile, source-payload, and job-description values.
- [x] SQLite runtime files and generated artifact directories are ignored.
- [x] Tests use fixtures and temporary files only; they make no external calls.
- [x] Telegram, OpenAI, Ollama Cloud, and MySQL are disabled or absent from the Milestones 0–1 runtime.

## Before enabling a future source or notification adapter

- [ ] Add adapter-specific timeout, retry, rate-limit, and safe-error tests.
- [ ] Confirm logs contain IDs and summaries, not authentication headers or source payloads.
- [ ] Confirm `.env` file permissions are appropriate for the local account.
- [ ] Run a secret scanner over all new root files.
- [ ] Review EnglishJobs retrieval behavior and terms before implementing full-description retrieval.
- [ ] Confirm notification idempotency tests pass before enabling Telegram.

## Arbeitsagentur adapter controls

- [x] The web-client API key is a configurable source default and is redacted from settings diagnostics even though it is not treated as a private user credential.
- [x] Authentication headers and full payloads/descriptions are absent from routine logs.
- [x] Connect/read timeouts, bounded retries, exponential backoff, and permanent-4xx behavior are fixture-tested.
- [x] The normal suite and default CLI mode make no network calls.
- [x] Live HTTP requires the explicit `--live` flag; the live pytest case additionally requires `RUN_ARBEITSAGENTUR_LIVE_TEST=1`.
- [x] Saved fixtures contain no credentials or unnecessary personal contact details.

## EnglishJobs adapter controls

- [x] No API key or credential is required for the implemented adapter path.
- [x] Connect/read timeouts, bounded retries, backoff, request delay, and permanent-4xx behavior are fixture-tested.
- [x] The normal suite and default CLI mode make no network calls.
- [x] Live HTTP requires the explicit `--live` flag; the live pytest case additionally requires `RUN_ENGLISHJOBS_LIVE_TEST=1`.
- [x] Clickout resolution records canonical destination URLs conservatively and does not fabricate full descriptions from unresolved external pages.
- [x] Saved fixtures contain no credentials or unnecessary personal details.

## Telegram notification controls

- [x] Preview/list/show are offline and do not instantiate a live client.
- [x] Send/retry require both explicit `--live` and `TELEGRAM_ENABLED=true`.
- [x] Timeouts, bounded retries, 429/5xx, permanent 4xx, malformed responses, and transport failures use fake clients in tests.
- [x] Tokens, chat IDs, token-bearing URLs, payloads, response bodies, and transport exception messages are absent from logs.
- [x] Cluster-level pending/success constraints and concurrency tests prevent duplicate logical-vacancy sends.
- [x] Partial failures retry only failed chunks and preserve successful delivery state.
- [ ] Rotate and review Telegram credentials before any real send.

## Local dashboard controls

- [x] Dashboard startup and page browsing require no API key or integration credential.
- [x] Automated page tests fail if a `requests.Session` attempts an external request.
- [x] Streamlit usage telemetry is disabled in local configuration and the launcher.
- [x] Pages contain no SQL or duplicated business rules; mutations call existing services.
- [x] Live Telegram and AI controls are disabled by safe defaults and require layered confirmation.
- [x] Full descriptions load only for selected detail views, not job-table rows.
- [x] Secrets, prompts, CV/JD text, payloads, and provider responses are excluded from diagnostics.
- [x] Original vacancy links open only through an explicit user click.

## Legacy import controls

- [x] Legacy import dry-run writes no database data and makes no network calls.
- [x] Apply requires an explicit verified SQLite backup ID.
- [x] Legacy `.env` files are not imported, displayed, parsed, or logged.
- [x] CSV descriptions are marked as snippets unless source evidence proves full text.
- [x] Legacy scores remain reference metadata and are not authoritative Milestone 5 analyses/rankings.
- [x] `sent_jobs.json` mappings suppress Telegram only when mapped exactly to a current clustered vacancy.
- [x] Legacy artifacts are copied as immutable, content-hashed, non-authoritative records.
- [x] `LEGACY_MYSQL_ENABLED=false` by default; tests use fixture readers and no real MySQL credentials.
- [x] The optional MySQL boundary rejects write/DDL statements.

## Incident response

If a secret is exposed: disable the affected feature, revoke/rotate the credential at the provider, inspect usage, remove it from current files and logs, assess repository history, and document the incident without reproducing the secret.
