-- 010_db_hosts.sql
-- Database hosts configuration
-- Consolidated from: 00300_db_hosts.sql, 00760_job_limits.sql

CREATE TABLE db_hosts (
    id CHAR(36) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL UNIQUE,
    host_alias VARCHAR(64) NULL 
        COMMENT 'Short alias for hostname (e.g., dev-db-01)',
    credential_ref VARCHAR(512) NOT NULL,
    
    -- Job limits (renamed from max_concurrent_restores in 00760)
    max_running_jobs INT NOT NULL DEFAULT 1
        COMMENT 'Maximum concurrent running jobs on this host (worker enforcement)',
    max_active_jobs INT NOT NULL DEFAULT 10
        COMMENT 'Maximum active jobs (queued+running) on this host (API enforcement)',
    
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);

CREATE UNIQUE INDEX idx_db_hosts_alias ON db_hosts(host_alias);
