-- migrate:up
-- =============================================================================
-- Phase 1: Add cancel_requested_at column
-- Enables user-initiated job cancellation
-- The worker checks this field and aborts gracefully if set
-- =============================================================================

ALTER TABLE jobs 
ADD COLUMN cancel_requested_at TIMESTAMP(6) NULL DEFAULT NULL 
AFTER error_detail;


-- migrate:down
-- =============================================================================
-- Rollback: Remove cancel_requested_at column
-- =============================================================================

ALTER TABLE jobs DROP COLUMN cancel_requested_at;
