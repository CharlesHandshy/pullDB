-- Migration 012: Add origin column to jobs table
-- Direction: 1.2.0 → 1.3.0
-- Safe: Wrapped in IF NOT EXISTS guard.

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'jobs'
      AND COLUMN_NAME = 'origin'
);

SET @sql = IF(@col_exists = 0,
    "ALTER TABLE jobs ADD COLUMN origin ENUM('restore','claim','assign')
        NOT NULL DEFAULT 'restore'
        COMMENT 'How this job entered pullDB tracking: restore (normal pipeline), claim (user self-claimed via discovery), assign (admin assigned via discovery)'",
    "SELECT '012: origin column already exists, skipping' AS migration_status"
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
