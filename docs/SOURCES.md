# Job Sources

The platform treats source collection as discovery plus evidence gathering.
Every source is normalized into shared job and description models, but the
description completeness contract remains strict.

## Description Completeness

Stored descriptions are classified as:

- `full`: enough meaningful job-body text is available for authoritative
  analysis, ranking, and stored-job CV generation.
- `snippet`: useful discovery text, but not enough for authoritative analysis.
- `missing`: no usable description text was extracted.

Snippets are never marked as full. The system does not fabricate descriptions.

## Arbeitsagentur

Arbeitsagentur supports structured search and detail endpoints. When the detail
payload contains full job-body text, the adapter stores it as `full` and those
jobs can support authoritative fit analysis, ranking, and CV generation.

Live requests require an explicit `--live` collection command or
`--live-collect` pipeline request.

## EnglishJobs

EnglishJobs supports state and keyword/location search. Search result cards are
stored for discovery, and the adapter safely fetches EnglishJobs-hosted detail
pages when listing URLs are available.

Milestone 15 improves detail extraction with quality checks:

- Detail text must be meaningful job-body content.
- Full descriptions must be long enough and include job-related sections or
  keywords such as responsibilities, requirements, qualifications, benefits,
  role, tasks, profile, skills, or experience.
- Navigation, footer, cookie, metadata, redirect, and apply-only text is not
  treated as a full description.
- External company pages are not broadly scraped.
- Clickout/apply URLs can be recorded as metadata while the description remains
  snippet-level unless EnglishJobs itself provides enough full text.

EnglishJobs jobs remain useful for discovery even when only snippets are
available, and become eligible for authoritative downstream workflows only when
a real full description is collected.

## Diagnostics

Collection output includes description and detail counters:

- `jobs_collected`
- `detail_requests_attempted`
- `detail_requests_succeeded`
- `detail_requests_failed`
- `full_descriptions`
- `snippet_descriptions`
- `missing_descriptions`
- `external_redirects_seen`
- `parsing_errors`

These counters help explain whether a run produced authoritative descriptions
or discovery-only snippets.

## Safe Bounds

Collection stays bounded by page limits and selected records. EnglishJobs also
supports an optional collection flag:

```powershell
python -m app.cli collect englishjobs --dry-run --max-detail-requests 5
```

Automated tests use fixtures and injected clients. No live source request is
made by the ordinary test suite.
