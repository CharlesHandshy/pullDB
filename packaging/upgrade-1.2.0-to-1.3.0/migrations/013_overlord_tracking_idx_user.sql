-- Migration 013: Add idx_user index to overlord_tracking
-- Direction: 1.2.0 → 1.3.0
-- Safe: Wrapped in IF NOT EXISTS guard.

SET @idx_exists = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'overlord_tracking'
      AND INDEX_NAME   = 'idx_user'
);

SET @sql = IF(@idx_exists = 0,
    'ALTER TABLE overlord_tracking ADD INDEX idx_user (created_by)',
    'SELECT ''013: idx_user already exists, skipping'' AS migration_status'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
