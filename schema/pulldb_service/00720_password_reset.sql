-- 00720_password_reset.sql
-- Add password reset flag to auth_credentials
-- Phase 4: Manager/Admin can mark user password for reset

ALTER TABLE auth_credentials 
ADD COLUMN password_reset_at TIMESTAMP(6) NULL 
COMMENT 'When set, user must reset password via CLI before next login';

-- Index for efficient lookup of users needing password reset
-- Note: MySQL doesn't support partial indexes, so we index the full column
CREATE INDEX idx_auth_credentials_reset ON auth_credentials(password_reset_at);
