-- 017_jobs_worker_id.sql
-- Add worker_id column for distributed worker tracking

-- worker_id: Optional identifier of the worker that claimed the job.
-- Format: "hostname:pid" or similar unique identifier.
-- Used for debugging and monitoring in multi-daemon deployments.
-- NULL for jobs not yet claimed or legacy data.

ALTER TABLE jobs
ADD COLUMN worker_id VARCHAR(255) NULL
AFTER error_detail;

-- Index for querying jobs by worker (useful for debugging/monitoring)
CREATE INDEX idx_jobs_worker_id ON jobs(worker_id);
