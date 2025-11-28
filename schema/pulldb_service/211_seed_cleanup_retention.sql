-- 211_seed_cleanup_retention.sql
-- Seed default staging cleanup retention days setting

INSERT INTO settings (setting_key, setting_value, description, updated_at)
VALUES (
    'staging_cleanup_retention_days',
    '7',
    'Number of days before abandoned staging databases are eligible for cleanup. Set to 0 to disable automatic cleanup.',
    UTC_TIMESTAMP(6)
)
ON DUPLICATE KEY UPDATE updated_at = UTC_TIMESTAMP(6);
