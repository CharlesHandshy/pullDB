-- 00860_expired_status.sql
-- Add 'expired' status to jobs system
-- 
-- This migration adds an 'expired' status for jobs whose retention period has passed:
-- - deployed: Job finished, database is live, user actively working with it (Active view)
-- - expired: Retention period passed, pending cleanup (History view / cleanup window)
--
-- Flow: deployed → expired (automatic when expires_at passes)

-- =============================================================================
-- Step 1: Add 'expired' to jobs status ENUM
-- =============================================================================

ALTER TABLE jobs MODIFY COLUMN status 
    ENUM('queued','running','canceling','failed','complete','canceled','deleting','deleted','deployed','expired') 
    NOT NULL DEFAULT 'queued';
