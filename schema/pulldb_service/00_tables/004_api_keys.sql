-- 004_api_keys.sql
-- API key storage for CLI/programmatic authentication
-- Consolidated from: 00715_api_keys.sql, 00716_api_keys_host_tracking.sql

CREATE TABLE api_keys (
    key_id VARCHAR(64) PRIMARY KEY,              -- Public key identifier (key_xxxxx...)
    user_id CHAR(36) NOT NULL,                   -- Owner of this API key
    key_secret_hash VARCHAR(255) NOT NULL,       -- bcrypt hash of the secret (for audit)
    key_secret VARCHAR(255) NOT NULL,            -- Plaintext secret (needed for HMAC verification)
    name VARCHAR(100) NULL,                      -- Optional friendly name for the key
    
    -- Host tracking (from 00716)
    host_name VARCHAR(255) NULL
        COMMENT 'Auto-detected hostname when key was requested',
    created_from_ip VARCHAR(45) NULL
        COMMENT 'IP address of the request-host-key call',
    
    -- Keys start inactive until approved (from 00716)
    is_active BOOLEAN NOT NULL DEFAULT FALSE,    -- Can be revoked without deletion
    
    -- Approval workflow (from 00716)
    approved_at TIMESTAMP(6) NULL
        COMMENT 'When admin approved the key (NULL = pending)',
    approved_by CHAR(36) NULL
        COMMENT 'Which admin approved the key',
    
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_used_at TIMESTAMP(6) NULL,              -- Track last usage for auditing
    last_used_ip VARCHAR(45) NULL
        COMMENT 'IP address of most recent authenticated request',
    expires_at TIMESTAMP(6) NULL,                -- Optional expiration
    
    CONSTRAINT fk_apikey_user FOREIGN KEY (user_id) 
        REFERENCES auth_users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_apikey_approved_by FOREIGN KEY (approved_by)
        REFERENCES auth_users(user_id) ON DELETE SET NULL,
    
    INDEX idx_apikey_user (user_id),
    INDEX idx_apikey_active (is_active, user_id),
    INDEX idx_apikey_pending (approved_at, created_at),
    INDEX idx_apikey_approval_status (is_active, approved_at)
);
