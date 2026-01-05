-- Migration 003: Add host tracking and approval workflow to api_keys
-- Date: 2026-01-05
-- Purpose: Enable multi-host API key management with admin approval
--
-- Changes:
--   - Add host_name: Auto-detected hostname when key was requested
--   - Add created_from_ip: IP address of the request-host-key call
--   - Add last_used_ip: IP address of most recent authenticated request
--   - Add approved_at: When admin approved the key (NULL = pending)
--   - Add approved_by: Which admin approved the key
--   - Change is_active default to FALSE (keys start inactive)
--
-- Rollback: See bottom of file

-- Add new columns
ALTER TABLE api_keys 
    ADD COLUMN host_name VARCHAR(255) NULL AFTER name,
    ADD COLUMN created_from_ip VARCHAR(45) NULL AFTER host_name,
    ADD COLUMN last_used_ip VARCHAR(45) NULL AFTER last_used_at,
    ADD COLUMN approved_at TIMESTAMP(6) NULL AFTER is_active,
    ADD COLUMN approved_by CHAR(36) NULL AFTER approved_at;

-- Add foreign key for approved_by (references admin user)
ALTER TABLE api_keys
    ADD CONSTRAINT fk_apikey_approved_by 
    FOREIGN KEY (approved_by) REFERENCES auth_users(user_id) ON DELETE SET NULL;

-- Index for finding pending approval keys efficiently
CREATE INDEX idx_apikey_pending ON api_keys (approved_at, created_at);

-- Index for finding keys by approval status
CREATE INDEX idx_apikey_approval_status ON api_keys (is_active, approved_at);

-- Grandfather existing keys as approved (they were created before this system)
-- Set approved_at = created_at to indicate they were auto-approved
UPDATE api_keys 
SET approved_at = created_at,
    is_active = TRUE
WHERE approved_at IS NULL;

-- Change default for new keys: is_active defaults to FALSE
-- New keys will be inactive until approved
ALTER TABLE api_keys 
    ALTER COLUMN is_active SET DEFAULT FALSE;

-- ============================================================================
-- ROLLBACK (run manually if needed):
-- ============================================================================
-- ALTER TABLE api_keys ALTER COLUMN is_active SET DEFAULT TRUE;
-- ALTER TABLE api_keys DROP FOREIGN KEY fk_apikey_approved_by;
-- DROP INDEX idx_apikey_approval_status ON api_keys;
-- DROP INDEX idx_apikey_pending ON api_keys;
-- ALTER TABLE api_keys 
--     DROP COLUMN approved_by,
--     DROP COLUMN approved_at,
--     DROP COLUMN last_used_ip,
--     DROP COLUMN created_from_ip,
--     DROP COLUMN host_name;
