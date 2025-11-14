-- 210_seed_settings.sql
-- Seed data for settings table

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('default_dbhost', 'localhost', 'Default database host (local development)');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('s3_bucket_path', 'pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/', 'S3 backup bucket path');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('customers_after_sql_dir', '/opt/pulldb/customers_after_sql/', 'Customer post-restore SQL directory'),
    ('qa_template_after_sql_dir', '/opt/pulldb/qa_template_after_sql/', 'QA template post-restore SQL directory');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('work_dir', '/var/lib/pulldb/work/', 'Working directory for downloads and extractions');
