-- 041_audit_logs.sql
-- Audit log for manager/admin actions
-- Source: 00740_audit_logs.sql (unchanged)

CREATE TABLE audit_logs (
    audit_id CHAR(36) PRIMARY KEY,
    
    -- Who performed the action
    actor_user_id CHAR(36) NOT NULL,
    
    -- Target of the action (if applicable)
    target_user_id CHAR(36) NULL,
    
    -- What action was performed
    action VARCHAR(50) NOT NULL,
    -- Actions: 'submit_for_user', 'cancel_job', 'create_user', 
    --          'disable_user', 'enable_user', 'set_role', 'assign_manager'
    
    -- Human-readable detail
    detail TEXT NULL,
    
    -- Additional context as JSON
    context_json JSON NULL,
    
    -- Timestamp
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    
    -- Indexes for common queries
    INDEX idx_audit_logs_actor (actor_user_id),
    INDEX idx_audit_logs_target (target_user_id),
    INDEX idx_audit_logs_action (action),
    INDEX idx_audit_logs_created (created_at)
);

-- Note: No foreign key constraints to allow audit log preservation
-- even if users or jobs are deleted
