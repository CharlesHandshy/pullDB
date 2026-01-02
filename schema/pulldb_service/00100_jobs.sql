-- 00100_jobs.sql
-- Core table definition: jobs and associated indexes
-- v0.0.7: Added 'canceling' status for intermediate cancellation state

CREATE TABLE jobs (
    id CHAR(36) PRIMARY KEY,
    owner_user_id CHAR(36) NOT NULL,
    owner_username VARCHAR(255) NOT NULL,
    owner_user_code CHAR(6) NOT NULL,
    target VARCHAR(255) NOT NULL,
    staging_name VARCHAR(64) NOT NULL,
    dbhost VARCHAR(255) NOT NULL,
    status ENUM('queued','running','canceling','failed','complete','canceled','deleting','deleted') NOT NULL DEFAULT 'queued',
    submitted_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    options_json JSON,
    retry_count INT NOT NULL DEFAULT 0,
    error_detail TEXT,
    cancel_requested_at TIMESTAMP(6) NULL COMMENT 'Phase 1: User-requested cancellation timestamp',
    staging_cleaned_at TIMESTAMP(6) NULL COMMENT 'Phase 1: When staging database was cleaned up',
    worker_id VARCHAR(255) NULL COMMENT 'Phase 3: Worker that claimed this job (hostname:pid)',
    active_target_key VARCHAR(520) GENERATED ALWAYS AS (
        CASE WHEN status IN ('queued','running','canceling') THEN CONCAT(target,'@@',dbhost) ELSE NULL END
    ) VIRTUAL,
    CONSTRAINT fk_jobs_owner FOREIGN KEY (owner_user_id) REFERENCES auth_users(user_id)
);

CREATE UNIQUE INDEX idx_jobs_active_target ON jobs(active_target_key);
CREATE INDEX idx_jobs_queue ON jobs(status, submitted_at);
CREATE INDEX idx_jobs_owner_status ON jobs(owner_user_id, status);
CREATE INDEX idx_jobs_worker_id ON jobs(worker_id);
CREATE INDEX idx_jobs_staging_cleanup ON jobs(dbhost, status, staging_cleaned_at, completed_at);
