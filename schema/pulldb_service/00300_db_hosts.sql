-- 00300_db_hosts.sql
-- Core table definition: db_hosts
-- v0.0.6: Added host_alias for short hostname support

CREATE TABLE db_hosts (
    id CHAR(36) PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL UNIQUE,
    host_alias VARCHAR(64) NULL COMMENT 'Short alias for hostname (e.g., dev-db-01)',
    credential_ref VARCHAR(512) NOT NULL,
    max_concurrent_restores INT NOT NULL DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);

CREATE UNIQUE INDEX idx_db_hosts_alias ON db_hosts(host_alias);
