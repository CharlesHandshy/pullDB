-- 00001_schema_migrations.sql
-- Track which schema files have been applied
-- This enables incremental migrations on upgrades

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);

