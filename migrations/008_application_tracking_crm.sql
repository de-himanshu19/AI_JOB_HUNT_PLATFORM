DROP TRIGGER IF EXISTS application_events_immutable_update;
DROP TRIGGER IF EXISTS application_events_immutable_delete;

CREATE TEMP TABLE application_events_m7_backup AS
SELECT * FROM application_events;

ALTER TABLE applications RENAME TO applications_m7;

CREATE TABLE applications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    logical_cluster_id TEXT REFERENCES duplicate_clusters(id),
    status TEXT NOT NULL CHECK (
        status IN (
            'new', 'shortlisted', 'skipped', 'cv_ready', 'applied',
            'interview', 'offer', 'rejected', 'withdrawn'
        )
    ),
    current_status TEXT NOT NULL CHECK (
        current_status IN (
            'new', 'shortlisted', 'skipped', 'cv_ready', 'applied',
            'interview', 'offer', 'rejected', 'withdrawn'
        )
    ),
    priority TEXT CHECK (priority IS NULL OR priority IN ('high', 'medium', 'low')),
    notes TEXT NOT NULL DEFAULT '',
    follow_up_date TEXT,
    cv_artifact_id TEXT REFERENCES cv_generation_artifacts(id),
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (job_id, profile_id),
    CHECK (status = current_status),
    CHECK (follow_up_date IS NULL OR follow_up_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
);

INSERT INTO applications (
    id, job_id, profile_id, logical_cluster_id, status, current_status,
    priority, notes, follow_up_date, cv_artifact_id, source, created_at, updated_at
)
SELECT id, job_id, profile_id, NULL, status, status, NULL, '', NULL, NULL,
       'manual', created_at, updated_at
FROM applications_m7;

DROP TABLE applications_m7;

CREATE INDEX ix_applications_profile
ON applications(profile_id);

CREATE INDEX ix_applications_job
ON applications(job_id);

CREATE INDEX ix_applications_logical_cluster
ON applications(logical_cluster_id);

CREATE INDEX ix_applications_current_status
ON applications(current_status);

CREATE INDEX ix_applications_follow_up_date
ON applications(follow_up_date);

CREATE UNIQUE INDEX uq_applications_profile_cluster
ON applications(profile_id, logical_cluster_id)
WHERE logical_cluster_id IS NOT NULL;

DROP TABLE application_events;

CREATE TABLE application_events (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    from_status TEXT CHECK (
        from_status IS NULL OR
        from_status IN (
            'new', 'shortlisted', 'skipped', 'cv_ready', 'applied',
            'interview', 'offer', 'rejected', 'withdrawn'
        )
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN (
            'new', 'shortlisted', 'skipped', 'cv_ready', 'applied',
            'interview', 'offer', 'rejected', 'withdrawn'
        )
    ),
    event_type TEXT NOT NULL DEFAULT 'status_changed' CHECK (
        event_type IN (
            'created', 'status_changed', 'status_noop', 'note_added',
            'priority_changed', 'follow_up_changed', 'cv_attached'
        )
    ),
    reason TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);

INSERT INTO application_events (
    id, application_id, from_status, to_status, event_type, reason, note, created_at
)
SELECT id, application_id, from_status, to_status,
       CASE WHEN from_status IS NULL THEN 'created' ELSE 'status_changed' END,
       reason, reason, created_at
FROM application_events_m7_backup;

DROP TABLE application_events_m7_backup;

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
