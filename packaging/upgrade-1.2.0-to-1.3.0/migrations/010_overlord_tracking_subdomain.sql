-- Migration 010: Add current_subdomain to overlord_tracking
-- Direction: 1.2.0 → 1.3.0
-- Safe: Wrapped in IF NOT EXISTS guard via stored procedure pattern.

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'overlord_tracking'
      AND COLUMN_NAME = 'current_subdomain'
);

SET @sql = IF(@col_exists = 0,
    'ALTER TABLE overlord_tracking
        ADD COLUMN current_subdomain VARCHAR(30) NULL
        COMMENT ''Subdomain value written to overlord.companies''
        AFTER current_dbhost_read',
    'SELECT ''010: current_subdomain already exists, skipping'' AS migration_status'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
