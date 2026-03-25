-- 050_disallowed_users.sql
-- Blocked usernames table (structure only, seed data separate)
-- Source: 00810_disallowed_users.sql (structure portion)

CREATE TABLE disallowed_users (
    username VARCHAR(100) NOT NULL PRIMARY KEY,
    reason VARCHAR(500) NULL,
    is_hardcoded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    created_by CHAR(36) NULL,  -- User ID who added (NULL for hardcoded/seed)
    
    INDEX idx_disallowed_users_hardcoded (is_hardcoded),
    INDEX idx_disallowed_users_created (created_at)
);
