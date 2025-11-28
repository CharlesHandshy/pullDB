-- migrate:up
-- =============================================================================
-- Initial pullDB Schema
-- Creates core tables required for the coordination database
-- This is the baseline schema - all future changes go in separate migrations
-- =============================================================================

-- -----------------------------------------------------------------------------
-- auth_users: Users who can submit restore requests
-- These are populated by the administrator, not self-service registration
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auth_users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    api_key CHAR(64) NOT NULL UNIQUE,  -- SHA-256 hex output
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- jobs: Restore job queue - the heart of pullDB
-- One row per restore request, tracks lifecycle from queued to complete
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    s3_uri VARCHAR(1024) NOT NULL,
    target_db VARCHAR(128) NOT NULL,
    status ENUM('queued','running','success','failed','cancelled') DEFAULT 'queued',
    myloader_threads TINYINT UNSIGNED DEFAULT 4,
    run_post_sql BOOLEAN DEFAULT TRUE,
    post_sql_exit_code INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP NULL,
    finished_at TIMESTAMP NULL,
    error_message TEXT,
    FOREIGN KEY (user_id) REFERENCES auth_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Index for worker polling: find oldest queued job efficiently
CREATE INDEX idx_jobs_status_created ON jobs(status, created_at);

-- Index for status queries: filter by user efficiently
CREATE INDEX idx_jobs_user_status ON jobs(user_id, status);

-- -----------------------------------------------------------------------------
-- job_events: Append-only event log for job lifecycle
-- Provides complete audit trail and debugging information
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id BIGINT NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Index for retrieving events by job
CREATE INDEX idx_job_events_job ON job_events(job_id);

-- -----------------------------------------------------------------------------
-- db_hosts: Registry of target database hosts
-- Used for host validation and connection management
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS db_hosts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    host VARCHAR(255) NOT NULL UNIQUE,
    description VARCHAR(500),
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- locks: Advisory locking for cross-service coordination
-- Used to prevent concurrent restores to same target database
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS locks (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    lock_name VARCHAR(255) NOT NULL UNIQUE,
    owner VARCHAR(255) NOT NULL,
    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NULL,
    INDEX idx_locks_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- settings: Key-value configuration store
-- Runtime tunable settings without code deployment
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    setting_key VARCHAR(100) NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    description VARCHAR(500),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- active_jobs: Convenience view for monitoring
-- Shows currently running jobs with user and duration info
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW active_jobs AS
SELECT 
    j.id,
    u.name as user_name,
    j.s3_uri,
    j.target_db,
    j.status,
    j.started_at,
    TIMESTAMPDIFF(SECOND, j.started_at, NOW()) as running_seconds
FROM jobs j
JOIN auth_users u ON j.user_id = u.id
WHERE j.status = 'running';


-- migrate:down
-- =============================================================================
-- Rollback: Remove all tables in reverse dependency order
-- WARNING: This will delete ALL data!
-- =============================================================================

DROP VIEW IF EXISTS active_jobs;
DROP TABLE IF EXISTS settings;
DROP TABLE IF EXISTS locks;
DROP TABLE IF EXISTS db_hosts;
DROP TABLE IF EXISTS job_events;
DROP TABLE IF EXISTS jobs;
DROP TABLE IF EXISTS auth_users;
