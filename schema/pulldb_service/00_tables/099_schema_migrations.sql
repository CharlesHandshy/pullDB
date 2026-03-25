-- 099_schema_migrations.sql
-- Track which schema files have been applied
-- Run this LAST after all tables are created
-- Source: 00001_schema_migrations.sql (unchanged)

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
