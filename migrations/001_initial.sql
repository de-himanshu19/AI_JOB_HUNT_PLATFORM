CREATE TABLE collection_runs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('arbeitsagentur', 'englishjobs', 'manual')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'partial', 'failed')),
    started_at TEXT,
    finished_at TEXT,
    jobs_found INTEGER NOT NULL DEFAULT 0 CHECK (jobs_found >= 0),
    jobs_stored INTEGER NOT NULL DEFAULT 0 CHECK (jobs_stored >= 0),
    error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    error_summary TEXT,
    config_snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('arbeitsagentur', 'englishjobs', 'manual')),
    source_job_id TEXT,
    source_url TEXT,
    canonical_url TEXT,
    title_raw TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    company_raw TEXT,
    company_normalized TEXT,
    location_raw TEXT,
    city TEXT,
    region TEXT,
    country TEXT,
    remote_mode TEXT,
    language_detected TEXT,
    language_confidence REAL CHECK (
        language_confidence IS NULL OR
        (language_confidence >= 0 AND language_confidence <= 1)
    ),
    explicit_german_requirement TEXT,
    published_at TEXT,
    expires_at TEXT,
    employment_type TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    first_seen_run_id TEXT REFERENCES collection_runs(id),
    last_seen_run_id TEXT REFERENCES collection_runs(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (source_job_id IS NULL OR length(trim(source_job_id)) > 0)
);

CREATE UNIQUE INDEX uq_jobs_source_source_job_id
ON jobs(source, source_job_id)
WHERE source_job_id IS NOT NULL;

CREATE INDEX ix_jobs_active_last_seen ON jobs(active, last_seen_at DESC);
CREATE INDEX ix_jobs_normalized_identity
ON jobs(company_normalized, title_normalized, city);

CREATE TABLE job_descriptions (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    raw_text TEXT,
    normalized_text TEXT,
    completeness TEXT NOT NULL CHECK (completeness IN ('full', 'snippet', 'missing')),
    content_hash TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (job_id, content_hash)
);

CREATE INDEX ix_job_descriptions_job_fetched
ON job_descriptions(job_id, fetched_at DESC);

CREATE TABLE candidate_profiles (
    id TEXT PRIMARY KEY,
    profile_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    display_name TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (profile_key, version),
    UNIQUE (profile_key, content_hash)
);

CREATE UNIQUE INDEX uq_candidate_profiles_one_active
ON candidate_profiles(profile_key)
WHERE active = 1;

CREATE TABLE applications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    status TEXT NOT NULL CHECK (
        status IN ('new', 'shortlisted', 'cv_ready', 'applied', 'skipped', 'rejected', 'interview')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (job_id, profile_id)
);

CREATE TABLE application_events (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    from_status TEXT CHECK (
        from_status IS NULL OR
        from_status IN ('new', 'shortlisted', 'cv_ready', 'applied', 'skipped', 'rejected', 'interview')
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN ('new', 'shortlisted', 'cv_ready', 'applied', 'skipped', 'rejected', 'interview')
    ),
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_application_events_application_created
ON application_events(application_id, created_at, id);

CREATE TRIGGER application_events_immutable_update
BEFORE UPDATE ON application_events
BEGIN
    SELECT RAISE(ABORT, 'application events are immutable');
END;

CREATE TRIGGER application_events_immutable_delete
BEFORE DELETE ON application_events
BEGIN
    SELECT RAISE(ABORT, 'application events are immutable');
END;

CREATE TABLE job_analyses (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    profile_version INTEGER NOT NULL CHECK (profile_version >= 1),
    analyzer_version TEXT NOT NULL,
    description_completeness TEXT NOT NULL CHECK (
        description_completeness IN ('full', 'snippet', 'missing')
    ),
    requirements_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    missing_skills_json TEXT NOT NULL DEFAULT '[]',
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    prefilter_score REAL CHECK (
        prefilter_score IS NULL OR (prefilter_score >= 0 AND prefilter_score <= 100)
    ),
    fit_score REAL CHECK (
        fit_score IS NULL OR (fit_score >= 0 AND fit_score <= 100)
    ),
    fit_reasons_json TEXT NOT NULL DEFAULT '[]',
    language_risk_penalty REAL NOT NULL DEFAULT 0 CHECK (
        language_risk_penalty >= 0 AND language_risk_penalty <= 100
    ),
    banking_preference_bonus REAL NOT NULL DEFAULT 0 CHECK (
        banking_preference_bonus >= 0 AND banking_preference_bonus <= 100
    ),
    created_at TEXT NOT NULL,
    UNIQUE (job_id, profile_id, profile_version, analyzer_version)
);

CREATE TABLE notifications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    channel TEXT NOT NULL CHECK (channel IN ('telegram')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    idempotency_key TEXT NOT NULL UNIQUE,
    remote_message_id TEXT,
    attempted_at TEXT NOT NULL,
    sent_at TEXT,
    error_summary TEXT
);

CREATE UNIQUE INDEX uq_notifications_success
ON notifications(job_id, profile_id, channel)
WHERE status = 'sent';

CREATE TABLE cv_artifacts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    analysis_id TEXT REFERENCES job_analyses(id),
    profile_version INTEGER NOT NULL CHECK (profile_version >= 1),
    artifact_format TEXT NOT NULL CHECK (artifact_format IN ('flowcv_txt')),
    source TEXT NOT NULL CHECK (source IN ('rule_based', 'ai_polished')),
    path TEXT NOT NULL,
    validated INTEGER NOT NULL DEFAULT 0 CHECK (validated IN (0, 1)),
    validation_summary TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_cv_artifacts_job_profile_created
ON cv_artifacts(job_id, profile_id, created_at DESC);

