-- 00900_stale_delete_recovery.sql
-- Add index for efficient stale deleting job recovery
--
-- Jobs stuck in 'deleting' status can be reclaimed by workers after a timeout.
-- This index optimizes the claim_stale_deleting_job() query which looks for:
--   status = 'deleting' AND started_at < (now - timeout) AND retry_count < max
--
-- The query orders by started_at ASC to process oldest stale jobs first.

-- Index for finding stale deleting jobs for worker recovery
-- Covers the WHERE clause (status, retry_count) and ORDER BY (started_at)
CREATE INDEX idx_jobs_stale_deleting ON jobs(status, retry_count, started_at)
    COMMENT 'Find stale deleting jobs for worker recovery';
