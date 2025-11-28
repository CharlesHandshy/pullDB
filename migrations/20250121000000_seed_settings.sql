-- migrate:up
-- =============================================================================
-- Seed Data: Initial settings
-- Core configuration values with sensible defaults
-- These can be modified at runtime via the admin CLI
-- =============================================================================

INSERT IGNORE INTO settings (setting_key, setting_value, description)
VALUES 
    ('staging_database_prefix', 'tmp_pulldb_', 
     'Prefix for temporary staging databases during restore'),
    
    ('myloader_default_threads', '4', 
     'Default number of parallel threads for myloader'),
    
    ('job_timeout_seconds', '3600', 
     'Maximum time a job can run before being marked as stale'),
    
    ('cleanup_retention_days', '7', 
     'Number of days to retain completed job records');


-- migrate:down
-- =============================================================================
-- Rollback: Remove initial settings
-- Note: Removes only the original seed values, not user-modified values
-- =============================================================================

DELETE FROM settings WHERE setting_key IN (
    'staging_database_prefix',
    'myloader_default_threads',
    'job_timeout_seconds',
    'cleanup_retention_days'
);
