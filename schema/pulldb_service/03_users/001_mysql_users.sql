-- 001_mysql_users.sql
-- MySQL user grants for pullDB services
-- Source: 03000_mysql_users.sql
--
-- Three users with least-privilege access:
--   - pulldb_api:    API/Web service (user management, job submission, admin UI)
--   - pulldb_worker: Worker service (job execution, status updates)
--   - pulldb_loader: myloader on TARGET hosts (restore permissions)
--
-- IMPORTANT: Run this script as a MySQL admin user (root or similar).
-- Replace 'CHANGE_ME' with strong passwords for each user.

-- =============================================================================
-- COORDINATION DATABASE USERS
-- =============================================================================

-- -----------------------------------------------------------------------------
-- pulldb_api: API/Web Service User
-- -----------------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'pulldb_api'@'localhost' IDENTIFIED BY 'CHANGE_ME_API';

GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.auth_users TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE ON pulldb_service.auth_credentials TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.sessions TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.user_hosts TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.jobs TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, DELETE ON pulldb_service.job_events TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.db_hosts TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.settings TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.active_jobs TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.audit_logs TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.admin_tasks TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.disallowed_users TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.api_keys TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.feature_requests TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.feature_request_votes TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, DELETE ON pulldb_service.feature_request_notes TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, DELETE ON pulldb_service.job_history_summary TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.overlord_tracking TO 'pulldb_api'@'localhost';

-- -----------------------------------------------------------------------------
-- pulldb_worker: Worker Service User
-- -----------------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'pulldb_worker'@'localhost' IDENTIFIED BY 'CHANGE_ME_WORKER';

GRANT SELECT, UPDATE, DELETE ON pulldb_service.auth_users TO 'pulldb_worker'@'localhost';
GRANT SELECT, UPDATE, DELETE ON pulldb_service.jobs TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT, DELETE ON pulldb_service.job_events TO 'pulldb_worker'@'localhost';
GRANT SELECT ON pulldb_service.db_hosts TO 'pulldb_worker'@'localhost';
GRANT LOCK TABLES ON pulldb_service.* TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.settings TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.locks TO 'pulldb_worker'@'localhost';
GRANT SELECT ON pulldb_service.active_jobs TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.admin_tasks TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.audit_logs TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.procedure_deployments TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT, DELETE ON pulldb_service.job_history_summary TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.overlord_tracking TO 'pulldb_worker'@'localhost';

FLUSH PRIVILEGES;

-- =============================================================================
-- TARGET DATABASE USERS (run on EACH target host)
-- =============================================================================
-- CREATE USER IF NOT EXISTS 'pulldb_loader'@'%' IDENTIFIED BY 'CHANGE_ME_LOADER';
-- GRANT CREATE, DROP, ALTER, INDEX, INSERT, UPDATE, DELETE, SELECT,
--       LOCK TABLES, TRIGGER, CREATE VIEW, CREATE ROUTINE, ALTER ROUTINE,
--       REFERENCES, EVENT, EXECUTE, PROCESS
--       ON *.* TO 'pulldb_loader'@'%';
-- FLUSH PRIVILEGES;
