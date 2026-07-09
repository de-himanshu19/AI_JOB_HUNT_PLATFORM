# Truthful CV Generation

Milestone 7 generates an authoritative deterministic FlowCV TXT plus a private
evidence report. It does not mutate shortlist or application status and needs no
network connection in normal operation.

## Commands

```powershell
python -m app.cli cv generate --job-id <job-id> --profile-id <profile-id>
python -m app.cli cv generate-manual --description-file <path> --profile-id <profile-id>
python -m app.cli cv generate --job-id <job-id> --profile-id <profile-id> --force-regenerate
python -m app.cli cv list --profile-id <profile-id>
python -m app.cli cv list --job-id <job-id>
python -m app.cli cv show --artifact-id <artifact-id>
python -m app.cli cv show --artifact-id <artifact-id> --text
python -m app.cli cv show --artifact-id <artifact-id> --evidence
python -m app.cli cv polish --artifact-id <rule-based-artifact-id> --live-ai
```

Stored-job generation accepts only the latest `full` description. Snippet and
missing descriptions fail with guidance to use the manual command. Manual input
is UTF-8 `.txt` or `.md`, bounded by `CV_MANUAL_MAX_BYTES`, hashed by content,
and recorded with no job, description-row, cluster, or stored-analysis ID.
`cv show` prints metadata by default; full CV text and private evidence reports
require explicit flags. See [CV workflow](CV_WORKFLOW.md) for dashboard copy and
application-attachment steps.

## Authority and evidence

The rule-based artifact is always generated and validated first. It consumes
the exact candidate profile version and exact Milestone 5 analysis for the
selected description. Evidence remains classified as direct professional,
transferable professional, project, education/training/certification, or
missing. Missing requirements stay visible in the private report.

The recruiter-facing TXT contains only CV sections. Evidence classifications,
risk flags, rules, hashes, and database identifiers appear only in the private
report or SQLite metadata. Candidate facts are copied from the versioned profile;
formatting does not promote courses to employment, exposure to ownership,
projects to professional experience, or language levels to stronger claims.

The rule-based FlowCV formatter targets a concise two-page copy-paste draft for
Data Analyst-style applications. It caps the professional summary at five
wrapped lines, groups skills separately from languages, combines same-company
experience blocks, limits each role to a small set of strongest JD-relevant
bullets, limits projects to the top two with at most three bullets each, and
removes broken Unicode/control characters before writing the artifact. Job-fit
evidence still drives selection; unsupported skills or stronger language claims
remain excluded by the validator.

Certifications and courses are rendered as a compact Data Analyst-focused list:
Data Analytics Program, SQL for Data Analysis, Complete Guide to Power BI for
Data Analysts, Python Statistics Essential Training, and optional Advanced SQL.
Additional information is normalized to concise work-authorization,
availability, relocation, hybrid-work, and travel bullets so it does not spill
onto a third page.

## Identity and storage

The authoritative cache identity hashes generation mode, description row/hash,
profile ID/version/hash, analysis ID, analyzer/rules identity, generator,
formatter, builder-content versions, and the complete fit-rule configuration
hash. An identical request reuses the existing validated artifact after checking
both file hashes and the configured artifact root. `--force-regenerate` bypasses
reuse by creating a fresh identity, preserving old artifacts and evidence
reports.

`cv_generation_artifacts` is the canonical Milestone 7 table. It is additive so
the original `cv_artifacts` rows remain readable. UUID-only filenames are written
atomically under `CV_ARTIFACT_ROOT`; no candidate name or job title enters a
filename. Failed database persistence removes newly written files.

## Optional AI derivative

Milestone 13 supports an explicitly enabled OpenAI-compatible chat-completions
API provider. Rule-based generation remains the default and needs no AI
credentials. API polish requires all of:

```text
AI_ENABLED=true
AI_PROVIDER=openai_compatible
AI_API_KEY=
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=<model name>
AI_TIMEOUT_SECONDS=30
AI_MAX_RETRIES=2
```

Generation-time polish requires both `--ai-polish` and `--live-ai`:

```powershell
python -m app.cli cv generate --job-id <job-id> --profile-id <profile-id> --force-regenerate --ai-polish --live-ai
```

Existing rule-based artifacts can be polished separately:

```powershell
python -m app.cli cv polish --artifact-id <rule-based-artifact-id> --live-ai
```

The request sends CV text and protected-fact instructions to the configured
external API. Never commit real API keys. Prompts, CV/JD text, response bodies,
credentials, and token-bearing URLs are never logged.

Successful output is validated and stored as a separate child artifact with
`parent_rule_based_artifact_id`, provider, model, prompt version, and validation
metadata. Timeout, rate-limit, provider, malformed-response, safety, config,
protected-fact, unsupported-number/tool, broken-character, or stronger-wording
failures create a safe `cv_ai_attempts` failure record and leave the
rule-based artifact unchanged.

Automated tests inject fake providers and make no live AI request.
