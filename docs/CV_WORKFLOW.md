# CV Workflow

Milestone 12 adds dashboard and CLI workflows for reviewing generated FlowCV
artifacts, copying CV text, viewing private evidence reports on demand, and
attaching reviewed CVs to application tracking.

The workflow is local and explicit. It does not generate PDF/DOCX files, send
email, send Telegram messages, auto-apply, call AI polish, or attach CVs without
a user action. Optional API-based AI polish is disabled by default and requires
explicit configuration plus a live confirmation.

## Generate A CV

Stored-job generation requires a full stored description:

```powershell
python -m app.cli cv generate --job-id <JOB_ID> --profile-id <PROFILE_ID> --force-regenerate
```

Manual JD fallback remains available for local UTF-8 text files:

```powershell
python -m app.cli cv generate-manual --description-file <path> --profile-id <PROFILE_ID>
```

Optional API polish can be requested during generation only when the user has
configured `AI_ENABLED=true`, a supported provider, and `AI_API_KEY` locally.
Use `AI_PROVIDER=openai_compatible` for chat-completions APIs, or
`AI_PROVIDER=ollama_cloud` with `AI_BASE_URL=https://ollama.com` and
`AI_MODEL=gpt-oss:20b` for native Ollama Cloud. For Ollama Cloud CV polish,
prefer `gpt-oss:20b`, not `gpt-oss-safeguard`:

```powershell
python -m app.cli cv generate --job-id <JOB_ID> --profile-id <PROFILE_ID> --force-regenerate --ai-polish --live-ai
```

Polish an existing reviewed rule-based artifact:

```powershell
python -m app.cli cv polish --artifact-id <RULE_BASED_ARTIFACT_ID> --live-ai
```

This sends CV text to the configured external AI API. The rule-based artifact
remains authoritative, and AI output is stored only as a separate validated
child artifact. `validation_failed` is expected and safe if the model changes
facts, translates content, removes required FlowCV sections, or adds unsupported
claims.
Safe polish mode is intentionally narrow: locked fact-bearing sections are
restored from the rule-based artifact, while only summary and safe key-skill
wording may remain AI-polished.

## List Artifacts

List CV artifacts for a profile or job:

```powershell
python -m app.cli cv list --profile-id <PROFILE_ID>
python -m app.cli cv list --job-id <JOB_ID>
```

The list output is JSON metadata and includes artifact paths, evidence-report
paths, generation mode, source, formatter version, validation status, and
provenance IDs.

## Show Metadata And Text

Show metadata only:

```powershell
python -m app.cli cv show --artifact-id <ARTIFACT_ID>
```

Show copy-friendly FlowCV text:

```powershell
python -m app.cli cv show --artifact-id <ARTIFACT_ID> --text
```

Show the private evidence report explicitly:

```powershell
python -m app.cli cv show --artifact-id <ARTIFACT_ID> --evidence
```

Evidence reports are for verification and debugging. They are not
recruiter-facing content.

## Copy Into FlowCV

Use the `--text` output or the dashboard text area to copy the FlowCV TXT
content into FlowCV manually. This milestone intentionally does not create PDF
or DOCX output.

## Attach CV To Application

After reviewing the CV, attach it to application tracking and mark the
application `cv_ready`:

```powershell
python -m app.cli applications cv-ready --profile-id <PROFILE_ID> --job-id <JOB_ID> --cv-artifact-id <ARTIFACT_ID> --note "FlowCV reviewed"
```

The alias below performs the same safe service workflow:

```powershell
python -m app.cli applications attach-cv --profile-id <PROFILE_ID> --job-id <JOB_ID> --cv-artifact-id <ARTIFACT_ID> --note "FlowCV reviewed"
```

The command validates the profile, job, and artifact, updates
`applications.cv_artifact_id`, moves the status to `cv_ready`, and appends an
immutable application event. It does not submit the application.
Validated AI artifacts can be attached like rule-based artifacts. Failed or
invalid AI attempts do not produce attachable ready CV artifacts.

## Dashboard Workflow

Open the dashboard:

```powershell
python -m app.dashboard
```

Use the **CV Workflow** page to:

- Generate a rule-based CV for a stored full-description job.
- List recent generated CV artifacts.
- Select an artifact and inspect metadata.
- Distinguish `rule_based` and `ai_polished` artifacts, including parent,
  provider, model, prompt, and AI attempt status metadata where available.
- Explicitly reveal the FlowCV TXT content for copying.
- Explicitly reveal the private evidence report when needed.
- Attach a selected artifact to a tracked application and mark it `cv_ready`.

The dashboard reads only artifact paths stored in SQLite. Missing local files
show a clear warning instead of failing the page.
The page never calls live AI on load. Any dashboard AI trigger requires an
explicit checkbox acknowledging that CV text will be sent to an external API.
