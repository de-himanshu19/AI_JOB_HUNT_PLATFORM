ALTER TABLE collection_runs ADD COLUMN jobs_inserted INTEGER NOT NULL DEFAULT 0 CHECK (jobs_inserted >= 0);
ALTER TABLE collection_runs ADD COLUMN jobs_updated INTEGER NOT NULL DEFAULT 0 CHECK (jobs_updated >= 0);
ALTER TABLE collection_runs ADD COLUMN queries_executed INTEGER NOT NULL DEFAULT 0 CHECK (queries_executed >= 0);
ALTER TABLE collection_runs ADD COLUMN pages_requested INTEGER NOT NULL DEFAULT 0 CHECK (pages_requested >= 0);
ALTER TABLE collection_runs ADD COLUMN search_requests_succeeded INTEGER NOT NULL DEFAULT 0 CHECK (search_requests_succeeded >= 0);
ALTER TABLE collection_runs ADD COLUMN search_requests_failed INTEGER NOT NULL DEFAULT 0 CHECK (search_requests_failed >= 0);
ALTER TABLE collection_runs ADD COLUMN detail_requests_succeeded INTEGER NOT NULL DEFAULT 0 CHECK (detail_requests_succeeded >= 0);
ALTER TABLE collection_runs ADD COLUMN detail_requests_failed INTEGER NOT NULL DEFAULT 0 CHECK (detail_requests_failed >= 0);

ALTER TABLE job_descriptions ADD COLUMN structured_data_json TEXT NOT NULL DEFAULT '{}';
