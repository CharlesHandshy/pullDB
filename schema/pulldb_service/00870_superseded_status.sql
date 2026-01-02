-- migrate:up
-- Add 'superseded' status to jobs status enum
-- Superseded jobs are those replaced by a newer restore to the same target

ALTER TABLE jobs MODIFY COLUMN status ENUM(
    'queued',
    'running', 
    'canceling',
    'failed',
    'complete',
    'canceled',
    'deleting',
    'deleted',
    'deployed',
    'expired',
    'superseded'
) NOT NULL DEFAULT 'queued';

-- migrate:down
-- Remove 'superseded' from status enum (requires no rows have this status)
ALTER TABLE jobs MODIFY COLUMN status ENUM(
    'queued',
    'running',
    'canceling', 
    'failed',
    'complete',
    'canceled',
    'deleting',
    'deleted',
    'deployed',
    'expired'
) NOT NULL DEFAULT 'queued';
