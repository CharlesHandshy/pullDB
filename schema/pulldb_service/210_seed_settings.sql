-- 210_seed_settings.sql
-- Seed data for settings table

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('default_dbhost', 'localhost', 'Default database host (local development)');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('s3_bucket_path', 'pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/', 'S3 backup bucket path');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('work_dir', '/var/lib/pulldb/work/', 'Working directory for downloads and extractions');

-- Phase 2: Concurrency Controls (0 = unlimited)
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('max_active_jobs_per_user', '0', 'Maximum concurrent active jobs per user (0=unlimited)');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('max_active_jobs_global', '0', 'Maximum concurrent active jobs system-wide (0=unlimited)');
