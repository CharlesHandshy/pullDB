-- 060_active_jobs_view.sql
-- Supporting view: active_jobs

CREATE VIEW active_jobs AS
SELECT id,
       owner_user_id,
       owner_username,
       owner_user_code,
       target,
       status,
       submitted_at,
       started_at
FROM jobs
WHERE status IN ('queued','running');
