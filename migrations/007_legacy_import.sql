CREATE TABLE legacy_import_backups (
    id TEXT PRIMARY KEY,
    database_path TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    created_at TEXT NOT NULL,
    verified_at TEXT,
    UNIQUE (backup_path, sha256)
);

CREATE TABLE legacy_import_batches (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (
        source_type IN (
            'englishjobs_csv',
            'state_intelligence_csv',
            'sent_jobs_json',
            'master_cv_json',
            'legacy_artifact',
            'mysql_fixture'
        )
    ),
    source_name TEXT NOT NULL,
    source_path TEXT,
    source_checksum TEXT NOT NULL CHECK (length(source_checksum) = 64),
    importer_version TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('dry_run', 'apply')),
    status TEXT NOT NULL CHECK (
        status IN ('planned', 'completed', 'partial', 'failed', 'reused')
    ),
    backup_id TEXT REFERENCES legacy_import_backups(id),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    records_read INTEGER NOT NULL DEFAULT 0 CHECK (records_read >= 0),
    creates INTEGER NOT NULL DEFAULT 0 CHECK (creates >= 0),
    updates INTEGER NOT NULL DEFAULT 0 CHECK (updates >= 0),
    skips INTEGER NOT NULL DEFAULT 0 CHECK (skips >= 0),
    conflicts INTEGER NOT NULL DEFAULT 0 CHECK (conflicts >= 0),
    uncertain INTEGER NOT NULL DEFAULT 0 CHECK (uncertain >= 0),
    rejected INTEGER NOT NULL DEFAULT 0 CHECK (rejected >= 0),
    warnings_json TEXT NOT NULL DEFAULT '[]',
    reconciliation_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    CHECK ((mode = 'apply' AND backup_id IS NOT NULL) OR mode = 'dry_run')
);

CREATE UNIQUE INDEX uq_legacy_import_apply_identity
ON legacy_import_batches(source_type, source_name, source_checksum, importer_version)
WHERE mode = 'apply' AND status IN ('completed', 'reused');

CREATE TABLE legacy_import_sources (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES legacy_import_batches(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_path TEXT,
    logical_name TEXT NOT NULL,
    source_checksum TEXT NOT NULL CHECK (length(source_checksum) = 64),
    size_bytes INTEGER NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
    record_count INTEGER NOT NULL DEFAULT 0 CHECK (record_count >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE legacy_import_items (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES legacy_import_batches(id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    item_type TEXT NOT NULL CHECK (
        item_type IN ('job', 'description', 'notification', 'profile', 'artifact', 'mysql_row')
    ),
    action TEXT NOT NULL CHECK (
        action IN ('created', 'updated', 'skipped', 'linked', 'rejected', 'uncertain')
    ),
    original_source_identifier TEXT,
    source_checksum TEXT NOT NULL CHECK (length(source_checksum) = 64),
    content_checksum TEXT CHECK (content_checksum IS NULL OR length(content_checksum) = 64),
    mapping_confidence REAL NOT NULL DEFAULT 0 CHECK (
        mapping_confidence >= 0 AND mapping_confidence <= 1
    ),
    target_table TEXT,
    target_id TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (batch_id, item_key)
);

CREATE INDEX ix_legacy_import_items_target
ON legacy_import_items(target_table, target_id);

CREATE TABLE legacy_import_mappings (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES legacy_import_items(id) ON DELETE CASCADE,
    mapping_type TEXT NOT NULL,
    target_table TEXT NOT NULL,
    target_id TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    suppresses_notifications INTEGER NOT NULL DEFAULT 0 CHECK (suppresses_notifications IN (0, 1)),
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE legacy_notification_suppressions (
    id TEXT PRIMARY KEY,
    import_item_id TEXT NOT NULL REFERENCES legacy_import_items(id) ON DELETE CASCADE,
    duplicate_cluster_id TEXT NOT NULL,
    duplicate_algorithm_version TEXT NOT NULL,
    profile_id TEXT REFERENCES candidate_profiles(id),
    channel TEXT NOT NULL CHECK (channel IN ('telegram')),
    source_identifier TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX ix_legacy_notification_suppressions_cluster
ON legacy_notification_suppressions(
    duplicate_cluster_id, duplicate_algorithm_version, channel
);

CREATE UNIQUE INDEX uq_legacy_notification_suppression_identity
ON legacy_notification_suppressions(
    duplicate_cluster_id, duplicate_algorithm_version,
    COALESCE(profile_id, '*'), channel, source_identifier
);

CREATE TABLE legacy_artifacts (
    id TEXT PRIMARY KEY,
    import_item_id TEXT NOT NULL REFERENCES legacy_import_items(id) ON DELETE CASCADE,
    artifact_kind TEXT NOT NULL CHECK (
        artifact_kind IN ('flowcv_txt', 'evidence_report', 'ai_debug', 'analysis_report', 'cover_letter', 'other_txt')
    ),
    original_path TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    authoritative INTEGER NOT NULL DEFAULT 0 CHECK (authoritative IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (content_hash, stored_path)
);
