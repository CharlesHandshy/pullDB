-- 00830_database_retention.sql
-- Database Retention & Cleanup System
-- v0.1.9: Adds expiration, locking, and lifecycle tracking for complete jobs
--
-- This migration adds:
-- 1. Expiration tracking for completed restore jobs
-- 2. Database locking to protect critical databases
-- 3. Lifecycle tracking (dropped, superseded states)
-- 4. User maintenance acknowledgment tracking
-- 5. Admin-configurable retention settings

-- =============================================================================
-- Jobs Table: Add retention and lifecycle columns
-- =============================================================================

ALTER TABLE jobs
    ADD COLUMN expires_at TIMESTAMP(6) NULL 
        COMMENT 'When database expires and becomes eligible for cleanup',
    ADD COLUMN locked_at TIMESTAMP(6) NULL 
        COMMENT 'When user locked this database (NULL = not locked)',
    ADD COLUMN locked_by VARCHAR(255) NULL 
        COMMENT 'Username who locked this database',
    ADD COLUMN db_dropped_at TIMESTAMP(6) NULL 
        COMMENT 'When the actual database was dropped from target host',
    ADD COLUMN superseded_at TIMESTAMP(6) NULL 
        COMMENT 'When a newer restore to same target replaced this job',
    ADD COLUMN superseded_by_job_id CHAR(36) NULL 
        COMMENT 'Job ID that superseded this one';

-- Index for cleanup queries: find expired, unlocked, not-dropped databases
CREATE INDEX idx_jobs_retention_cleanup 
    ON jobs(status, expires_at, locked_at, db_dropped_at, superseded_at);

-- Index for finding locked databases (manager report)
CREATE INDEX idx_jobs_locked 
    ON jobs(locked_at, owner_user_id);

-- =============================================================================
-- Auth Users Table: Add maintenance acknowledgment tracking  
-- =============================================================================

ALTER TABLE auth_users
    ADD COLUMN last_maintenance_ack DATE NULL
        COMMENT 'Last date user acknowledged maintenance modal';

-- =============================================================================
-- Retention Settings
-- =============================================================================

-- Default expiration for new restores; maximum extension allowed (months)
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('max_retention_months', '6', 
     'Default expiration for new restores and maximum extension allowed (1-12 months)')
ON DUPLICATE KEY UPDATE setting_key = setting_key;

-- Step size for retention dropdown options
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('max_retention_increment', '3', 
     'Step size for retention dropdown options (1, 2, 3, 4, or 5 months)')
ON DUPLICATE KEY UPDATE setting_key = setting_key;

-- Days before expiry to show warning in maintenance modal
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('expiring_notice_days', '7', 
     'Days before expiry to show database in Expiring Soon notice')
ON DUPLICATE KEY UPDATE setting_key = setting_key;

-- Days after expiry before automatic cleanup
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('cleanup_grace_days', '7', 
     'Days after expiry before database is automatically cleaned up')
ON DUPLICATE KEY UPDATE setting_key = setting_key;

-- =============================================================================
-- Backfill: Set expiration for existing complete jobs
-- Uses the max_retention_months setting (default 6 months from completion)
-- =============================================================================

UPDATE jobs 
SET expires_at = DATE_ADD(completed_at, INTERVAL 6 MONTH)
WHERE status = 'complete' 
  AND expires_at IS NULL 
  AND completed_at IS NOT NULL;
