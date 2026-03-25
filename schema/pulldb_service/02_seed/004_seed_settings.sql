-- 004_seed_settings.sql
-- Seed data for settings table
-- Consolidated from: 02100_seed_settings.sql, 00830_database_retention.sql

-- Core settings
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('default_dbhost', 'localhost', 'Default database host (local development)');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('s3_bucket_path', 'pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/', 'S3 backup bucket path');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('work_directory', '/opt/pulldb.service/work', 'Working directory for downloads and extractions');

-- Concurrency Controls (0 = unlimited)
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('max_active_jobs_per_user', '0', 'Maximum concurrent active jobs per user (0=unlimited)');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('max_active_jobs_global', '0', 'Maximum concurrent active jobs system-wide (0=unlimited)');

-- Staging Cleanup
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('staging_retention_days', '7', 'Days before abandoned staging databases are eligible for cleanup. 0=disabled.');

-- Job Log Retention
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('job_log_retention_days', '30', 'Days before job logs are eligible for pruning. 0=disabled.');

-- Database Retention Settings (from 00830, updated 2026-02-13)
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('max_retention_days', '180', 
     'Maximum retention period in days for restored databases')
ON DUPLICATE KEY UPDATE setting_key = setting_key;

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('expiring_warning_days', '7', 
     'Days before expiry to show database in Expiring Soon warning')
ON DUPLICATE KEY UPDATE setting_key = setting_key;

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('cleanup_grace_days', '7', 
     'Days after expiry before database is automatically cleaned up')
ON DUPLICATE KEY UPDATE setting_key = setting_key;
