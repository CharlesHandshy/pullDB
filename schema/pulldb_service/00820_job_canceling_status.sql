-- 00820_job_canceling_status.sql
-- Add 'canceling' status for intermediate cancellation state
-- Jobs in 'canceling' state have cancellation requested but worker is still
-- cleaning up (myloader cannot be interrupted, only pre-restore stages can be)

-- Add 'canceling' to jobs.status ENUM
-- Note: In MySQL, we must redefine the entire ENUM to add new values
-- Order matters: inserted between 'running' and 'failed' for logical flow
ALTER TABLE jobs MODIFY COLUMN status 
    ENUM('queued','running','canceling','failed','complete','canceled','deleting','deleted') 
    NOT NULL DEFAULT 'queued';

-- Update active_jobs view to include 'canceling' status
-- Jobs being canceled are still "active" from an operational perspective
DROP VIEW IF EXISTS active_jobs;

CREATE VIEW active_jobs AS
SELECT id,
       owner_user_id,
       owner_username,
       owner_user_code,
       target,
       staging_name,
       dbhost,
       status,
       submitted_at,
       started_at
FROM jobs
WHERE status IN ('queued','running','canceling');

-- Update the virtual column for unique constraint enforcement
-- 'canceling' jobs should still block new jobs for same target
ALTER TABLE jobs DROP INDEX idx_jobs_active_target;

ALTER TABLE jobs DROP COLUMN active_target_key;

ALTER TABLE jobs ADD COLUMN active_target_key VARCHAR(520) GENERATED ALWAYS AS (
    CASE WHEN status IN ('queued','running','canceling') THEN CONCAT(target,'@@',dbhost) ELSE NULL END
) VIRTUAL;

CREATE UNIQUE INDEX idx_jobs_active_target ON jobs(active_target_key);
