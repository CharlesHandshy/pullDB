-- 070_overlord_tracking.sql
-- Tracks pullDB ownership and state of overlord.companies rows

CREATE TABLE IF NOT EXISTS overlord_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- What we're tracking (links to overlord.companies.database)
    database_name VARCHAR(50) NOT NULL,
    company_id INT NULL COMMENT 'overlord.companies.companyID if row exists',

    -- Ownership proof (must have deployed job for this database)
    job_id VARCHAR(36) NOT NULL COMMENT 'pullDB job UUID that owns this',
    job_target VARCHAR(255) NOT NULL COMMENT 'Copy of job.target for verification',
    created_by VARCHAR(50) NOT NULL COMMENT 'User who initiated the claim',

    -- State machine: claimed → synced → released
    status ENUM('claimed', 'synced', 'released') NOT NULL DEFAULT 'claimed',

    -- Backup for safe restoration (CRITICAL for safety)
    row_existed_before BOOLEAN NOT NULL DEFAULT FALSE
        COMMENT 'TRUE if overlord row existed before pullDB touched it',
    previous_dbhost VARCHAR(253) NULL
        COMMENT 'Original dbHost value before pullDB modification',
    previous_dbhost_read VARCHAR(253) NULL
        COMMENT 'Original dbHostRead value before pullDB modification',
    previous_snapshot JSON NULL
        COMMENT 'Full row snapshot for complete restoration',

    -- Current state (what we set in overlord)
    current_dbhost VARCHAR(253) NULL,
    current_dbhost_read VARCHAR(253) NULL,
    current_subdomain VARCHAR(30) NULL
        COMMENT 'Subdomain value written to overlord.companies',

    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    released_at DATETIME NULL,

    -- Constraints
    UNIQUE KEY uk_database_name (database_name),
    INDEX idx_job_id (job_id),
    INDEX idx_status (status),
    INDEX idx_user (created_by)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='Tracks pullDB ownership and state of overlord.companies rows';
