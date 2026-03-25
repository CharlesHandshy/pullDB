-- 002_seed_admin_account.sql
-- Initial Administrator Account
-- Source: 02040_seed_admin_account.sql

-- Only insert if not exists (idempotent)
-- Use fixed UUID for consistency: 00000000-0000-0000-0000-000000000002
INSERT IGNORE INTO auth_users (user_id, username, user_code, role)
VALUES ('00000000-0000-0000-0000-000000000002', 'admin', 'adminn', 'admin');

-- Create credentials entry with NULL password (postinst will set the real hash)
INSERT IGNORE INTO auth_credentials (user_id, password_hash)
SELECT '00000000-0000-0000-0000-000000000002', NULL
FROM DUAL
WHERE EXISTS (
    SELECT 1 FROM auth_users WHERE user_id = '00000000-0000-0000-0000-000000000002'
);
