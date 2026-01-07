-- Add can_cancel column to jobs table
-- This flag is TRUE by default and flips to FALSE atomically when restore begins.
-- Once FALSE, the cancel button is hidden and cancel requests are rejected.
-- This provides a deterministic, race-free cancel control mechanism.

ALTER TABLE jobs ADD COLUMN can_cancel BOOLEAN NOT NULL DEFAULT TRUE
    COMMENT 'Whether job can still be canceled (false once loading begins)';

-- Add index for efficient filtering of cancelable jobs
CREATE INDEX idx_jobs_can_cancel ON jobs(can_cancel);
