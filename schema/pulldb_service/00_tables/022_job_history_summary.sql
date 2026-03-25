-- 022_job_history_summary.sql
-- Aggregated metrics from completed jobs for historical reporting
-- Isolated table: no foreign keys, manual management only

CREATE TABLE job_history_summary (
    job_id CHAR(36) PRIMARY KEY,
    
    -- Job identity (denormalized for fast queries)
    owner_user_id CHAR(36) NOT NULL,
    owner_username VARCHAR(255) NOT NULL,
    dbhost VARCHAR(255) NOT NULL,
    target VARCHAR(255) NOT NULL,
    custom_target TINYINT(1) NOT NULL DEFAULT 0,
    
    -- Timestamps
    submitted_at TIMESTAMP(6) NOT NULL,
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NOT NULL,
    
    -- Outcome
    final_status ENUM('complete', 'failed', 'canceled') NOT NULL,
    error_category ENUM(
        'download_timeout',
        'download_failed',
        'extraction_failed',
        'mysql_error',
        'disk_full',
        's3_access_denied',
        'canceled_by_user',
        'worker_crash',
        'uncategorized'
    ) NULL COMMENT 'Categorized failure reason',
    
    -- Data volume metrics
    archive_size_bytes BIGINT NULL 
        COMMENT 'Downloaded archive size',
    extracted_size_bytes BIGINT NULL 
        COMMENT 'Extracted data size on disk',
    table_count INT NULL 
        COMMENT 'Number of tables restored',
    total_rows BIGINT NULL 
        COMMENT 'Total rows restored across all tables',
    
    -- Phase durations (seconds)
    total_duration_seconds DECIMAL(10,2) NULL,
    discovery_duration_seconds DECIMAL(10,2) NULL,
    download_duration_seconds DECIMAL(10,2) NULL,
    extraction_duration_seconds DECIMAL(10,2) NULL,
    myloader_duration_seconds DECIMAL(10,2) NULL,
    post_sql_duration_seconds DECIMAL(10,2) NULL,
    metadata_duration_seconds DECIMAL(10,2) NULL,
    atomic_rename_duration_seconds DECIMAL(10,2) NULL,
    
    -- Throughput metrics
    download_mbps DECIMAL(8,2) NULL 
        COMMENT 'Download throughput MB/s',
    restore_rows_per_second INT NULL 
        COMMENT 'Average rows/s during myloader phase',
    
    -- Source backup info
    backup_date DATE NULL 
        COMMENT 'Date of the backup being restored',
    backup_s3_path VARCHAR(1024) NULL 
        COMMENT 'S3 path of the backup archive',
    
    -- Worker info
    worker_id VARCHAR(255) NULL,
    
    -- Metadata
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    
    -- Indexes for common queries
    INDEX idx_history_user (owner_user_id, completed_at DESC),
    INDEX idx_history_host (dbhost, completed_at DESC),
    INDEX idx_history_status (final_status, completed_at DESC),
    INDEX idx_history_date (completed_at DESC),
    INDEX idx_history_backup_date (backup_date, dbhost),
    INDEX idx_history_username (owner_username, completed_at DESC)
    
    -- NO FOREIGN KEY - isolated table for long-term retention
);
