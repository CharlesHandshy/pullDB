-- 00860_active_jobs_can_cancel.sql
-- Add can_cancel column to active_jobs view
-- 
-- This migration updates the active_jobs view to include the can_cancel column,
-- which indicates whether a job can still be canceled (before restore lock).

-- =============================================================================
-- Update active_jobs view to include can_cancel
-- =============================================================================

DROP VIEW IF EXISTS active_jobs;
CREATE VIEW active_jobs AS
SELECT id, owner_user_id, owner_username, owner_user_code, target,
       staging_name, dbhost, status, submitted_at, started_at,
       worker_id, can_cancel
FROM jobs
WHERE status IN ('queued', 'running', 'canceling', 'deployed');
