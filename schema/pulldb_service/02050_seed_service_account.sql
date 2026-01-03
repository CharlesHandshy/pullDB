-- 02050_seed_service_account.sql
-- Service Bootstrap/CLI Admin Account (SBCACC)
--
-- This account allows systemd services and scheduled tasks (like pulldb-retention.timer)
-- to execute admin CLI commands. When pulldb-admin runs as the pulldb_service Linux user,
-- it looks up this account for authorization.
--
-- Key properties:
--   - Username matches Linux system user: pulldb_service
--   - Admin role for full CLI access
--   - No password (system account, not for interactive login)
--   - Cannot be disabled (required for system operations)
--
-- See also: packaging/debian/postinst (creates this during fresh install)

-- Only insert if not exists (idempotent)
-- Use fixed UUID for consistency: 00000000-0000-0000-0000-000000000001
INSERT IGNORE INTO auth_users (user_id, username, user_code, is_admin, role)
VALUES ('00000000-0000-0000-0000-000000000001', 'pulldb_service', 'SBCACC', TRUE, 'admin');

-- Service account has no password (cannot login via web UI)
-- The auth_credentials entry is optional but we create it for consistency
INSERT IGNORE INTO auth_credentials (user_id, password_hash)
SELECT '00000000-0000-0000-0000-000000000001', NULL
FROM DUAL
WHERE EXISTS (
    SELECT 1 FROM auth_users WHERE user_id = '00000000-0000-0000-0000-000000000001'
);
