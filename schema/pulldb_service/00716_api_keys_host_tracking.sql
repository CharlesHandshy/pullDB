-- 00716_api_keys_host_tracking.sql
-- Add host tracking and approval workflow to api_keys
-- Date: 2026-01-05
-- Purpose: Enable multi-host API key management with admin approval
--
-- Changes:
--   - Add host_name: Auto-detected hostname when key was requested
--   - Add created_from_ip: IP address of the request-host-key call
--   - Add last_used_ip: IP address of most recent authenticated request
--   - Add approved_at: When admin approved the key (NULL = pending)
--   - Add approved_by: Which admin approved the key
--   - Change is_active default to FALSE (keys start inactive until approved)
--
-- Note: Uses conditional logic for idempotent column additions

-- Add new columns using procedure for idempotent behavior
DROP PROCEDURE IF EXISTS add_api_key_columns;

DELIMITER //
CREATE PROCEDURE add_api_key_columns()
BEGIN
    -- Add host_name if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_schema = DATABASE() 
                   AND table_name = 'api_keys' 
                   AND column_name = 'host_name') THEN
        ALTER TABLE api_keys ADD COLUMN host_name VARCHAR(255) NULL AFTER name;
    END IF;
    
    -- Add created_from_ip if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_schema = DATABASE() 
                   AND table_name = 'api_keys' 
                   AND column_name = 'created_from_ip') THEN
        ALTER TABLE api_keys ADD COLUMN created_from_ip VARCHAR(45) NULL AFTER host_name;
    END IF;
    
    -- Add last_used_ip if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_schema = DATABASE() 
                   AND table_name = 'api_keys' 
                   AND column_name = 'last_used_ip') THEN
        ALTER TABLE api_keys ADD COLUMN last_used_ip VARCHAR(45) NULL AFTER last_used_at;
    END IF;
    
    -- Add approved_at if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_schema = DATABASE() 
                   AND table_name = 'api_keys' 
                   AND column_name = 'approved_at') THEN
        ALTER TABLE api_keys ADD COLUMN approved_at TIMESTAMP(6) NULL AFTER is_active;
    END IF;
    
    -- Add approved_by if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_schema = DATABASE() 
                   AND table_name = 'api_keys' 
                   AND column_name = 'approved_by') THEN
        ALTER TABLE api_keys ADD COLUMN approved_by CHAR(36) NULL AFTER approved_at;
    END IF;
    
    -- Add foreign key if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                   WHERE constraint_schema = DATABASE() 
                   AND table_name = 'api_keys' 
                   AND constraint_name = 'fk_apikey_approved_by') THEN
        ALTER TABLE api_keys ADD CONSTRAINT fk_apikey_approved_by 
            FOREIGN KEY (approved_by) REFERENCES auth_users(user_id) ON DELETE SET NULL;
    END IF;
    
    -- Add index idx_apikey_pending if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.statistics 
                   WHERE table_schema = DATABASE() 
                   AND table_name = 'api_keys' 
                   AND index_name = 'idx_apikey_pending') THEN
        CREATE INDEX idx_apikey_pending ON api_keys (approved_at, created_at);
    END IF;
    
    -- Add index idx_apikey_approval_status if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.statistics 
                   WHERE table_schema = DATABASE() 
                   AND table_name = 'api_keys' 
                   AND index_name = 'idx_apikey_approval_status') THEN
        CREATE INDEX idx_apikey_approval_status ON api_keys (is_active, approved_at);
    END IF;
END //
DELIMITER ;

-- Execute the procedure
CALL add_api_key_columns();

-- Clean up procedure
DROP PROCEDURE IF EXISTS add_api_key_columns;

-- Grandfather existing keys as approved (they were created before this approval system)
-- Set approved_at = created_at to indicate they were auto-approved
UPDATE api_keys 
SET approved_at = created_at,
    is_active = TRUE
WHERE approved_at IS NULL;

-- Change default for new keys: is_active defaults to FALSE
-- New keys will be inactive until approved by admin
ALTER TABLE api_keys ALTER COLUMN is_active SET DEFAULT FALSE;
