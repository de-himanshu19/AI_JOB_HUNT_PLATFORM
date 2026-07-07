CREATE TABLE cv_generation_artifacts (
    id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES jobs(id),
    logical_cluster_id TEXT,
    description_id TEXT REFERENCES job_descriptions(id),
    description_content_hash TEXT NOT NULL,
    description_completeness TEXT NOT NULL CHECK (description_completeness = 'full'),
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    profile_version INTEGER NOT NULL CHECK (profile_version >= 1),
    profile_content_hash TEXT NOT NULL,
    analysis_id TEXT REFERENCES job_analyses(id),
    analyzer_version TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    formatter_version TEXT NOT NULL,
    generation_mode TEXT NOT NULL CHECK (generation_mode IN ('stored_job', 'manual_jd')),
    generation_identity TEXT NOT NULL,
    artifact_format TEXT NOT NULL CHECK (artifact_format = 'flowcv_txt'),
    source TEXT NOT NULL CHECK (source IN ('rule_based', 'ai_polished')),
    parent_rule_based_artifact_id TEXT REFERENCES cv_generation_artifacts(id),
    artifact_path TEXT NOT NULL,
    evidence_report_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    evidence_report_hash TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    prompt_version TEXT,
    ai_generated_at TEXT,
    validated INTEGER NOT NULL CHECK (validated IN (0, 1)),
    validation_result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        (generation_mode = 'stored_job' AND job_id IS NOT NULL AND
         description_id IS NOT NULL AND analysis_id IS NOT NULL) OR
        (generation_mode = 'manual_jd' AND job_id IS NULL AND
         description_id IS NULL AND analysis_id IS NULL)
    ),
    CHECK (
        (source = 'rule_based' AND parent_rule_based_artifact_id IS NULL AND
         provider IS NULL AND model IS NULL AND prompt_version IS NULL AND
         ai_generated_at IS NULL) OR
        (source = 'ai_polished' AND parent_rule_based_artifact_id IS NOT NULL AND
         provider IS NOT NULL AND model IS NOT NULL AND prompt_version IS NOT NULL AND
         ai_generated_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX uq_cv_generation_rule_identity
ON cv_generation_artifacts(generation_identity)
WHERE source = 'rule_based';

CREATE INDEX ix_cv_generation_job_profile_created
ON cv_generation_artifacts(job_id, profile_id, created_at DESC);

CREATE INDEX ix_cv_generation_parent
ON cv_generation_artifacts(parent_rule_based_artifact_id, created_at);

CREATE TABLE cv_ai_attempts (
    id TEXT PRIMARY KEY,
    parent_rule_based_artifact_id TEXT NOT NULL REFERENCES cv_generation_artifacts(id),
    derivative_artifact_id TEXT REFERENCES cv_generation_artifacts(id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    failure_category TEXT,
    evidence_report_path TEXT NOT NULL,
    validation_result_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    CHECK (
        (status = 'succeeded' AND derivative_artifact_id IS NOT NULL AND failure_category IS NULL) OR
        (status = 'failed' AND derivative_artifact_id IS NULL AND failure_category IS NOT NULL)
    )
);

CREATE INDEX ix_cv_ai_attempts_parent_created
ON cv_ai_attempts(parent_rule_based_artifact_id, generated_at DESC);
