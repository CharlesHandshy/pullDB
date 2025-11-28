-- 031_db_hosts_alias.sql
-- Add host_alias column for short hostname support
-- Allows users to use short names like "dev-db-01" instead of full FQDNs

ALTER TABLE db_hosts
ADD COLUMN host_alias VARCHAR(64) NULL AFTER hostname;

-- Create unique index for alias lookups (allows NULL for hosts without aliases)
CREATE UNIQUE INDEX idx_db_hosts_alias ON db_hosts(host_alias);
