-- migrate:up
-- =============================================================================
-- Phase 2: Concurrency Controls
-- Adds settings for per-user and global active job limits
-- Value of 0 means unlimited (no cap)
-- Used by API to return HTTP 429 when limits exceeded
-- =============================================================================

INSERT IGNORE INTO settings (setting_key, setting_value, description)
VALUES 
    ('max_active_jobs_per_user', '0', 
     'Maximum concurrent active jobs per user. 0 = unlimited.'),
    
    ('max_active_jobs_global', '0', 
     'Maximum concurrent active jobs system-wide. 0 = unlimited.');


-- migrate:down
-- =============================================================================
-- Rollback: Remove Phase 2 concurrency settings
-- =============================================================================

DELETE FROM settings WHERE setting_key IN (
    'max_active_jobs_per_user',
    'max_active_jobs_global'
);
