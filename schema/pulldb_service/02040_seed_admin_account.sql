-- 02040_seed_admin_account.sql
-- Initial Administrator Account
--
-- This creates the 'admin' user account for human administrators.
-- The password hash is set to NULL here - the postinst script will:
--   1. Generate a random 16-character password
--   2. Hash it with bcrypt
--   3. Update auth_credentials with the hash
--   4. Display/save the password for the administrator
--
-- This seed ensures the admin account structure exists even if postinst
-- password generation fails, allowing manual password reset later.
--
-- See also: packaging/debian/postinst (sets password during install)

-- Only insert if not exists (idempotent)
-- Use fixed UUID for consistency: 00000000-0000-0000-0000-000000000002
INSERT IGNORE INTO auth_users (user_id, username, user_code, is_admin, role)
VALUES ('00000000-0000-0000-0000-000000000002', 'admin', 'ADMINN', TRUE, 'admin');

-- Create credentials entry with NULL password (postinst will set the real hash)
-- NULL password means the account exists but cannot login until password is set
INSERT IGNORE INTO auth_credentials (user_id, password_hash)
SELECT '00000000-0000-0000-0000-000000000002', NULL
FROM DUAL
WHERE EXISTS (
    SELECT 1 FROM auth_users WHERE user_id = '00000000-0000-0000-0000-000000000002'
);
