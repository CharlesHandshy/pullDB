-- 00730_manager_user_relationship.sql
-- Add manager_id to auth_users for hierarchical management
-- Managers can only manage users they created/are assigned to

ALTER TABLE auth_users 
ADD COLUMN manager_id CHAR(36) NULL
AFTER role;

ALTER TABLE auth_users
ADD CONSTRAINT fk_auth_users_manager 
FOREIGN KEY (manager_id) REFERENCES auth_users(user_id)
ON DELETE SET NULL;

-- Index for efficient manager->user lookups
CREATE INDEX idx_auth_users_manager ON auth_users(manager_id);

-- Note: When a manager creates a user, manager_id is set to the manager's user_id
-- When an admin creates a user, manager_id can be NULL (unmanaged) or set explicitly
