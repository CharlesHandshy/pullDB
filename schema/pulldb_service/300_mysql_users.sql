-- 300_mysql_users.sql
-- MySQL user grants for pullDB services
--
-- Three users with least-privilege access:
--   - pulldb_api:    API/Web service (user management, job submission, admin UI)
--   - pulldb_worker: Worker service (job execution, status updates)
--   - pulldb_loader: myloader on TARGET hosts (restore permissions)
--
-- IMPORTANT: Run this script as a MySQL admin user (root or similar).
-- Replace 'CHANGE_ME' with strong passwords for each user.
--
-- Usage:
--   mysql -u root -p < 300_mysql_users.sql
--
-- Or with password substitution:
--   sed -e "s/CHANGE_ME_API/yourpassword1/" \
--       -e "s/CHANGE_ME_WORKER/yourpassword2/" \
--       300_mysql_users.sql | mysql -u root -p

-- =============================================================================
-- COORDINATION DATABASE USERS
-- =============================================================================
-- These users connect to the pulldb_service coordination database.

-- -----------------------------------------------------------------------------
-- pulldb_api: API/Web Service User
-- -----------------------------------------------------------------------------
-- Permissions: User management, job submission, admin UI operations
-- Used by: pulldb-api.service, pulldb-web.service

CREATE USER IF NOT EXISTS 'pulldb_api'@'localhost' IDENTIFIED BY 'CHANGE_ME_API';

-- auth_users: Create users, update roles/managers/status via admin UI
GRANT SELECT, INSERT, UPDATE ON pulldb_service.auth_users TO 'pulldb_api'@'localhost';

-- auth_credentials: Web login + password management (create, reset)
GRANT SELECT, INSERT, UPDATE ON pulldb_service.auth_credentials TO 'pulldb_api'@'localhost';

-- sessions: Full access for web session management
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.sessions TO 'pulldb_api'@'localhost';

-- user_hosts: Full access for admin user-host assignment management
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.user_hosts TO 'pulldb_api'@'localhost';

-- jobs: Submit jobs via enqueue_job()
GRANT SELECT, INSERT ON pulldb_service.jobs TO 'pulldb_api'@'localhost';

-- job_events: Read job history only
GRANT SELECT ON pulldb_service.job_events TO 'pulldb_api'@'localhost';

-- db_hosts: Full access for admin host management
GRANT SELECT, INSERT, UPDATE ON pulldb_service.db_hosts TO 'pulldb_api'@'localhost';

-- settings: Full access for admin settings management
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.settings TO 'pulldb_api'@'localhost';

-- active_jobs: Read-only view
GRANT SELECT ON pulldb_service.active_jobs TO 'pulldb_api'@'localhost';

-- audit_logs: Read + write for audit logging
GRANT SELECT, INSERT ON pulldb_service.audit_logs TO 'pulldb_api'@'localhost';

-- -----------------------------------------------------------------------------
-- pulldb_worker: Worker Service User
-- -----------------------------------------------------------------------------
-- Permissions: Update job status, manage events/locks/settings
-- Used by: pulldb-worker.service

CREATE USER IF NOT EXISTS 'pulldb_worker'@'localhost' IDENTIFIED BY 'CHANGE_ME_WORKER';

-- auth_users: Read only (user created by API)
GRANT SELECT ON pulldb_service.auth_users TO 'pulldb_worker'@'localhost';

-- jobs: Update status via mark_job_*()
GRANT SELECT, UPDATE ON pulldb_service.jobs TO 'pulldb_worker'@'localhost';

-- job_events: Append events
GRANT SELECT, INSERT ON pulldb_service.job_events TO 'pulldb_worker'@'localhost';

-- db_hosts: Read host config
GRANT SELECT ON pulldb_service.db_hosts TO 'pulldb_worker'@'localhost';

-- settings: Full access via CLI
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.settings TO 'pulldb_worker'@'localhost';

-- locks: Distributed locking
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.locks TO 'pulldb_worker'@'localhost';

-- active_jobs: Read-only view
GRANT SELECT ON pulldb_service.active_jobs TO 'pulldb_worker'@'localhost';

FLUSH PRIVILEGES;


-- =============================================================================
-- TARGET DATABASE USERS
-- =============================================================================
-- This user exists on TARGET database hosts (dev-db-01, etc.), NOT on the
-- coordination database. Used by myloader to restore backups.
--
-- Run this on EACH TARGET database host:

-- CREATE USER IF NOT EXISTS 'pulldb_loader'@'%' IDENTIFIED BY 'CHANGE_ME_LOADER';
--
-- GRANT CREATE, DROP, ALTER, INDEX, INSERT, UPDATE, DELETE, SELECT,
--       LOCK TABLES, TRIGGER, CREATE VIEW, CREATE ROUTINE, ALTER ROUTINE,
--       REFERENCES, EVENT
-- ON *.* TO 'pulldb_loader'@'%';
--
-- -- Optional: Restrict to specific database patterns
-- -- GRANT ... ON `______%`.* TO 'pulldb_loader'@'%';  -- user_code prefixed DBs
-- -- GRANT ... ON `qatemplate`.* TO 'pulldb_loader'@'%';
--
-- FLUSH PRIVILEGES;
