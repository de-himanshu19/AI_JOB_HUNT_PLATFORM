# Communication Drafts

Communication drafts are local markdown files for application follow-ups,
recruiter replies, interview scheduling, thank-you notes, rejection responses,
and internal status notes.

Nothing is sent automatically. The system does not email recruiters, send
Telegram messages, contact external services, call AI, or change application
status by default.

## Command

```powershell
python -m app.cli communications draft `
  --profile-id <profile-id> `
  --job-id <job-id> `
  --type follow_up
```

Supported draft types:

- `follow_up`
- `recruiter_reply`
- `interview_availability`
- `interview_thank_you`
- `rejection_response`
- `status_update`

Optional flags:

- `--output-dir data/communication_drafts`: choose local output directory.
- `--tone professional`: currently the supported tone.
- `--force`: overwrite if the generated filename already exists.
- `--record-event`: append a local application note that a draft was generated.

## Output

Drafts are written under ignored local runtime storage:

```text
data/communication_drafts/
```

The command returns JSON with status, draft type, job/profile IDs, output path,
warnings, and whether an event was recorded.

## Evidence And Placeholders

Drafts use stored job/application context only:

- job title and company
- application status and follow-up date
- CV artifact reference when available
- prep-pack and application-pack references when available
- recent application history notes
- stored profile evidence

Drafts intentionally use placeholders when details are uncertain:

- `[Recruiter Name]`
- `[Application Date]`
- `[Interview Date]`
- `[Portal/Reference Number]`

Replace placeholders manually before sending any message yourself.

## Record Event

`--record-event` adds a local application note only. It does not change status
and does not send anything.

## Dashboard

The Job Detail page shows exact CLI commands for all draft types and latest
local draft files when present. It has no send button and performs no external
communication.
