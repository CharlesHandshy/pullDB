-- Add staging_cleaned_at column to track when staging DB was cleaned up
-- This prevents re-processing the same job in future cleanup runs

ALTER TABLE jobs
ADD COLUMN staging_cleaned_at TIMESTAMP(6) NULL
COMMENT 'When the staging database was cleaned up (NULL if not yet cleaned)';

-- Index for efficient cleanup queries
CREATE INDEX idx_jobs_staging_cleanup
ON jobs (dbhost, status, staging_cleaned_at, completed_at);
