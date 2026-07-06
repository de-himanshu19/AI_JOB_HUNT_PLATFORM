ALTER TABLE jobs ADD COLUMN normalization_version TEXT;
ALTER TABLE job_descriptions ADD COLUMN normalization_version TEXT;

CREATE TABLE duplicate_clusters (
    id TEXT PRIMARY KEY,
    representative_job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    algorithm_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (id, algorithm_version)
);

CREATE INDEX ix_duplicate_clusters_version
ON duplicate_clusters(algorithm_version, representative_job_id);

CREATE TABLE job_duplicate_links (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    cluster_id TEXT NOT NULL REFERENCES duplicate_clusters(id) ON DELETE CASCADE,
    algorithm_version TEXT NOT NULL,
    match_method TEXT NOT NULL CHECK (
        match_method IN (
            'singleton', 'exact_source_id', 'canonical_url',
            'strong_fingerprint', 'cross_source_similarity', 'manual'
        )
    ),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reasons_json TEXT NOT NULL DEFAULT '[]',
    reviewed INTEGER NOT NULL DEFAULT 0 CHECK (reviewed IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (job_id, algorithm_version),
    FOREIGN KEY (cluster_id, algorithm_version)
        REFERENCES duplicate_clusters(id, algorithm_version) ON DELETE CASCADE
);

CREATE INDEX ix_job_duplicate_links_cluster
ON job_duplicate_links(algorithm_version, cluster_id);

CREATE TABLE duplicate_candidates (
    id TEXT PRIMARY KEY,
    left_job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    right_job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    algorithm_version TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reasons_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'approved', 'rejected')
    ),
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    CHECK (left_job_id < right_job_id),
    UNIQUE (left_job_id, right_job_id, algorithm_version)
);

CREATE INDEX ix_duplicate_candidates_review
ON duplicate_candidates(algorithm_version, status, confidence DESC);
