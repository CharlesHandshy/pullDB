-- 00850_deployed_status.sql
-- Add 'deployed' status to jobs system
-- 
-- This migration adds a 'deployed' status to distinguish between:
-- - deployed: Job finished, database is live, user actively working with it (Active view)
-- - complete: User marked done with database (History view)
--
-- Flow: running → deployed → complete (user action)

-- =============================================================================
-- Step 1: Add 'deployed' to jobs status ENUM
-- =============================================================================

ALTER TABLE jobs MODIFY COLUMN status 
    ENUM('queued','running','canceling','failed','complete','canceled','deleting','deleted','deployed') 
    NOT NULL DEFAULT 'queued';

-- =============================================================================
-- Step 2: Update active_jobs view to include deployed status
-- =============================================================================

DROP VIEW IF EXISTS active_jobs;
CREATE VIEW active_jobs AS
SELECT id, owner_user_id, owner_username, owner_user_code, target,
       staging_name, dbhost, status, submitted_at, started_at,
       worker_id
FROM jobs
WHERE status IN ('queued', 'running', 'canceling', 'deployed');

-- =============================================================================
-- Step 3: Backfill existing 'complete' jobs (with live DB) to 'deployed'
-- Jobs that are complete but NOT dropped and NOT superseded are still "active"
-- and should be marked as 'deployed'
-- =============================================================================

UPDATE jobs 
SET status = 'deployed' 
WHERE status = 'complete' 
  AND db_dropped_at IS NULL
  AND superseded_at IS NULL;
