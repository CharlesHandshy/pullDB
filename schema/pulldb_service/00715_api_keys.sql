-- 00715_api_keys.sql
-- API key storage for CLI/programmatic authentication
-- Stores HMAC secrets per user for signed request authentication

CREATE TABLE api_keys (
    key_id VARCHAR(64) PRIMARY KEY,              -- Public key identifier (key_xxxxx...)
    user_id CHAR(36) NOT NULL,                   -- Owner of this API key
    key_secret_hash VARCHAR(255) NOT NULL,       -- bcrypt hash of the secret (for audit)
    key_secret VARCHAR(255) NOT NULL,            -- Plaintext secret (needed for HMAC verification)
    name VARCHAR(100) NULL,                      -- Optional friendly name for the key
    is_active BOOLEAN NOT NULL DEFAULT TRUE,     -- Can be revoked without deletion
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_used_at TIMESTAMP(6) NULL,              -- Track last usage for auditing
    expires_at TIMESTAMP(6) NULL,                -- Optional expiration
    CONSTRAINT fk_apikey_user FOREIGN KEY (user_id) 
        REFERENCES auth_users(user_id) ON DELETE CASCADE,
    INDEX idx_apikey_user (user_id),
    INDEX idx_apikey_active (is_active, user_id)
);

-- Each user can have multiple API keys (e.g., different machines)
-- but typically will have one primary key created at registration
-- Grant permissions to pulldb_api user (needed for registration to create keys)
-- NOTE: Run this manually if the grants don't exist:
-- GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.api_keys TO 'pulldb_api'@'localhost';
-- FLUSH PRIVILEGES;