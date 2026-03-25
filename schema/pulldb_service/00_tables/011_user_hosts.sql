-- 011_user_hosts.sql
-- Junction table for user-to-database-host assignments
-- Source: 00750_user_hosts.sql (unchanged)

CREATE TABLE user_hosts (
    user_id CHAR(36) NOT NULL,
    host_id CHAR(36) NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    assigned_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    assigned_by CHAR(36) NULL COMMENT 'Admin user who made the assignment',
    
    PRIMARY KEY (user_id, host_id),
    
    CONSTRAINT fk_user_hosts_user 
        FOREIGN KEY (user_id) REFERENCES auth_users(user_id) ON DELETE CASCADE,
    
    CONSTRAINT fk_user_hosts_host 
        FOREIGN KEY (host_id) REFERENCES db_hosts(id) ON DELETE CASCADE,
    
    CONSTRAINT fk_user_hosts_assigned_by 
        FOREIGN KEY (assigned_by) REFERENCES auth_users(user_id) ON DELETE SET NULL
);

-- Index for default host lookups
CREATE INDEX idx_user_hosts_default ON user_hosts(user_id, is_default);

-- Index for looking up all users assigned to a host
CREATE INDEX idx_user_hosts_by_host ON user_hosts(host_id);
