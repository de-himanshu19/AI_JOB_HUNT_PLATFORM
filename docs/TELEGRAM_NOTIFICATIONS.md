# Telegram Top-20 Notifications

Milestone 6 delivers at most 20 new authoritative logical vacancies from stored
Milestone 5 rankings. Selection is cluster-based, so Arbeitsagentur and
EnglishJobs copies of one vacancy are never sent separately.

## Safety boundary

Preview is offline and does not write notification state:

```powershell
python -m app.cli notify telegram preview --profile-id <profile-id>
```

Network delivery requires both explicit live mode and enabled credentials:

```powershell
python -m app.cli notify telegram send --profile-id <profile-id> --live
```

`TELEGRAM_ENABLED` defaults to `false`. Do not enable it until the legacy token
and chat destination have been rotated and reviewed. Routine tests use injected
fake clients and never contact Telegram.

## Selection and idempotency

Eligible rows must be active Milestone 4 cluster representatives with an
authoritative stored ranking for the requested profile and ranking version.
Rows are ordered by the persisted Milestone 5 ordering and capped at 20.

A pending or successful `(cluster, duplicate version, profile, channel)` item is
excluded from subsequent batches. Reservations and selection share one SQLite
write transaction, preventing concurrent processes from claiming the same
logical vacancy. Failed items are eligible for explicit retry; successful items
are never moved back to pending.

## Chunks and retries

Messages are deterministic plain text and remain below
`TELEGRAM_MESSAGE_MAX_CHARS` (default 4000, maximum 4096). Every chunk has an
independent delivery attempt and payload hash. A failed chunk marks only its
items failed; later chunks are still attempted.

```powershell
python -m app.cli notify telegram retry --batch-id <batch-id> --live
python -m app.cli notify list
python -m app.cli notify show <batch-id>
```

Retry reconstructs the failed chunk from its stored job/ranking snapshot and
creates a new attempt. Successful chunks are not resent.

## Logging and persistence

Logs contain only safe attempt metadata. Bot tokens, chat IDs, token-bearing
URLs, message payloads, response bodies, descriptions, and authentication data
are not logged. SQLite stores concise notification snapshots, payload hashes,
safe error categories, and remote message IDs for auditability.

## Limitations

Telegram cannot provide exactly-once delivery across an external success followed
by a local database crash. Pending reservations are intentionally retained for
manual inspection in that rare state. This milestone adds no scheduler, email,
shortlist mutation, application action, CV generation, or UI.
