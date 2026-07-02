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

## Incident response

If a secret is exposed: disable the affected feature, revoke/rotate the credential at the provider, inspect usage, remove it from current files and logs, assess repository history, and document the incident without reproducing the secret.
