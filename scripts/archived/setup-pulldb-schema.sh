#!/bin/bash
#
# ARCHIVED (Nov 2025): Superseded by applying schema/pulldb.sql directly.
# Retained for historical reference only. Do not use for new environments.
#
# pullDB Database Schema Setup Script
# Drops and recreates the pulldb coordination database with fresh schema
#
# PREREQUISITES:
#   1. MySQL 8.0+ installed and running
#   2. pulldb_app MySQL user created (see docs/mysql-setup.md)
#   3. AWS Secrets Manager secrets created (see docs/aws-secrets-manager-setup.md)
#
# WARNING: This script will DROP the existing pulldb database!
#   - All existing data will be permanently deleted
#   - All jobs, events, and audit history will be lost
#   - This is intended for development and testing only
#
# WHAT THIS SCRIPT DOES:
#   - Drops existing pulldb database (if it exists)
#   - Creates fresh pulldb database with utf8mb4 charset
#   - Creates 6 core tables: auth_users, jobs, job_events, db_hosts, locks, settings
#   - Creates active_jobs view
#   - Creates triggers for job status tracking
#   - Populates initial settings (S3 buckets, default host)
#   - Populates db_hosts with AWS Secrets Manager credential references
#
# WHAT THIS SCRIPT DOES NOT DO:
#   - Create pulldb_app MySQL user (manual step - see docs/mysql-setup.md)
#   - Create AWS Secrets Manager secrets (manual step - see docs/aws-secrets-manager-setup.md)
#   - Backup existing data (do this manually before running if needed)
#
# Usage: sudo ./setup-pulldb-schema.sh
#
# SOURCE: Generated from docs/mysql-schema.md
#

set -euo pipefail  # Exit on error, undefined variables, pipe failures

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

# Check if pulldb database exists
DB_EXISTS=$(mysql -sN -e "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = 'pulldb';")

if [ -n "$DB_EXISTS" ]; then
    print_warn "========================================"
    print_warn "WARNING: pulldb database already exists!"
    print_warn "========================================"
    print_warn ""
    print_warn "This script will DROP the existing database and all its data:"
    print_warn "  - All jobs and job history will be deleted"
    print_warn "  - All audit events will be lost"
    print_warn "  - All configuration settings will be reset"
    print_warn "  - All user accounts will be removed"
    print_warn ""
    print_warn "This action CANNOT be undone!"
    print_warn ""

    # Show table count to give context
    TABLE_COUNT=$(mysql -sN -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'pulldb';")
    print_warn "Current database has ${TABLE_COUNT} tables"

    echo -e "${RED}Do you want to continue and DROP the database? (type 'yes' to confirm): ${NC}"
    read -r CONFIRMATION

    if [ "$CONFIRMATION" != "yes" ]; then
        print_info "Setup canceled. Database was not modified."
        exit 0
    fi

    print_info "Dropping existing pulldb database..."
    mysql -e "DROP DATABASE pulldb;"
    print_info "✓ Database dropped successfully"
fi

# Create the pulldb database
print_info "Creating fresh pulldb database..."
mysql -e "CREATE DATABASE pulldb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
print_info "✓ Database created"

# Create schema SQL file from documentation
print_info "Creating schema..."
SCHEMA_SQL="${SCRIPT_DIR}/pulldb-schema.sql"

cat > "$SCHEMA_SQL" << 'EOF'
-- =============================================================================
-- pullDB Coordination Database Schema
-- Source: docs/mysql-schema.md
-- =============================================================================

USE pulldb;

SET FOREIGN_KEY_CHECKS = 1;

-- -----------------------------------------------------------------------------
-- Table: auth_users
-- Stores authenticated users with unique user_code for database naming
-- -----------------------------------------------------------------------------
CREATE TABLE auth_users (
    user_id CHAR(36) PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    user_code CHAR(6) NOT NULL UNIQUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    disabled_at TIMESTAMP(6) NULL,
    CONSTRAINT chk_user_code_length CHECK (CHAR_LENGTH(user_code) = 6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: jobs
-- Job queue with per-target exclusivity enforced via virtual column
-- Includes staging_name pattern for atomic staging-to-production renames
-- -----------------------------------------------------------------------------
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
    -- Virtual column for per-target exclusivity (MySQL 8.0 doesn't support partial indexes)
    active_target_key VARCHAR(255) AS (
        CASE WHEN status IN ('queued','running') THEN target ELSE NULL END
    ) VIRTUAL,
    CONSTRAINT fk_jobs_owner FOREIGN KEY (owner_user_id) REFERENCES auth_users(user_id),
    UNIQUE INDEX idx_active_target_unique (active_target_key),
    INDEX idx_jobs_status_submitted (status, submitted_at),
    INDEX idx_jobs_target (target),
    INDEX idx_jobs_owner (owner_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: job_events
-- Audit trail for job lifecycle transitions and troubleshooting
-- -----------------------------------------------------------------------------
CREATE TABLE job_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id CHAR(36) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    detail TEXT,
    logged_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_job_events_job FOREIGN KEY (job_id) REFERENCES jobs(id),
    INDEX idx_job_events_job_logged (job_id, logged_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: db_hosts
-- Target database servers with AWS Secrets Manager credential references
-- credential_ref format: aws-secretsmanager:/pulldb/mysql/{db-name}
-- -----------------------------------------------------------------------------
CREATE TABLE db_hosts (
    id CHAR(36) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL UNIQUE,
    credential_ref VARCHAR(512) NOT NULL,
    max_concurrent_restores INT NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_db_hosts_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: locks
-- Advisory locking for per-target exclusivity coordination
-- -----------------------------------------------------------------------------
CREATE TABLE locks (
    lock_name VARCHAR(255) PRIMARY KEY,
    locked_by_job_id CHAR(36) NOT NULL,
    locked_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_locks_job FOREIGN KEY (locked_by_job_id) REFERENCES jobs(id),
    INDEX idx_locks_job (locked_by_job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: settings
-- Configuration key-value pairs for runtime settings
-- -----------------------------------------------------------------------------
CREATE TABLE settings (
    setting_key VARCHAR(255) PRIMARY KEY,
    setting_value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================================================================
-- Views
-- =============================================================================

-- -----------------------------------------------------------------------------
-- View: active_jobs
-- Convenience view for queued and running jobs
-- -----------------------------------------------------------------------------
CREATE VIEW active_jobs AS
SELECT
    id,
    owner_user_id,
    owner_username,
    owner_user_code,
    target,
    staging_name,
    dbhost,
    status,
    submitted_at,
    started_at,
    options_json,
    retry_count
FROM jobs
WHERE status IN ('queued', 'running');

-- =============================================================================
-- Triggers
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Trigger: trg_jobs_status_change
-- Automatically log job status changes to job_events table
-- -----------------------------------------------------------------------------
DELIMITER //
CREATE TRIGGER trg_jobs_status_change
AFTER UPDATE ON jobs
FOR EACH ROW
BEGIN
    IF OLD.status != NEW.status THEN
        INSERT INTO job_events (job_id, event_type, detail)
        VALUES (
            NEW.id,
            CONCAT('status_changed_to_', NEW.status),
            CONCAT('Previous status: ', OLD.status)
        );
    END IF;
END//
DELIMITER ;

-- =============================================================================
-- Initial Data
-- =============================================================================

-- -----------------------------------------------------------------------------
-- db_hosts: Target database servers
-- NOTE: Update hostnames with actual RDS endpoints before production use
-- NOTE: Create secrets in AWS Secrets Manager first (see docs/aws-secrets-manager-setup.md)
-- -----------------------------------------------------------------------------
INSERT INTO db_hosts (id, hostname, credential_ref, max_concurrent_restores, enabled) VALUES
    ('550e8400-e29b-41d4-a716-446655440000',
        'db-mysql-db3-dev-vpc-us-east-1-aurora.cluster-xxxxx.us-east-1.rds.amazonaws.com',
        'aws-secretsmanager:/pulldb/mysql/db3-dev',
        1,
        TRUE
    ),
    ('550e8400-e29b-41d4-a716-446655440001',
        'db-mysql-db4-dev-vpc-us-east-1-aurora.cluster-xxxxx.us-east-1.rds.amazonaws.com',
        'aws-secretsmanager:/pulldb/mysql/db4-dev',
        1,
        TRUE
    ),
    ('550e8400-e29b-41d4-a716-446655440002',
        'db-mysql-db5-dev-vpc-us-east-1-aurora.cluster-xxxxx.us-east-1.rds.amazonaws.com',
        'aws-secretsmanager:/pulldb/mysql/db5-dev',
        1,
        TRUE
    );

-- -----------------------------------------------------------------------------
-- settings: Runtime configuration
-- NOTE: Update default_dbhost with actual default RDS endpoint
-- -----------------------------------------------------------------------------
INSERT INTO settings (setting_key, setting_value) VALUES
    ('default_dbhost', 'db-mysql-db4-dev-vpc-us-east-1-aurora.cluster-xxxxx.us-east-1.rds.amazonaws.com'),
    ('s3_bucket_prod', 'pestroutes-rds-backup-prod-vpc-us-east-1-s3'),
    ('s3_prefix_prod', 'daily/prod'),
    ('s3_bucket_stg', 'pestroutesrdsdbs'),
    ('s3_prefix_stg', 'daily/stg');

EOF

# Execute schema
print_info "Executing schema creation..."
if mysql < "$SCHEMA_SQL" 2>&1 | tee /tmp/pulldb-schema-output.log; then
    print_info "✓ Schema executed successfully"
else
    print_error "✗ Schema execution failed. Check /tmp/pulldb-schema-output.log for details"
    rm -f "$SCHEMA_SQL"
    exit 1
fi

# Verify schema
print_info "Verifying schema creation..."

# Check table count
TABLE_COUNT=$(mysql -sN -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'pulldb' AND table_type = 'BASE TABLE';")
if [ "$TABLE_COUNT" -eq 6 ]; then
    print_info "✓ All 6 tables created successfully"
else
    print_error "✗ Expected 6 tables, found ${TABLE_COUNT}"
    exit 1
fi

# Check view count
VIEW_COUNT=$(mysql -sN -e "SELECT COUNT(*) FROM information_schema.views WHERE table_schema = 'pulldb';")
if [ "$VIEW_COUNT" -eq 1 ]; then
    print_info "✓ active_jobs view created"
else
    print_error "✗ Expected 1 view, found ${VIEW_COUNT}"
    exit 1
fi

# Check trigger count
TRIGGER_COUNT=$(mysql -sN -e "SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema = 'pulldb';")
if [ "$TRIGGER_COUNT" -eq 1 ]; then
    print_info "✓ Status change trigger created"
else
    print_error "✗ Expected 1 trigger, found ${TRIGGER_COUNT}"
    exit 1
fi

# Check initial data
SETTINGS_COUNT=$(mysql -sN -e "SELECT COUNT(*) FROM pulldb.settings;")
print_info "✓ Settings populated (${SETTINGS_COUNT} rows)"

DB_HOSTS_COUNT=$(mysql -sN -e "SELECT COUNT(*) FROM pulldb.db_hosts;")
print_info "✓ db_hosts populated (${DB_HOSTS_COUNT} rows)"

# Cleanup temp SQL file
rm -f "$SCHEMA_SQL"

print_info ""
print_info "=========================================="
print_info "✓ pullDB Schema Setup Complete!"
print_info "=========================================="
print_info ""
print_info "Database: pulldb"
print_info "Tables: auth_users, jobs, job_events, db_hosts, locks, settings"
print_info "Views: active_jobs"
print_info "Triggers: trg_jobs_status_change"
print_info ""
print_warn "=========================================="
print_warn "REQUIRED: Update Configuration Values"
print_warn "=========================================="
print_warn ""
print_warn "1. Update db_hosts hostnames (replace 'xxxxx' with actual RDS cluster IDs):"
print_warn "   UPDATE pulldb.db_hosts SET hostname = 'actual-hostname.rds.amazonaws.com' WHERE id = 1;"
print_warn ""
print_warn "2. Update default_dbhost setting:"
print_warn "   UPDATE pulldb.settings SET setting_value = 'actual-hostname.rds.amazonaws.com' WHERE setting_key = 'default_dbhost';"
print_warn ""
print_warn "3. Verify AWS Secrets Manager secrets exist:"
print_warn "   aws secretsmanager describe-secret --secret-id /pulldb/mysql/db3-dev"
print_warn "   aws secretsmanager describe-secret --secret-id /pulldb/mysql/db4-dev"
print_warn "   aws secretsmanager describe-secret --secret-id /pulldb/mysql/db5-dev"
print_warn "   (See docs/aws-secrets-manager-setup.md for creation steps)"
print_warn ""
print_info "=========================================="
print_info "Next Steps"
print_info "=========================================="
print_info ""
print_info "1. Test database connection:"
print_info "   mysql -upulldb_app -p pulldb -e 'SHOW TABLES;'"
print_info ""
print_info "2. Implement CredentialResolver (Milestone 1.3):"
print_info "   See design/implementation-notes.md"
print_info ""
print_info "3. Begin Python development:"
print_info "   cd pulldb && python -m pytest tests/"
print_info ""
