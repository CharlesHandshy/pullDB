-- 00910_jobs_custom_target.sql
-- Add custom_target column to jobs table for tracking custom target usage
-- Part of Custom Target Database Name feature (2026-01-16)
--
-- This column tracks whether a job used a custom target name (user-specified)
-- versus an auto-generated name ({user_code}{customer}{suffix} pattern).
--
-- Used for:
-- - Cleanup logic differentiation (custom targets skip user_code-in-name check)
-- - Audit trail and job history queries
-- - Fast queries without parsing options_json

-- Add custom_target column to jobs table
ALTER TABLE jobs 
ADD COLUMN custom_target TINYINT(1) NOT NULL DEFAULT 0 
    COMMENT 'Whether custom target naming was used (1=custom, 0=auto-generated)'
    AFTER options_json;

-- Create index for efficient querying of custom target jobs
CREATE INDEX idx_jobs_custom_target ON jobs(custom_target, status);
