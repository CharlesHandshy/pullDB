-- 00920_feature_requests.sql
-- Feature requests with user voting system
-- Users can submit requests, all users can vote (1 vote per user per request)
-- Admins can update status (open -> in_progress -> complete/declined)

CREATE TABLE feature_requests (
    request_id CHAR(36) PRIMARY KEY,
    
    -- Submitter
    submitted_by_user_id CHAR(36) NOT NULL,
    
    -- Content
    title VARCHAR(200) NOT NULL,
    description TEXT NULL,
    
    -- Status: 'open', 'in_progress', 'complete', 'declined'
    status ENUM('open', 'in_progress', 'complete', 'declined') NOT NULL DEFAULT 'open',
    
    -- Vote aggregates (denormalized for performance)
    vote_score INT NOT NULL DEFAULT 0,  -- upvotes - downvotes
    upvote_count INT UNSIGNED NOT NULL DEFAULT 0,
    downvote_count INT UNSIGNED NOT NULL DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    
    -- Admin response (shown when complete/declined)
    admin_response TEXT NULL,
    
    -- Indexes
    INDEX idx_feature_requests_status (status),
    INDEX idx_feature_requests_score (vote_score DESC),
    INDEX idx_feature_requests_created (created_at DESC),
    INDEX idx_feature_requests_submitted_by (submitted_by_user_id),
    
    FOREIGN KEY (submitted_by_user_id) REFERENCES auth_users(user_id)
);

CREATE TABLE feature_request_votes (
    vote_id CHAR(36) PRIMARY KEY,
    request_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    
    -- Vote type: 1 = upvote, -1 = downvote
    vote_value TINYINT NOT NULL,
    
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    
    -- Ensure one vote per user per request
    UNIQUE KEY uk_user_request (user_id, request_id),
    
    FOREIGN KEY (request_id) REFERENCES feature_requests(request_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES auth_users(user_id)
);
