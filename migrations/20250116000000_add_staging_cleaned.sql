-- migrate:up
-- =============================================================================
-- Phase 1: Add staging_cleaned_at column
-- Tracks when staging database cleanup was performed after restore
-- Enables verification that cleanup ran and supports audit requirements
-- =============================================================================

ALTER TABLE jobs 
ADD COLUMN staging_cleaned_at TIMESTAMP(6) NULL DEFAULT NULL 
AFTER cancel_requested_at;

-- Index for cleanup monitoring queries (matches schema file)
CREATE INDEX idx_jobs_staging_cleanup ON jobs(dbhost, status, staging_cleaned_at, completed_at);


-- migrate:down
-- =============================================================================
-- Rollback: Remove staging_cleaned_at column and index
-- =============================================================================

DROP INDEX idx_jobs_staging_cleanup ON jobs;
ALTER TABLE jobs DROP COLUMN staging_cleaned_at;
