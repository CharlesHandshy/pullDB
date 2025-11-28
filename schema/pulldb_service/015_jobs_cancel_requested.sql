-- 015_jobs_cancel_requested.sql
-- Phase 1: Add cancellation support column
-- This column signals that a user has requested job cancellation.
-- The worker checks this flag periodically during long operations.

ALTER TABLE jobs ADD COLUMN cancel_requested_at TIMESTAMP(6) NULL AFTER error_detail;

-- Note: MySQL 8 does not support partial indexes (WHERE clause).
-- The column is nullable; checking IS NOT NULL is efficient enough for our use case
-- since most jobs will have NULL (not canceled).
