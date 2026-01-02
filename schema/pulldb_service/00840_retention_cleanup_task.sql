-- 00840_retention_cleanup_task.sql
-- Add 'retention_cleanup' admin task type for scheduled database cleanup

-- Add 'retention_cleanup' to admin_tasks.task_type ENUM
ALTER TABLE admin_tasks MODIFY COLUMN task_type 
    ENUM('force_delete_user', 'scan_user_orphans', 'bulk_delete_jobs', 'retention_cleanup') 
    NOT NULL;
