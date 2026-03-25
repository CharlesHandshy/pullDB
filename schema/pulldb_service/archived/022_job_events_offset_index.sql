-- 022_job_events_offset_index.sql
-- Add index for efficient offset-based pagination (virtual scroll)
-- Query pattern: SELECT ... WHERE job_id = ? ORDER BY id DESC LIMIT ? OFFSET ?

CREATE INDEX idx_job_events_job_id_desc ON job_events(job_id, id DESC);
