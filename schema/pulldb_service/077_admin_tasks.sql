-- 077_admin_tasks.sql
-- Admin background tasks queue for long-running operations
-- Examples: force_delete_user (with database drops), scan_user_orphans

CREATE TABLE admin_tasks (
    task_id CHAR(36) PRIMARY KEY,
    
    -- Task type and status
    task_type ENUM('force_delete_user', 'scan_user_orphans') NOT NULL,
    status ENUM('pending', 'running', 'complete', 'failed') NOT NULL DEFAULT 'pending',
    
    -- Who requested the task
    requested_by CHAR(36) NOT NULL,
    
    -- Target user (for user-related tasks)
    target_user_id CHAR(36) NULL,
    
    -- Task parameters (JSON)
    -- For force_delete_user: {"databases_to_drop": [{"name": "db", "host": "host"}], "target_username": "..."}
    parameters_json JSON NULL,
    
    -- Task results (JSON)
    -- For force_delete_user: {"databases_dropped": [...], "databases_failed": [...], "jobs_deleted": N, "user_deleted": true}
    result_json JSON NULL,
    
    -- Timestamps
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    
    -- Error detail for failed tasks
    error_detail TEXT NULL,
    
    -- Worker tracking for orphan recovery
    worker_id VARCHAR(255) NULL COMMENT 'Worker that claimed this task (hostname:pid)',
    
    -- Indexes
    INDEX idx_admin_tasks_status_created (status, created_at),
    INDEX idx_admin_tasks_requested_by (requested_by),
    INDEX idx_admin_tasks_target_user (target_user_id),
    INDEX idx_admin_tasks_type_status (task_type, status)
);

-- Enforce max 1 concurrent force_delete_user task
-- MySQL doesn't support partial indexes, so we use a generated column workaround
ALTER TABLE admin_tasks ADD COLUMN running_task_type VARCHAR(50) GENERATED ALWAYS AS (
    CASE WHEN status = 'running' THEN task_type ELSE NULL END
) STORED;

CREATE UNIQUE INDEX idx_admin_tasks_single_running ON admin_tasks(running_task_type);

-- Note: No FK constraints to allow task preservation even if users are deleted
-- (the requested_by user might be deleted later)
