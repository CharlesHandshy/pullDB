-- 021_job_events.sql
-- Job event log
-- Source: 00200_job_events.sql (unchanged)

CREATE TABLE job_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id CHAR(36) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    detail TEXT,
    logged_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    
    CONSTRAINT fk_job_events_job FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- Index for filtering by job_id and ordering by logged_at
CREATE INDEX idx_job_events_job_id ON job_events(job_id, logged_at);

-- Index for efficient offset-based pagination (virtual scroll)
-- Query pattern: SELECT ... WHERE job_id = ? ORDER BY id DESC LIMIT ? OFFSET ?
CREATE INDEX idx_job_events_job_id_desc ON job_events(job_id, id DESC);
