-- 042_procedure_deployments.sql
-- Stored procedure deployment tracking
-- Source: 00800_procedure_deployments.sql (unchanged)

CREATE TABLE procedure_deployments (
    id CHAR(36) PRIMARY KEY COMMENT 'UUID of deployment event',
    host VARCHAR(255) NOT NULL COMMENT 'MySQL hostname where procedure deployed',
    procedure_name VARCHAR(64) NOT NULL COMMENT 'Name of stored procedure (pulldb_atomic_rename)',
    version_deployed VARCHAR(20) NOT NULL COMMENT 'Semantic version deployed (e.g., 1.0.0)',
    deployed_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6) COMMENT 'When deployment occurred',
    deployed_by VARCHAR(50) COMMENT 'User or service that deployed (e.g., worker-1, admin)',
    deployment_reason ENUM('initial','version_mismatch','missing') NOT NULL COMMENT 'Why deployment happened',
    job_id CHAR(36) NULL COMMENT 'Job UUID that triggered deployment (if applicable)',
    
    INDEX idx_host_proc_time (host, procedure_name, deployed_at DESC)
        COMMENT 'Fast lookup of latest version for host+procedure',
    INDEX idx_job_id (job_id)
        COMMENT 'Track which jobs triggered deployments',
    INDEX idx_deployed_at (deployed_at DESC)
        COMMENT 'Time-based queries for audit'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 
  COMMENT='Deployment history for pulldb_atomic_rename stored procedures';
