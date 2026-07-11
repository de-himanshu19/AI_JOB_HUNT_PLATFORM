# Manual Applications

Manual application packages help prepare the final files and notes for a job
application. They are local folders only. The system never submits forms,
uploads documents, sends email, sends Telegram messages, or applies on your
behalf.

## Create An Application Package

```powershell
python -m app.cli application-pack create `
  --profile-id <profile-id> `
  --job-id <job-id>
```

Optional flags:

- `--cv-artifact-id <artifact-id>`: select a specific reviewed CV artifact.
- `--prep-pack-path <path>`: reuse a specific prep pack for the cover letter.
- `--output-dir data/application_packs`: choose the local output directory.
- `--include-cv-text`: copy local CV artifact text into the package.
- `--force`: overwrite an existing package folder with the same generated name.

By default, CV artifacts are referenced by ID/path only. CV text is copied only
when `--include-cv-text` is explicitly supplied.

## Package Contents

Each package folder contains:

- `README_CHECKLIST.md`
- `job_snapshot.md`
- `cover_letter_draft.md`
- `cv_reference.md`
- `submission_notes.md`
- `follow_up_plan.md`

Default output is ignored by git:

```text
data/application_packs/
```

## Manual Submission Tracking

After you apply manually, record it explicitly:

```powershell
python -m app.cli applications submit-manual `
  --profile-id <profile-id> `
  --job-id <job-id> `
  --note "Applied manually via company website" `
  --follow-up-date YYYY-MM-DD
```

Optional metadata:

- `--applied-date YYYY-MM-DD`
- `--channel "company website"`
- `--reference "confirmation number"`

This command uses the existing application tracking workflow to mark the local
record as `applied`, append notes/events, and set a follow-up date when
provided. It does not validate an external portal and does not send anything.

## Dashboard

The dashboard daily flow is:

```text
Review Jobs -> Review Tray -> Job Detail -> CV/Cover Letter -> Apply manually -> Applications
```

The Review Tray is backed by existing local application tracking and displayed
as the working queue for jobs worth action. Job Detail offers explicit
local-only buttons for CV, cover-letter, prep-pack, application-pack, and Mark
Applied actions; nothing runs on page load and nothing is submitted externally.

When marking a job applied from the dashboard, the default follow-up date is
seven days from today. The status changes only after an explicit button click
and confirmation.

## Safety Notes

- Review every file before applying.
- Confirm the original posting is still active.
- Confirm location, language expectations, and work mode.
- Save confirmation/reference numbers manually.
- Update the local application status only after you submit the application
  yourself.
