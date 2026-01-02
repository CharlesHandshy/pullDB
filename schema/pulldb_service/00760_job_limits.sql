-- 00760_job_limits.sql
-- Add job limit columns for per-host and per-user capacity management
-- Implements dual-limit model: max_active_jobs (queued+running) and max_running_jobs (concurrent)

-- =============================================================================
-- Phase 1: Rename max_concurrent_restores to max_running_jobs in db_hosts
-- =============================================================================
-- max_running_jobs: Maximum concurrent restore operations (worker enforcement)
ALTER TABLE db_hosts 
    CHANGE COLUMN max_concurrent_restores max_running_jobs INT NOT NULL DEFAULT 1
    COMMENT 'Maximum concurrent running jobs on this host (worker enforcement)';

-- =============================================================================
-- Phase 2: Add max_active_jobs to db_hosts
-- =============================================================================
-- max_active_jobs: Maximum queued + running jobs (API enforcement)
ALTER TABLE db_hosts 
    ADD COLUMN max_active_jobs INT NOT NULL DEFAULT 10
    COMMENT 'Maximum active jobs (queued+running) on this host (API enforcement)'
    AFTER max_running_jobs;

-- =============================================================================
-- Phase 3: Add max_active_jobs to auth_users
-- =============================================================================
-- Per-user job limit (NULL = use system default from settings table, 0 = unlimited)
ALTER TABLE auth_users 
    ADD COLUMN max_active_jobs INT NULL
    COMMENT 'Per-user active job limit (NULL=system default, 0=unlimited)'
    AFTER disabled_at;
