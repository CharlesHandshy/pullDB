-- Migration 011: Fix settings key names
-- Direction: 1.2.0 → 1.3.0
-- Safe: All statements use NOT EXISTS guards.

-- Rename max_retention_months → max_retention_days (convert months × 30)
UPDATE settings
SET setting_key   = 'max_retention_days',
    setting_value = CAST(CAST(setting_value AS UNSIGNED) * 30 AS CHAR),
    description   = 'Maximum retention period in days for restored databases'
WHERE setting_key = 'max_retention_months'
  AND NOT EXISTS (
      SELECT 1 FROM (SELECT 1 FROM settings WHERE setting_key = 'max_retention_days') t
  );

-- Remove max_retention_increment (no longer used)
DELETE FROM settings WHERE setting_key = 'max_retention_increment';

-- Rename expiring_notice_days → expiring_warning_days
UPDATE settings
SET setting_key = 'expiring_warning_days'
WHERE setting_key = 'expiring_notice_days'
  AND NOT EXISTS (
      SELECT 1 FROM (SELECT 1 FROM settings WHERE setting_key = 'expiring_warning_days') t
  );

-- If expiring_warning_days already existed (rename was skipped), remove the
-- orphaned expiring_notice_days row so the old key doesn't persist.
DELETE FROM settings WHERE setting_key = 'expiring_notice_days';
