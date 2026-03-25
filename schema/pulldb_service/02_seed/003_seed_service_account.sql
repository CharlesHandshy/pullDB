-- 003_seed_service_account.sql
-- Service Bootstrap/CLI Admin Account (sbcacc)
-- Source: 02050_seed_service_account.sql

-- Only insert if not exists (idempotent)
-- Use fixed UUID for consistency: 00000000-0000-0000-0000-000000000001
INSERT IGNORE INTO auth_users (user_id, username, user_code, role, locked_at)
VALUES ('00000000-0000-0000-0000-000000000001', 'pulldb_service', 'sbcacc', 'service', NOW(6));

-- Service account has no password (cannot login via web UI)
INSERT IGNORE INTO auth_credentials (user_id, password_hash)
SELECT '00000000-0000-0000-0000-000000000001', NULL
FROM DUAL
WHERE EXISTS (
    SELECT 1 FROM auth_users WHERE user_id = '00000000-0000-0000-0000-000000000001'
);
