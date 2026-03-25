-- 040_admin_tasks.sql
-- Admin background tasks queue
-- Consolidated from: 00770_admin_tasks.sql, 00800_job_delete_support.sql,
--   00840_retention_cleanup_task.sql

CREATE TABLE admin_tasks (
    task_id CHAR(36) PRIMARY KEY,
    
    -- Task type with all values (consolidated ENUM)
    task_type ENUM(
        'force_delete_user', 
        'scan_user_orphans', 
        'bulk_delete_jobs',      -- from 00800
        'retention_cleanup'      -- from 00840
    ) NOT NULL,
    status ENUM('pending', 'running', 'complete', 'failed') NOT NULL DEFAULT 'pending',
    
    -- Who requested the task
    requested_by CHAR(36) NOT NULL,
    
    -- Target user (for user-related tasks)
    target_user_id CHAR(36) NULL,
    
    -- Task parameters (JSON)
    parameters_json JSON NULL,
    
    -- Task results (JSON)
    result_json JSON NULL,
    
    -- Timestamps
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    
    -- Error detail for failed tasks
    error_detail TEXT NULL,
    
    -- Worker tracking for orphan recovery
    worker_id VARCHAR(255) NULL COMMENT 'Worker that claimed this task (hostname:pid)',
    
    -- Generated column for single-running-task constraint
    running_task_type VARCHAR(50) GENERATED ALWAYS AS (
        CASE WHEN status = 'running' THEN task_type ELSE NULL END
    ) STORED,
    
    -- Indexes
    INDEX idx_admin_tasks_status_created (status, created_at),
    INDEX idx_admin_tasks_requested_by (requested_by),
    INDEX idx_admin_tasks_target_user (target_user_id),
    INDEX idx_admin_tasks_type_status (task_type, status)
);

-- Enforce max 1 concurrent task of same type (e.g., force_delete_user)
CREATE UNIQUE INDEX idx_admin_tasks_single_running ON admin_tasks(running_task_type);
