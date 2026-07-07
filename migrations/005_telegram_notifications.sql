CREATE TABLE notification_batches (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    channel TEXT NOT NULL CHECK (channel IN ('telegram')),
    ranking_version TEXT NOT NULL,
    duplicate_algorithm_version TEXT NOT NULL,
    top_n INTEGER NOT NULL CHECK (top_n >= 1 AND top_n <= 20),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'sending', 'completed', 'partial', 'failed')
    ),
    selected_count INTEGER NOT NULL DEFAULT 0 CHECK (
        selected_count >= 0 AND selected_count <= 20
    ),
    chunks_total INTEGER NOT NULL DEFAULT 0 CHECK (chunks_total >= 0),
    chunks_sent INTEGER NOT NULL DEFAULT 0 CHECK (chunks_sent >= 0),
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE notification_deliveries (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES notification_batches(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 1),
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    remote_message_id TEXT,
    attempted_at TEXT NOT NULL,
    sent_at TEXT,
    error_summary TEXT,
    UNIQUE (batch_id, chunk_index, attempt_number)
);

CREATE UNIQUE INDEX uq_notification_delivery_success
ON notification_deliveries(batch_id, chunk_index)
WHERE status = 'sent';

CREATE TABLE notification_items (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES notification_batches(id) ON DELETE CASCADE,
    delivery_id TEXT NOT NULL REFERENCES notification_deliveries(id),
    duplicate_cluster_id TEXT NOT NULL,
    duplicate_algorithm_version TEXT NOT NULL,
    representative_job_id TEXT NOT NULL REFERENCES jobs(id),
    ranking_id TEXT NOT NULL REFERENCES job_rankings(id),
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    channel TEXT NOT NULL CHECK (channel IN ('telegram')),
    position INTEGER NOT NULL CHECK (position >= 1 AND position <= 20),
    idempotency_key TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    sent_at TEXT,
    error_summary TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (batch_id, position)
);

CREATE UNIQUE INDEX uq_notification_item_active
ON notification_items(
    duplicate_cluster_id, duplicate_algorithm_version, profile_id, channel
)
WHERE status IN ('pending', 'sent');

CREATE INDEX ix_notification_items_batch_delivery
ON notification_items(batch_id, delivery_id, position);

CREATE INDEX ix_notification_batches_profile_created
ON notification_batches(profile_id, created_at DESC);
