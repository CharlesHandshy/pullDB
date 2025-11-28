-- migrate:up
-- =============================================================================
-- Seed Data: Default database host (localhost)
-- Required for development and single-server deployments
-- Additional hosts can be added via INSERT for multi-host environments
-- =============================================================================

INSERT IGNORE INTO db_hosts (host, description, is_enabled)
VALUES ('localhost', 'Local development host', TRUE);


-- migrate:down
-- =============================================================================
-- Rollback: Remove localhost seed data
-- Note: Uses specific delete to avoid removing user-added hosts
-- =============================================================================

DELETE FROM db_hosts WHERE host = 'localhost' AND description = 'Local development host';
