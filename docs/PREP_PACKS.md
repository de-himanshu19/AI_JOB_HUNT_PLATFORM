# Prep Packs

Prep packs are local markdown drafts for manual applications and interviews.
They combine stored job data, deterministic fit analysis, application status,
and CV artifact references into one review document.

They do not submit applications, send emails, send Telegram messages, call AI,
or change application status.

## Command

```powershell
python -m app.cli prep pack --profile-id <profile-id> --job-id <job-id>
```

Optional flags:

- `--cv-artifact-id <artifact-id>`: reference a specific reviewed CV artifact.
- `--output-dir data/prep_packs`: choose the markdown output directory.
- `--format markdown`: currently the only supported format.
- `--force`: overwrite if the generated filename already exists.

The command returns JSON with status, job/profile IDs, authority, selected CV
artifact ID, output path, and warnings.

## Output

Default files are written under ignored local runtime storage:

```text
data/prep_packs/prep_<job_id>_<timestamp>.md
```

The generated markdown contains:

- Job snapshot
- Fit summary
- Evidence-backed fit points
- Gaps and risks
- Tailored CV reference
- Cover letter draft
- Interview talking points
- Recruiter questions
- Application checklist
- Suggested CLI next actions

## Evidence Rules

Prep packs are intentionally conservative. They use stored profile evidence,
job descriptions, deterministic fit-analysis output, application metadata, and
CV artifact metadata.

They must not invent degrees, certifications, tools, German level, seniority,
company facts, achievements, or metrics.

For snippet or missing job descriptions, the pack is a lighter discovery pack.
It warns that the fit is `prefilter_only` and recommends opening the original
vacancy before applying.

## Dashboard

The Job Detail page has an explicit **Create Prep Pack** button and lists latest
local prep-pack files when present. It never generates files on page load. CLI
commands remain available for advanced/operator workflows outside the normal
dashboard flow.

## Review Before Use

Cover letters are drafts only. Review the original vacancy, edit the wording,
confirm work authorization and availability, and apply manually outside the
system.
