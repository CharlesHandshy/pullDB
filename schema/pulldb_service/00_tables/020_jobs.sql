-- 020_jobs.sql
-- Core job queue table
-- Consolidated from: 00100_jobs.sql, 00800_job_delete_support.sql,
--   00820_job_canceling_status.sql, 00830_database_retention.sql,
--   00850_deployed_status.sql, 00855_can_cancel_column.sql,
--   00860_expired_status.sql, 00870_superseded_status.sql,
--   00900_stale_delete_recovery.sql, 00910_jobs_custom_target.sql,
--   012_add_origin_column.sql

CREATE TABLE jobs (
    id CHAR(36) PRIMARY KEY,
    owner_user_id CHAR(36) NOT NULL,
    owner_username VARCHAR(255) NOT NULL,
    owner_user_code CHAR(6) NOT NULL,
    target VARCHAR(255) NOT NULL,
    staging_name VARCHAR(64) NOT NULL,
    dbhost VARCHAR(255) NOT NULL,
    
    -- Full status ENUM with all statuses
    status ENUM(
        'queued',
        'running',
        'canceling',    -- from 00820
        'failed',
        'complete',
        'canceled',
        'deleting',     -- from 00800
        'deleted',      -- from 00800
        'deployed',     -- from 00850
        'expired',      -- from 00860
        'superseded'    -- from 00870
    ) NOT NULL DEFAULT 'queued',
    
    submitted_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    options_json JSON,
    
    -- Custom target tracking (from 00910)
    custom_target TINYINT(1) NOT NULL DEFAULT 0 
        COMMENT 'Whether custom target naming was used (1=custom, 0=auto-generated)',
    
    -- Database discovery origin tracking (from 012_add_origin_column)
    origin ENUM('restore', 'claim', 'assign') NOT NULL DEFAULT 'restore'
        COMMENT 'How this job was created: restore=normal pipeline, claim=claimed via discovery, assign=assigned via discovery',
    
    retry_count INT NOT NULL DEFAULT 0,
    error_detail TEXT,
    
    -- Cancel support (from 00855)
    can_cancel BOOLEAN NOT NULL DEFAULT TRUE
        COMMENT 'Whether job can still be canceled (false once loading begins)',
    cancel_requested_at TIMESTAMP(6) NULL 
        COMMENT 'User-requested cancellation timestamp',
    staging_cleaned_at TIMESTAMP(6) NULL 
        COMMENT 'When staging database was cleaned up',
    
    -- Worker tracking
    worker_id VARCHAR(255) NULL 
        COMMENT 'Worker that claimed this job (hostname:pid)',
    
    -- Database retention (from 00830)
    expires_at TIMESTAMP(6) NULL 
        COMMENT 'When database expires and becomes eligible for cleanup',
    locked_at TIMESTAMP(6) NULL 
        COMMENT 'When user locked this database (NULL = not locked)',
    locked_by VARCHAR(255) NULL 
        COMMENT 'Username who locked this database',
    db_dropped_at TIMESTAMP(6) NULL 
        COMMENT 'When the actual database was dropped from target host',
    superseded_at TIMESTAMP(6) NULL 
        COMMENT 'When a newer restore to same target replaced this job',
    superseded_by_job_id CHAR(36) NULL 
        COMMENT 'Job ID that superseded this one',
    
    -- Virtual column for unique constraint enforcement
    -- Includes canceling jobs which should still block new jobs for same target
    active_target_key VARCHAR(520) GENERATED ALWAYS AS (
        CASE WHEN status IN ('queued','running','canceling') THEN CONCAT(target,'@@',dbhost) ELSE NULL END
    ) VIRTUAL,
    
    CONSTRAINT fk_jobs_owner FOREIGN KEY (owner_user_id) REFERENCES auth_users(user_id)
);

-- Core indexes
CREATE UNIQUE INDEX idx_jobs_active_target ON jobs(active_target_key);
CREATE INDEX idx_jobs_queue ON jobs(status, submitted_at);
CREATE INDEX idx_jobs_owner_status ON jobs(owner_user_id, status);
CREATE INDEX idx_jobs_worker_id ON jobs(worker_id);
CREATE INDEX idx_jobs_staging_cleanup ON jobs(dbhost, status, staging_cleaned_at, completed_at);

-- Retention indexes (from 00830)
CREATE INDEX idx_jobs_retention_cleanup 
    ON jobs(status, expires_at, locked_at, db_dropped_at, superseded_at);
CREATE INDEX idx_jobs_locked 
    ON jobs(locked_at, owner_user_id);

-- Delete support index (from 00800)
CREATE INDEX idx_jobs_deletable ON jobs(owner_user_id, status, completed_at)
    COMMENT 'Find deletable jobs for a user';

-- Cancel support index (from 00855)
CREATE INDEX idx_jobs_can_cancel ON jobs(can_cancel);

-- Custom target index (from 00910)
CREATE INDEX idx_jobs_custom_target ON jobs(custom_target, status);

-- Stale delete recovery index (from 00900)
CREATE INDEX idx_jobs_stale_deleting ON jobs(status, retry_count, started_at)
    COMMENT 'Find stale deleting jobs for worker recovery';
