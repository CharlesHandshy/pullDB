-- 001_auth_users.sql
-- Core table: auth_users
-- Consolidated from: 00000_auth_users.sql, 00700_auth_users_role.sql, 
--   00730_manager_user_relationship.sql, 00760_job_limits.sql,
--   00830_database_retention.sql, 00890_user_locked_service_role.sql

CREATE TABLE auth_users (
    user_id CHAR(36) PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    user_code CHAR(6) NOT NULL UNIQUE,
    
    -- RBAC role controlling access levels
    role ENUM('user', 'manager', 'admin', 'service') NOT NULL DEFAULT 'user',
    
    -- Manager relationship (from 00730)
    manager_id CHAR(36) NULL,
    
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    disabled_at TIMESTAMP(6) NULL,
    
    -- Per-user job limit (from 00760) - NULL=system default, 0=unlimited
    max_active_jobs INT NULL
        COMMENT 'Per-user active job limit (NULL=system default, 0=unlimited)',
    
    -- Maintenance acknowledgment (from 00830)
    last_maintenance_ack DATE NULL
        COMMENT 'Last date user acknowledged maintenance modal',
    
    -- System account lock (from 00890) - locked users cannot be modified via UI
    locked_at TIMESTAMP(6) NULL DEFAULT NULL
        COMMENT 'When set, user cannot be modified or login. For system accounts.',
    
    CONSTRAINT chk_user_code_length CHECK (CHAR_LENGTH(user_code) = 6),
    
    CONSTRAINT fk_auth_users_manager 
        FOREIGN KEY (manager_id) REFERENCES auth_users(user_id)
        ON DELETE SET NULL
);

-- Index for efficient manager->user lookups
CREATE INDEX idx_auth_users_manager ON auth_users(manager_id);
