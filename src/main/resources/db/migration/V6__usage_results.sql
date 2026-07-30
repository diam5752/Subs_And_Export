CREATE TABLE IF NOT EXISTS usage_results (
    ledger_id VARCHAR(32) PRIMARY KEY
        REFERENCES usage_ledger (id) ON DELETE CASCADE,
    job_id VARCHAR(128) NOT NULL
        REFERENCES jobs (id) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_usage_results_job_id
    ON usage_results (job_id);
