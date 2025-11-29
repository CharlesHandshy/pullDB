-- 070_auth_users_role.sql
-- Add role column to auth_users (additive, non-breaking)
-- Phase 4: RBAC support

ALTER TABLE auth_users 
ADD COLUMN role ENUM('user', 'manager', 'admin') NOT NULL DEFAULT 'user'
AFTER is_admin;

-- Backfill: admin users get 'admin' role
UPDATE auth_users SET role = 'admin' WHERE is_admin = TRUE;
