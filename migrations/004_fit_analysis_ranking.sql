CREATE TABLE job_analyses_new (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    description_id TEXT REFERENCES job_descriptions(id),
    description_content_hash TEXT,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    profile_version INTEGER NOT NULL CHECK (profile_version >= 1),
    analyzer_version TEXT NOT NULL,
    rules_version TEXT NOT NULL DEFAULT 'legacy',
    ranking_version TEXT NOT NULL DEFAULT 'legacy',
    analysis_input_hash TEXT,
    description_completeness TEXT NOT NULL CHECK (
        description_completeness IN ('full', 'snippet', 'missing')
    ),
    authority TEXT NOT NULL DEFAULT 'prefilter_only' CHECK (
        authority IN ('authoritative', 'prefilter_only')
    ),
    completeness_warning TEXT,
    requirements_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    missing_skills_json TEXT NOT NULL DEFAULT '[]',
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    prefilter_score REAL CHECK (
        prefilter_score IS NULL OR (prefilter_score >= 0 AND prefilter_score <= 100)
    ),
    fit_score REAL CHECK (
        fit_score IS NULL OR (fit_score >= 0 AND fit_score <= 100)
    ),
    fit_reasons_json TEXT NOT NULL DEFAULT '[]',
    positive_components_json TEXT NOT NULL DEFAULT '[]',
    penalties_json TEXT NOT NULL DEFAULT '[]',
    score_caps_json TEXT NOT NULL DEFAULT '[]',
    language_risk_penalty REAL NOT NULL DEFAULT 0 CHECK (
        language_risk_penalty >= 0 AND language_risk_penalty <= 100
    ),
    banking_preference_bonus REAL NOT NULL DEFAULT 0 CHECK (
        banking_preference_bonus >= 0 AND banking_preference_bonus <= 100
    ),
    created_at TEXT NOT NULL
);

INSERT INTO job_analyses_new (
    id, job_id, profile_id, profile_version, analyzer_version, rules_version,
    ranking_version, description_completeness, authority, requirements_json, evidence_json,
    missing_skills_json, risk_flags_json, prefilter_score, fit_score,
    fit_reasons_json, language_risk_penalty, banking_preference_bonus, created_at
)
SELECT
    id, job_id, profile_id, profile_version, analyzer_version, 'legacy', 'legacy',
    description_completeness,
    CASE WHEN fit_score IS NULL THEN 'prefilter_only' ELSE 'authoritative' END,
    requirements_json, evidence_json, missing_skills_json, risk_flags_json,
    prefilter_score, fit_score, fit_reasons_json, language_risk_penalty,
    banking_preference_bonus, created_at
FROM job_analyses;

CREATE TABLE cv_artifacts_new (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    analysis_id TEXT REFERENCES job_analyses_new(id),
    profile_version INTEGER NOT NULL CHECK (profile_version >= 1),
    artifact_format TEXT NOT NULL CHECK (artifact_format IN ('flowcv_txt')),
    source TEXT NOT NULL CHECK (source IN ('rule_based', 'ai_polished')),
    path TEXT NOT NULL,
    validated INTEGER NOT NULL DEFAULT 0 CHECK (validated IN (0, 1)),
    validation_summary TEXT,
    created_at TEXT NOT NULL
);

INSERT INTO cv_artifacts_new
SELECT id, job_id, profile_id, analysis_id, profile_version, artifact_format,
       source, path, validated, validation_summary, created_at
FROM cv_artifacts;

DROP TABLE cv_artifacts;
DROP TABLE job_analyses;
ALTER TABLE job_analyses_new RENAME TO job_analyses;
ALTER TABLE cv_artifacts_new RENAME TO cv_artifacts;

CREATE UNIQUE INDEX uq_job_analyses_input_hash
ON job_analyses(analysis_input_hash)
WHERE analysis_input_hash IS NOT NULL;

CREATE INDEX ix_job_analyses_job_profile_created
ON job_analyses(job_id, profile_id, created_at DESC);

CREATE INDEX ix_cv_artifacts_job_profile_created
ON cv_artifacts(job_id, profile_id, created_at DESC);

CREATE TABLE job_rankings (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    cluster_id TEXT,
    analysis_id TEXT NOT NULL REFERENCES job_analyses(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    profile_version INTEGER NOT NULL CHECK (profile_version >= 1),
    ranking_version TEXT NOT NULL,
    ranking_input_hash TEXT NOT NULL UNIQUE,
    ranked_as_of TEXT NOT NULL,
    authority TEXT NOT NULL CHECK (authority IN ('authoritative', 'prefilter_only')),
    rank_score REAL NOT NULL,
    components_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX ix_job_rankings_profile_version_score
ON job_rankings(profile_id, ranking_version, rank_score DESC);
