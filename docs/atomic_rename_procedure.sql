-- Atomic rename stored procedure for pullDB
-- Version: 1.0.0
--
-- IMPORTANT: Procedure version MUST match expected version in deployment
-- tooling and worker compatibility checks. Bump this version ONLY when
-- procedure logic changes in a way that requires redeployment across all
-- hosts. Versioning allows:
--   * Worker-side compatibility validation
--   * Controlled rollout (verify version before restore)
--   * Benchmark correlations (performance evolution across versions)
--
-- Preview companion procedure (pulldb_atomic_rename_preview) is provided
-- to safely inspect the RENAME TABLE statement without executing it.
-- Deployment script may optionally deploy both procedures; preview can be
-- used for benchmarking and diagnostics.
--
-- Name: pulldb_atomic_rename
-- Purpose: Atomically cut over restored staging database to target database
--          after successful myloader + post-SQL + metadata injection.
--
-- Contract:
--   IN p_staging_db VARCHAR(64)
--   IN p_target_db  VARCHAR(64)
--
-- Behavior:
--   1. Validate staging database exists.
--   2. If target exists, DROP it (zero-downtime expectation: clients connect only after restore completes).
--   3. Rename all tables from staging schema to target schema using RENAME TABLE ... syntax.
--   4. Verify target schema now contains at least one table.
--   5. Leave staging schema intact if ANY error occurs (caller will FAIL HARD; manual inspection allowed).
--
-- Transactional Notes:
--   MySQL does not support transactional CREATE/DROP DATABASE operations.
--   RENAME TABLE across databases is atomic per statement when renaming multiple tables.
--   We build a single RENAME statement covering all tables to ensure atomicity.
--
-- Error Handling:
--   Any SQL error causes procedure to SIGNAL with descriptive message.
--   Caller (pullDB worker) catches error and raises AtomicRenameError, preserving staging DB.
--
-- Idempotence:
--   Not idempotent: running twice after success will drop newly restored target.
--   Caller guarantees single invocation.
--
-- Security Requirements:
--   EXECUTE privilege on procedure.
--   DROP privilege on target schema.
--   ALTER privilege (implicit for RENAME TABLE) on staging + target schemas.
--
-- Verification:
--   SHOW PROCEDURE STATUS LIKE 'pulldb_atomic_rename';
--   SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_NAME='pulldb_atomic_rename';
--
-- Future Enhancements:
--   - Versioned procedure (include version comment and runtime check)
--   - Dry-run mode returning proposed RENAME statement without executing
--   - Graceful connection quiescing (KILL QUERY on target before drop)
--
-- NOTE: Deploy this procedure individually on each target MySQL host used by pullDB.
--       Test in non-production hosts before production promotion.
DELIMITER $$
DROP PROCEDURE IF EXISTS pulldb_atomic_rename $$
CREATE PROCEDURE pulldb_atomic_rename(IN p_staging_db VARCHAR(64), IN p_target_db VARCHAR(64))
BEGIN
    DECLARE v_table_count INT DEFAULT 0;
    DECLARE v_rename_sql TEXT;
    DECLARE v_first_table VARCHAR(255);

    -- Validate staging exists
    SELECT COUNT(*) INTO v_table_count
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = p_staging_db;

    IF v_table_count = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = CONCAT('Staging database ', p_staging_db, ' has no tables (empty or missing)');
    END IF;

    -- Drop target if exists (ensures clean cutover)
    IF EXISTS (
        SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = p_target_db
    ) THEN
        SET @drop_sql = CONCAT('DROP DATABASE `', p_target_db, '`');
        PREPARE stmt_drop FROM @drop_sql;
        EXECUTE stmt_drop;
        DEALLOCATE PREPARE stmt_drop;
    END IF;

    -- Build atomic RENAME statement for all tables
    SET v_rename_sql = NULL;
    SET @i = 0;

    -- Cursor simulation via GROUP_CONCAT(for atomic single statement)
    SELECT GROUP_CONCAT(
        CONCAT('`', p_staging_db, '`.`', TABLE_NAME, '` TO `', p_target_db, '`.`', TABLE_NAME, '`')
        SEPARATOR ', '
    ) INTO v_rename_sql
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = p_staging_db;

    IF v_rename_sql IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Failed to build RENAME TABLE statement (no tables)';
    END IF;

    -- Create target schema first
    SET @create_sql = CONCAT('CREATE DATABASE `', p_target_db, '`');
    PREPARE stmt_create FROM @create_sql;
    EXECUTE stmt_create;
    DEALLOCATE PREPARE stmt_create;

    -- Execute atomic rename
    SET @rename_sql = CONCAT('RENAME TABLE ', v_rename_sql);
    PREPARE stmt_rename FROM @rename_sql;
    EXECUTE stmt_rename;
    DEALLOCATE PREPARE stmt_rename;

    -- Verify target has tables now
    SELECT COUNT(*) INTO v_table_count
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = p_target_db;

    IF v_table_count = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = CONCAT('Atomic rename produced empty target ', p_target_db);
    END IF;
END $$
DELIMITER ;

-- Preview procedure: returns the atomic RENAME TABLE statement that would be
-- executed for a given staging->target pair without performing any changes.
-- Useful for:
--   * Diagnostic validation before deployment
--   * Benchmarking string build performance
--   * Dry-run tooling in CI or staging
--
-- Behavior:
--   1. Validate staging database contains tables
--   2. Build the single RENAME TABLE statement
--   3. Return it via SELECT (single row, single column rename_sql)
--
-- NOTE: Does NOT check or manipulate target database existence.
-- NOTE: Caller must ensure inputs meet naming constraints (<64 chars).
DELIMITER $$
DROP PROCEDURE IF EXISTS pulldb_atomic_rename_preview $$
CREATE PROCEDURE pulldb_atomic_rename_preview(IN p_staging_db VARCHAR(64), IN p_target_db VARCHAR(64))
BEGIN
    DECLARE v_table_count INT DEFAULT 0;
    DECLARE v_rename_sql TEXT;

    SELECT COUNT(*) INTO v_table_count
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = p_staging_db;

    IF v_table_count = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = CONCAT('Staging database ', p_staging_db, ' has no tables (empty or missing)');
    END IF;

    SELECT GROUP_CONCAT(
        CONCAT('`', p_staging_db, '`.`', TABLE_NAME, '` TO `', p_target_db, '`.`', TABLE_NAME, '`')
        SEPARATOR ', '
    ) INTO v_rename_sql
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = p_staging_db;

    IF v_rename_sql IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Failed to build RENAME TABLE statement (no tables)';
    END IF;

    SET @rename_preview_sql = CONCAT('RENAME TABLE ', v_rename_sql);
    SELECT @rename_preview_sql AS rename_sql;
END $$
DELIMITER ;
