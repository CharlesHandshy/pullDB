-- migrate:up
-- =============================================================================
-- Phase 1: Add cancel_requested_at column
-- Enables user-initiated job cancellation
-- The worker checks this field and aborts gracefully if set
-- =============================================================================

ALTER TABLE jobs 
ADD COLUMN cancel_requested_at TIMESTAMP NULL DEFAULT NULL 
AFTER finished_at;


-- migrate:down
-- =============================================================================
-- Rollback: Remove cancel_requested_at column
-- =============================================================================

ALTER TABLE jobs DROP COLUMN cancel_requested_at;
