# Truthful CV Generation

Milestone 7 generates an authoritative deterministic FlowCV TXT plus a private
evidence report. It does not mutate shortlist or application status and needs no
network connection in normal operation.

## Commands

```powershell
python -m app.cli cv generate --job-id <job-id> --profile-id <profile-id>
python -m app.cli cv generate-manual --description-file <path> --profile-id <profile-id>
python -m app.cli cv list --job-id <job-id>
python -m app.cli cv show <artifact-id>
```

Stored-job generation accepts only the latest `full` description. Snippet and
missing descriptions fail with guidance to use the manual command. Manual input
is UTF-8 `.txt` or `.md`, bounded by `CV_MANUAL_MAX_BYTES`, hashed by content,
and recorded with no job, description-row, cluster, or stored-analysis ID.

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

## Identity and storage

The authoritative cache identity hashes generation mode, description row/hash,
profile ID/version/hash, analysis ID, analyzer/rules identity, generator and
formatter versions, and the complete fit-rule configuration hash. An identical
request reuses the existing validated artifact after checking both file hashes
and the configured artifact root.

`cv_generation_artifacts` is the canonical Milestone 7 table. It is additive so
the original `cv_artifacts` rows remain readable. UUID-only filenames are written
atomically under `CV_ARTIFACT_ROOT`; no candidate name or job title enters a
filename. Failed database persistence removes newly written files.

## Optional AI derivative

AI polishing requires both `--ai-polish` and `--live-ai`, plus
`AI_PROVIDER=local_ollama` or `ollama_cloud`. OpenAI is not supported. Successful
output is validated and stored as a separate child artifact. Timeout, provider,
malformed-content, incomplete-section, protected-fact, unsupported-number/tool,
or stronger-wording failures create a safe `cv_ai_attempts` failure record and
leave the rule-based artifact unchanged.

Prompts, CV/JD text, response bodies, credentials, and token-bearing URLs are
never logged. Automated tests inject fake providers and make no live request.
