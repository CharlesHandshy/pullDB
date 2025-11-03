-- pullDB MySQL Schema
-- Version: 0.0.1
-- MySQL: 8.0+
-- Generated from: docs/mysql-schema.md

-- Core Tables

CREATE TABLE auth_users (
    user_id CHAR(36) PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    user_code CHAR(6) NOT NULL UNIQUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    disabled_at TIMESTAMP(6) NULL,
    CONSTRAINT chk_user_code_length CHECK (CHAR_LENGTH(user_code) = 6)
);

CREATE TABLE jobs (
    id CHAR(36) PRIMARY KEY,
    owner_user_id CHAR(36) NOT NULL,
    owner_username VARCHAR(255) NOT NULL,
    owner_user_code CHAR(6) NOT NULL,
    target VARCHAR(255) NOT NULL,
    staging_name VARCHAR(64) NOT NULL,
    dbhost VARCHAR(255) NOT NULL,
    status ENUM('queued','running','failed','complete','canceled') NOT NULL DEFAULT 'queued',
    submitted_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    options_json JSON,
    retry_count INT NOT NULL DEFAULT 0,
    error_detail TEXT,
    active_target_key VARCHAR(520) GENERATED ALWAYS AS (
        CASE WHEN status IN ('queued','running') THEN CONCAT(target,'@@',dbhost) ELSE NULL END
    ) VIRTUAL,
    CONSTRAINT fk_jobs_owner FOREIGN KEY (owner_user_id) REFERENCES auth_users(user_id)
);

CREATE UNIQUE INDEX idx_jobs_active_target ON jobs(active_target_key);
CREATE INDEX idx_jobs_queue ON jobs(status, submitted_at);

CREATE TABLE job_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id CHAR(36) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    detail TEXT,
    logged_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_job_events_job FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_job_events_job_id ON job_events(job_id, logged_at);

CREATE TABLE db_hosts (
    id CHAR(36) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL UNIQUE,
    credential_ref VARCHAR(512) NOT NULL,
    max_concurrent_restores INT NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);

CREATE TABLE locks (
    lock_name VARCHAR(100) PRIMARY KEY,
    locked_by VARCHAR(255) NOT NULL,
    locked_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at TIMESTAMP(6) NOT NULL,
    INDEX idx_locks_expires (expires_at)
);

CREATE TABLE settings (
    setting_key VARCHAR(100) PRIMARY KEY,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
);

-- Supporting Views

CREATE VIEW active_jobs AS
SELECT id,
       owner_user_id,
       owner_username,
       owner_user_code,
       target,
       status,
       submitted_at,
       started_at
FROM jobs
WHERE status IN ('queued','running');

CREATE INDEX idx_jobs_owner_status ON jobs(owner_user_id, status);

-- Initial Data Population

-- Database Hosts (Legacy appType Support)
INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440000',
     'db-mysql-db3-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'aws-secretsmanager:/pulldb/mysql/db3-dev',
     1,
     TRUE);

INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440001',
     'db-mysql-db4-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'aws-secretsmanager:/pulldb/mysql/db4-dev',
     1,
     TRUE);

INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440002',
     'db-mysql-db5-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com',
     'aws-secretsmanager:/pulldb/mysql/db5-dev',
     1,
     TRUE);

-- Configuration Settings
INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('default_dbhost', 'db-mysql-db4-dev-vpc-us-east-1-aurora.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com', 'Default database host (SUPPORT)');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('s3_bucket_path', 'pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/', 'S3 backup bucket path');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('customers_after_sql_dir', '/opt/pulldb/customers_after_sql/', 'Customer post-restore SQL directory'),
    ('qa_template_after_sql_dir', '/opt/pulldb/qa_template_after_sql/', 'QA template post-restore SQL directory');

INSERT INTO settings (setting_key, setting_value, description) VALUES
    ('work_dir', '/var/lib/pulldb/work/', 'Working directory for downloads and extractions');
