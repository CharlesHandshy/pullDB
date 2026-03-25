-- 002_auth_credentials.sql
-- Password and 2FA storage for web authentication
-- Consolidated from: 00710_auth_credentials.sql, 00720_password_reset.sql

CREATE TABLE auth_credentials (
    user_id CHAR(36) PRIMARY KEY,
    password_hash VARCHAR(255) NULL,  -- bcrypt hash, NULL = no password set
    totp_secret VARCHAR(64) NULL,     -- Base32 encoded TOTP secret
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Password reset flag (from 00720)
    password_reset_at TIMESTAMP(6) NULL
        COMMENT 'When set, user must reset password via CLI before next login',
    
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    
    CONSTRAINT fk_credentials_user FOREIGN KEY (user_id) 
        REFERENCES auth_users(user_id) ON DELETE CASCADE
);

-- Index for efficient lookup of users needing password reset
CREATE INDEX idx_auth_credentials_reset ON auth_credentials(password_reset_at);
