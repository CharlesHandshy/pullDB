-- Migration: Add locked_at field and SERVICE role for system accounts
-- 
-- This migration adds:
-- 1. locked_at column to auth_users for system-protected accounts
-- 2. SERVICE role value for system accounts like pulldb_service
--
-- Locked users cannot:
-- - Login via Web UI or API
-- - Have their password changed
-- - Be enabled/disabled/deleted
-- - Have their role/manager/hosts changed
--
-- Locked users CAN:
-- - Execute CLI admin commands (pulldb-admin) when running as the Linux user
-- - This allows systemd services/timers to run maintenance tasks
--
-- Can only be set/unset via direct SQL updates.

-- Add SERVICE to the role ENUM
ALTER TABLE auth_users
MODIFY COLUMN role ENUM('user', 'manager', 'admin', 'service') NOT NULL DEFAULT 'user';

-- Add locked_at column
ALTER TABLE auth_users
ADD COLUMN locked_at TIMESTAMP(6) NULL DEFAULT NULL
COMMENT 'When set, user cannot be modified or login. For system accounts.';

-- Update pulldb_service to SERVICE role and lock it (find by username)
-- Also ensure manager_id is NULL - service accounts don't have managers
UPDATE auth_users 
SET role = 'service', locked_at = NOW(6), manager_id = NULL 
WHERE username = 'pulldb_service';
