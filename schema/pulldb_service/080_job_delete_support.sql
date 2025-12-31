-- 080_job_delete_support.sql
-- Add 'deleting' and 'deleted' statuses for user-initiated job database deletion
-- Add 'bulk_delete_jobs' admin task type for bulk operations

-- Add 'deleting' and 'deleted' to jobs.status ENUM
-- Note: In MySQL, we must redefine the entire ENUM to add new values
ALTER TABLE jobs MODIFY COLUMN status 
    ENUM('queued','running','failed','complete','canceled','deleting','deleted') 
    NOT NULL DEFAULT 'queued';

-- Add 'bulk_delete_jobs' to admin_tasks.task_type ENUM
ALTER TABLE admin_tasks MODIFY COLUMN task_type 
    ENUM('force_delete_user', 'scan_user_orphans', 'bulk_delete_jobs') 
    NOT NULL;

-- Index for finding deletable jobs (terminal status, not yet deleted)
-- Useful for the history view with delete actions
CREATE INDEX idx_jobs_deletable ON jobs(owner_user_id, status, completed_at)
    COMMENT 'Find deletable jobs for a user';
