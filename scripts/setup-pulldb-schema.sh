#!/bin/bash
#
# pullDB Database Schema Setup Script
# Creates the pulldb coordination database and initializes all tables
#
# Usage: sudo ./setup-pulldb-schema.sh
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    print_error "Please run as root (use sudo)"
    exit 1
fi

print_info "Setting up pullDB coordination database schema"

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Check if MySQL is running
if ! systemctl is-active --quiet mysql; then
    print_error "MySQL service is not running. Please start MySQL first."
    exit 1
fi

# Create the pulldb database
print_info "Creating pulldb database..."
mysql -e "CREATE DATABASE IF NOT EXISTS pulldb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Create schema SQL file from documentation
print_info "Extracting schema from documentation..."
SCHEMA_SQL="${SCRIPT_DIR}/pulldb-schema.sql"

cat > "$SCHEMA_SQL" << 'EOF'
-- pullDB Coordination Database Schema
-- Generated from docs/mysql-schema.md

USE pulldb;

-- Enable foreign key constraints
SET FOREIGN_KEY_CHECKS = 1;

-- auth_users table
CREATE TABLE IF NOT EXISTS auth_users (
    user_id CHAR(36) PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    user_code CHAR(6) NOT NULL UNIQUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    disabled_at TIMESTAMP(6) NULL,
    CONSTRAINT chk_user_code_length CHECK (CHAR_LENGTH(user_code) = 6)
);

-- jobs table
CREATE TABLE IF NOT EXISTS jobs (
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
    CONSTRAINT fk_jobs_owner FOREIGN KEY (owner_user_id) REFERENCES auth_users(user_id)
);

-- Index for active jobs per target exclusivity
-- MySQL does not support partial indexes with WHERE; emulate by using a generated column
-- that is NULL unless status is in ('queued','running'), then enforce uniqueness where not null.
ALTER TABLE jobs 
    ADD COLUMN active_target_key VARCHAR(520) GENERATED ALWAYS AS (
        CASE WHEN status IN ('queued','running') THEN CONCAT(target,'@@',dbhost) ELSE NULL END
    ) VIRTUAL;
CREATE UNIQUE INDEX idx_jobs_active_target ON jobs(active_target_key);

-- Index for job queue polling
CREATE INDEX idx_jobs_queue 
ON jobs(status, submitted_at);

-- job_events table
CREATE TABLE IF NOT EXISTS job_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id CHAR(36) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    detail TEXT,
    logged_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_job_events_job FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- Index for job event lookup
CREATE INDEX idx_job_events_job_id ON job_events(job_id, logged_at);

-- db_hosts table
CREATE TABLE IF NOT EXISTS db_hosts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL UNIQUE,
    connection_string VARCHAR(512) NOT NULL,
    max_concurrent_restores INT NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);

-- settings table
CREATE TABLE IF NOT EXISTS settings (
    setting_key VARCHAR(100) PRIMARY KEY,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
);

-- locks table (for distributed locking)
CREATE TABLE IF NOT EXISTS locks (
    lock_name VARCHAR(100) PRIMARY KEY,
    locked_by VARCHAR(255) NOT NULL,
    locked_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at TIMESTAMP(6) NOT NULL,
    INDEX idx_locks_expires (expires_at)
);

-- Trigger: Auto-log job status changes
DELIMITER //
CREATE TRIGGER trg_jobs_status_change 
AFTER UPDATE ON jobs
FOR EACH ROW
BEGIN
    IF OLD.status != NEW.status THEN
        INSERT INTO job_events (job_id, event_type, detail)
        VALUES (NEW.id, CONCAT('status_changed_to_', NEW.status), 
                CONCAT('Previous status: ', OLD.status));
    END IF;
END//
DELIMITER ;

-- Initial data: db_hosts
INSERT INTO db_hosts (hostname, connection_string, max_concurrent_restores, enabled) 
VALUES 
    ('db-mysql-db3-dev', 'mysql://db-mysql-db3-dev.pestroutes.com:3306', 1, TRUE),
    ('db-mysql-db4-dev', 'mysql://db-mysql-db4-dev.pestroutes.com:3306', 1, TRUE),
    ('db-mysql-db5-dev', 'mysql://db-mysql-db5-dev.pestroutes.com:3306', 1, TRUE)
ON DUPLICATE KEY UPDATE 
    connection_string = VALUES(connection_string),
    max_concurrent_restores = VALUES(max_concurrent_restores);

-- Initial data: settings
INSERT INTO settings (setting_key, setting_value, description)
VALUES
    ('default_dbhost', 'db-mysql-db4-dev', 'Default database host for SUPPORT team restores'),
    ('s3_bucket_path', 'pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod', 'S3 path to production backups'),
    ('work_dir', '/mnt/data/pulldb/work', 'Temporary working directory for downloads and extraction'),
    ('customers_after_sql_dir', '/opt/pulldb/customers_after_sql', 'Directory containing post-restore SQL scripts for customer databases'),
    ('qa_template_after_sql_dir', '/opt/pulldb/qa_template_after_sql', 'Directory containing post-restore SQL scripts for QA templates')
ON DUPLICATE KEY UPDATE
    setting_value = VALUES(setting_value),
    description = VALUES(description);
EOF

# Execute schema
print_info "Creating tables and loading initial data..."
mysql < "$SCHEMA_SQL"

# Verify schema
print_info "Verifying schema..."
TABLE_COUNT=$(mysql -sN -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'pulldb';")

if [ "$TABLE_COUNT" -ge 6 ]; then
    print_info "✓ Schema created successfully ($TABLE_COUNT tables)"
else
    print_error "✗ Schema creation may have failed (found $TABLE_COUNT tables, expected 6+)"
    exit 1
fi

# Show created tables
print_info "Tables in pulldb database:"
mysql -e "USE pulldb; SHOW TABLES;"

# Show initial settings
print_info "Initial settings:"
mysql -e "USE pulldb; SELECT * FROM settings;"

# Show db_hosts
print_info "Database hosts:"
mysql -e "USE pulldb; SELECT hostname, enabled FROM db_hosts;"

# Cleanup temp SQL file
rm -f "$SCHEMA_SQL"

print_info ""
print_info "=========================================="
print_info "pullDB schema setup complete!"
print_info "=========================================="
print_info ""
print_info "Database: pulldb"
print_info "Tables: auth_users, jobs, job_events, db_hosts, settings, locks"
print_info ""
print_info "Next steps:"
print_info "1. Configure environment variables for database connection"
print_info "2. Begin Python implementation (Milestone 1.1)"
print_info ""
