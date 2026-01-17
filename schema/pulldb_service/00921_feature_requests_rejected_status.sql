-- 00921_feature_requests_rejected_status.sql
-- Change status enum from 'declined' to 'rejected'
-- Status values: open, in_progress, complete, rejected

-- Step 1: Add 'rejected' to the enum
ALTER TABLE feature_requests 
MODIFY COLUMN status ENUM('open', 'in_progress', 'complete', 'declined', 'rejected') NOT NULL DEFAULT 'open';

-- Step 2: Update any existing 'declined' records to 'rejected'
UPDATE feature_requests SET status = 'rejected' WHERE status = 'declined';

-- Step 3: Remove 'declined' from the enum (now that no records use it)
ALTER TABLE feature_requests 
MODIFY COLUMN status ENUM('open', 'in_progress', 'complete', 'rejected') NOT NULL DEFAULT 'open';
