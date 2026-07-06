# Fit Analysis and Ranking

Milestone 5 provides deterministic, offline job analysis against a versioned
candidate profile. It makes no external requests and does not mutate application
status, send notifications, or generate CVs.

## Candidate profile

Import a JSON profile with:

- `personal_info` and versioned identity metadata;
- `work_experience`, `projects`, `education`, courses, and certifications;
- `skills_and_tools`, languages with proficiency, domains, and verified metrics;
- preferences for target role families, locations, mobility, and domains;
- optional evidence-strength labels (`direct`, `transferable`, `supporting`).

Legacy `skills_bank`, `training_and_courses`, and separate `certifications`
sections remain accepted. Candidate facts are read only from the imported profile.

```powershell
python -m app.cli profile import profile.json --profile-key candidate
python -m app.cli profile list
python -m app.cli profile show <profile-id>
```

## Analysis authority

Only `full` descriptions receive an authoritative fit score. `snippet` and
`missing` descriptions receive a clearly labelled `prefilter_only` result, a
completeness warning, and no `fit_score`.

Evidence precedence is:

1. direct professional experience;
2. professional transferable experience;
3. project evidence;
4. education, training, or certification evidence;
5. no evidence.

Generic tool exposure never proves ownership. Course knowledge is not
professional experience. Unsupported requirements remain in `missing_skills`.

## Scoring

The versioned defaults are stored in `config/fit_rules.json`.

```text
evidence_score = 100 * sum(requirement_weight * evidence_factor)
                       / sum(requirement_weight)

raw_fit = evidence_score
        + target_role_bonus
        - required_missing_penalty
        - visible risk penalties

fit_score = clamp(raw_fit, 0, 100), then apply every visible score cap
```

Required requirements have weight 10 and optional requirements weight 3.
Evidence factors are direct 1.0, transferable 0.65, project 0.75,
education/training 0.5, and missing 0.0. Default caps are German mismatch 70,
S/4HANA ownership gap 65, seniority gap 60, and direct finance/controlling gap
75. Optional missing requirements remain visible but do not receive the required
missing penalty. No risk rule is a silent hard exclusion.

## Ranking

Ranking operates on Milestone 4 cluster representatives, not source rows.
Authoritative ranking is the fit score plus visible freshness, preferred-location,
and preferred-domain components. Prefilter-only rows are excluded unless
`--include-prefilter-only` is explicitly supplied.

Tie order is exact and stable:

1. rank score descending;
2. authoritative fit score descending (`None` last);
3. published timestamp descending (`None` last);
4. first-seen timestamp descending;
5. normalized title ascending;
6. normalized company ascending;
7. cluster ID, or job ID fallback, ascending.

```powershell
python -m app.cli analyze --profile-id <profile-id>
python -m app.cli analysis show <analysis-id>
python -m app.cli rank --profile-id <profile-id> --as-of 2026-07-06T12:00:00+00:00
```

## Cache identity

Analysis identity hashes job ID, description content hash/completeness, candidate
profile content hash/version, analyzer version, rules version, and ranking
version. Ranking identity hashes analysis ID, duplicate cluster ID, ranking/rules
versions, explicit `as_of`, and all ranking components. Cache hits return the
same immutable row; changed inputs create new rows and preserve prior results.

## Limitations

Rule dictionaries are intentionally small and need calibration against reviewed
vacancies. No statistical or AI model is used. Full-description availability
still depends on the source adapters, and prefilter-only results are not evidence
of candidate fit.
