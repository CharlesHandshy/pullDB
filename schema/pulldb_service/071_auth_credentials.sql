-- 071_auth_credentials.sql
-- Password and 2FA storage for web authentication
-- Phase 4: Enhanced authentication

CREATE TABLE auth_credentials (
    user_id CHAR(36) PRIMARY KEY,
    password_hash VARCHAR(255) NULL,  -- bcrypt hash, NULL = no password set
    totp_secret VARCHAR(64) NULL,     -- Base32 encoded TOTP secret
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_credentials_user FOREIGN KEY (user_id) 
        REFERENCES auth_users(user_id) ON DELETE CASCADE
);
