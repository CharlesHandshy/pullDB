-- 003_sessions.sql
-- Session management for web authentication
-- Source: 00720_sessions.sql (unchanged)

CREATE TABLE sessions (
    session_id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    token_hash CHAR(64) NOT NULL,  -- SHA-256 of session token
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at TIMESTAMP(6) NOT NULL,
    last_activity TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ip_address VARCHAR(45) NULL,   -- IPv4 or IPv6
    user_agent VARCHAR(255) NULL,
    
    CONSTRAINT fk_session_user FOREIGN KEY (user_id) 
        REFERENCES auth_users(user_id) ON DELETE CASCADE,
    
    INDEX idx_sessions_user (user_id),
    INDEX idx_sessions_expires (expires_at),
    INDEX idx_sessions_token (token_hash)
);
