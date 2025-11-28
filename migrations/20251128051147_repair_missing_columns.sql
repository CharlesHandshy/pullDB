-- migrate:up
-- =============================================================================
-- REPAIR MIGRATION: Add missing columns from baselined migrations
-- 
-- Context: Migrations 20250115 and 20250116 were baselined (marked as applied)
-- on an existing database that was set up before the migration system existed.
-- However, the columns they define don't exist in production because:
-- 1. The original migration had a bug (AFTER finished_at instead of completed_at)
-- 2. The database was set up manually before migrations existed
--
-- This migration safely adds the missing columns if they don't exist.
-- =============================================================================

-- Add cancel_requested_at if missing
SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.columns 
    WHERE table_schema = DATABASE() 
    AND table_name = 'jobs' 
    AND column_name = 'cancel_requested_at'
);

SET @sql = IF(@col_exists = 0,
    'ALTER TABLE jobs ADD COLUMN cancel_requested_at TIMESTAMP(6) NULL DEFAULT NULL AFTER error_detail',
    'SELECT "cancel_requested_at already exists" AS status'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add staging_cleaned_at if missing
SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.columns 
    WHERE table_schema = DATABASE() 
    AND table_name = 'jobs' 
    AND column_name = 'staging_cleaned_at'
);

SET @sql = IF(@col_exists = 0,
    'ALTER TABLE jobs ADD COLUMN staging_cleaned_at TIMESTAMP(6) NULL DEFAULT NULL AFTER cancel_requested_at',
    'SELECT "staging_cleaned_at already exists" AS status'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add staging cleanup index if missing
SET @idx_exists = (
    SELECT COUNT(*) FROM information_schema.statistics 
    WHERE table_schema = DATABASE() 
    AND table_name = 'jobs' 
    AND index_name = 'idx_jobs_staging_cleanup'
);

SET @sql = IF(@idx_exists = 0,
    'CREATE INDEX idx_jobs_staging_cleanup ON jobs(dbhost, status, staging_cleaned_at, completed_at)',
    'SELECT "idx_jobs_staging_cleanup already exists" AS status'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;


-- migrate:down
-- =============================================================================
-- Rollback: Remove columns added by this repair migration
-- Note: Only safe to run if these columns were added by this migration
-- =============================================================================

DROP INDEX IF EXISTS idx_jobs_staging_cleanup ON jobs;
ALTER TABLE jobs DROP COLUMN IF EXISTS staging_cleaned_at;
ALTER TABLE jobs DROP COLUMN IF EXISTS cancel_requested_at;
