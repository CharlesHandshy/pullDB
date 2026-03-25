-- 001_active_jobs_view.sql
-- View for active (queued, running, canceling, deployed) jobs
-- Consolidated from: 00600_active_jobs_view.sql, 00850_deployed_status.sql,
--   00856_active_jobs_can_cancel.sql

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
       started_at,
       worker_id,
       can_cancel
FROM jobs
WHERE status IN ('queued', 'running', 'canceling', 'deployed');
