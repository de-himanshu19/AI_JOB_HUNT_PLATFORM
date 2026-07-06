# Normalization and Duplicate Clustering

Milestone 4 normalizes stored jobs and identifies the same logical vacancy across
sources without deleting or replacing either source row. The workflow is fully
offline and makes no requests to Arbeitsagentur or EnglishJobs.

## Rules and versions

- Normalization version: `m4-normalization-v1`.
- Duplicate algorithm version: `m4-dedup-v1`.
- Raw titles, companies, locations, descriptions, and source URLs remain stored.
- Company aliases are loaded from `config/company_aliases.json` by default and
  can be overridden with `DEDUP_COMPANY_ALIASES_PATH` or `--alias-file`.
- Tracking parameters are removed only from the comparable canonical URL.

The matcher applies exact source identity, canonical URL identity, a strong
company/title/city/date fingerprint, then conservative cross-source similarity.
Seniority conflicts cannot auto-cluster. Gray-zone pairs are stored as pending
review candidates with their score and reasons.

## Commands

```powershell
python -m app.cli deduplicate backfill
python -m app.cli deduplicate review-list --status pending
python -m app.cli deduplicate review <candidate-id> --decision approved
python -m app.cli deduplicate review <candidate-id> --decision rejected
python -m app.cli deduplicate split <job-id>
python -m app.cli deduplicate clear --algorithm-version m4-dedup-v1
```

Backfill and review mutations are transaction-scoped. A failed merge or split
rolls back completely. Rerunning one version recreates the same deterministic
cluster, link, and candidate identities. Clearing a version preserves source
rows, normalized values, and mappings produced by other versions.

## Limitations

Fuzzy matching is intentionally conservative. A pending candidate requires a
human decision, and rejected candidates remain auditable. This milestone does
not rank jobs, send notifications, change application state, or provide a UI.
