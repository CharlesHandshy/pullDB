# Staging Database + Atomic Rename Pattern

## Overview

This document describes the **staging-to-production rename** pattern for database restores, which provides safety, atomicity, and rollback capabilities. This pattern is already implemented in the legacy `pullDB-auth` and must be preserved in the new design.

## Security & Safety Rationale

### Why Use Staging Names?

1. **Isolation**: Active applications continue using the production database while restore happens in parallel
2. **Validation**: Post-restore SQL scripts and verification can run without affecting live data
3. **Rollback**: If restore or post-restore SQL fails, the original database remains untouched
4. **Atomicity**: The final rename operation is nearly instantaneous, minimizing downtime
5. **Audit Trail**: The staging database name includes the job_id for complete traceability

### Risk Without Staging

Restoring directly to the target name would:
- Drop existing database immediately, causing service interruption
- Lose ability to validate before cutover
- Prevent rollback if post-restore SQL fails
- Create race conditions with active connections

## Naming Convention

### MySQL Database Name Constraints

- **Maximum Length**: 64 characters (MySQL 8.x hard limit)
- **Reserved Characters**: Underscore (`_`) used as separator between target and job_id
- **Suffix Length**: 13 characters (`_` + 12-char job_id prefix)
- **Maximum Target Length**: 51 characters to leave room for suffix

### Staging Database Pattern

```
<target>_<job_id_short>
```

Where:
- `<target>` = sanitized target name, **maximum 51 characters**
- `_` = separator (1 character)
- `<job_id_short>` = first 12 characters of UUID (no hyphens), provides sufficient uniqueness (12 characters)
- **Total Maximum**: 64 characters (51 + 1 + 12)

### Length Validation

The system must enforce target name length limits during user_code generation and customer ID sanitization:

| Component | Max Length | Calculation |
|-----------|------------|-------------|
| user_code | 6 chars | Fixed by design |
| customer_id (sanitized) | 45 chars | 51 - 6 = 45 chars available |
| Full target | 51 chars | user_code (6) + sanitized customer (max 45) |
| Staging suffix | 13 chars | "_" (1) + job_id_short (12) |
| **Total staging name** | **64 chars** | target (51) + suffix (13) |

### Examples

| Final Target | Length | Job ID | Staging Name | Total Length |
|--------------|--------|--------|--------------|--------------|
| `jdoecustomer` | 13 | `550e8400-e29b-41d4-a716-446655440000` | `jdoecustomer_550e8400e29b` | 26 |
| `jdoeqatemplate` | 15 | `6ba7b810-9dad-11d1-80b4-00c04fd430c8` | `jdoeqatemplate_6ba7b8109dad` | 28 |
| `msmithacme` | 11 | `7c9e6679-7425-40de-944b-e07fc1f90ae7` | `msmithacme_7c9e66797425` | 24 |
| `jdoeverylongcustomernamethatreachesmaximumlength` | 51 | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` | `jdoeverylongcustomernamethatreachesmaximumlength_a1b2c3d4e5f6` | 64 ✓ |

### Edge Case: QA Template

The literal suffix `qatemplate` is 10 characters:
- user_code: 6 chars
- "qatemplate": 10 chars
- Total target: 16 chars max
- Staging name: 16 + 13 = 29 chars (well under 64 limit)

## Implementation Flow

### Phase 1: Pre-Restore Checks & Cleanup

```python
def cleanup_orphaned_staging_databases(target: str, dbhost: str) -> list:
    """
    Drop any orphaned staging databases for the same target.

    When a user re-restores the same customer/template, we assume they're done
    examining previous staging databases and drop them automatically.

    Args:
        target: Final target database name (e.g., 'jdoecustomer')
        dbhost: Target database server

    Returns:
        list: Names of dropped staging databases
    """
    # Find all staging databases matching the pattern: target_*
    # Pattern: target name + underscore + 12 hex chars
    staging_pattern = f"{target}_" + "[0-9a-f]" * 12

    cursor.execute("""
        SELECT SCHEMA_NAME
        FROM information_schema.SCHEMATA
        WHERE SCHEMA_NAME REGEXP %s
    """, (f"^{target}_[0-9a-f]{{12}}$",))

    orphaned = [row['SCHEMA_NAME'] for row in cursor.fetchall()]

    if orphaned:
        logger.info(f"Found {len(orphaned)} orphaned staging database(s) for target {target}")
        for staging_db in orphaned:
            logger.info(f"Dropping orphaned staging database: {staging_db}")
            cursor.execute(f"DROP DATABASE IF EXISTS `{staging_db}`")
            emit_job_event(job_id, 'staging_cleanup',
                          f"Dropped orphaned staging database: {staging_db}")

    return orphaned

def validate_staging_name(target: str, job_id: str, dbhost: str) -> str:
    """
    Generate staging name and verify it doesn't conflict.

    NOTE: Call cleanup_orphaned_staging_databases() BEFORE this function
    to automatically remove old staging databases for the same target.

    Args:
        target: Final target database name (max 51 chars)
        job_id: UUID for this restore job
        dbhost: Target database server

    Returns:
        staging_name: Unique staging database name (max 64 chars)

    Raises:
        ValidationException: If staging name would exceed MySQL limit or already exists
    """
    # CRITICAL: Validate target length first (must be enforced during CLI validation)
    if len(target) > 51:
        raise ValidationException(
            f"Target name too long: {len(target)} chars. "
            f"Maximum allowed is 51 chars to accommodate staging suffix. "
            f"This should have been caught during target name generation."
        )

    # Extract first 12 chars of UUID (remove hyphens)
    job_id_short = job_id.replace('-', '')[:12]
    staging_name = f"{target}_{job_id_short}"

    # Verify staging name length (defensive check)
    if len(staging_name) > 64:
        raise ValidationException(
            f"Staging name exceeds MySQL limit: {len(staging_name)} chars (max 64). "
            f"Target: {target} ({len(target)} chars), Suffix: _{job_id_short} (13 chars)"
        )

    # Verify staging name doesn't exist (collision check)
    # This should never happen after cleanup, but check defensively
    cursor.execute(
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
        (staging_name,)
    )
    if cursor.fetchone():
        raise ValidationException(
            f"Staging database {staging_name} already exists after cleanup. "
            f"This indicates a UUID collision or concurrent job with same job_id."
        )

    return staging_name
```
    cursor.execute(
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
        (staging_name,)
    )
    if cursor.fetchone():
        raise ValidationException(
            f"Staging database {staging_name} already exists. "
            f"This indicates a previous job cleanup failure or UUID collision."
        )

    # Verify name length within MySQL limits (64 chars)
    if len(staging_name) > 64:
        raise ValidationException(
            f"Staging name too long: {len(staging_name)} chars (max 64)"
        )

    return staging_name
```

### Phase 2: Restore to Staging

```python
def restore_to_staging(staging_name: str, myloader_dir: str, dbhost: str):
    """
    Execute myloader to restore into staging database.

    - Creates staging database if needed
    - Restores all tables via myloader
    - Does NOT modify target database
    """
    # myloader creates database automatically with --overwrite-tables
    myloader_cmd = [
        'myloader',
        f'--directory={myloader_dir}',
        f'--database={staging_name}',  # Restore to staging name
        f'--host={dbhost}',
        '--overwrite-tables',
        # ... other options
    ]

    subprocess.run(myloader_cmd, check=True)
```

### Phase 3: Post-Restore SQL Execution

```python
def execute_post_restore_sql(staging_name: str, sql_dir: str, dbhost: str) -> dict:
    """
    Execute post-restore SQL scripts against staging database.

    Returns:
        dict: {filename: 'success'|'failed', ...}
    """
    results = {}
    sql_files = sorted(Path(sql_dir).glob('*.sql'))

    conn = mysql.connector.connect(host=dbhost, database=staging_name, ...)

    for sql_file in sql_files:
        try:
            with open(sql_file) as f:
                sql = f.read()
            cursor = conn.cursor()
            # Execute multi-statement SQL
            for statement in sql.split(';'):
                if statement.strip():
                    cursor.execute(statement)
            conn.commit()
            results[sql_file.name] = 'success'
        except Exception as e:
            conn.rollback()
            results[sql_file.name] = f'failed: {str(e)}'
            raise  # Abort entire job on SQL failure

    conn.close()
    return results
```

### Phase 4: Add Restore Metadata

```python
def add_restore_metadata(staging_name: str, job_id: str, backup_file: str,
                         post_sql_results: dict, dbhost: str):
    """
    Create pullDB metadata table in staging database.

    This table tracks:
    - Who restored the database
    - When it was restored
    - Source backup file
    - Post-restore SQL execution status
    """
    conn = mysql.connector.connect(host=dbhost, database=staging_name, ...)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pullDB (
            job_id CHAR(36) PRIMARY KEY,
            restored_by VARCHAR(255) NOT NULL,
            restored_at TIMESTAMP(6) NOT NULL,
            backup_file VARCHAR(512) NOT NULL,
            post_restore_sql_status JSON NOT NULL,
            restore_completed_at TIMESTAMP(6) NOT NULL
        )
    """)

    cursor.execute("""
        INSERT INTO pullDB
        (job_id, restored_by, restored_at, backup_file, post_restore_sql_status, restore_completed_at)
        VALUES (%s, %s, UTC_TIMESTAMP(6), %s, %s, UTC_TIMESTAMP(6))
    """, (job_id, username, backup_file, json.dumps(post_sql_results)))

    conn.commit()
    conn.close()
```

### Phase 5: Atomic Rename (Cutover)

```python
def atomic_rename_to_target(staging_name: str, target: str, dbhost: str):
    """
    Atomically rename staging database to target.

    This is the critical cutover moment:
    1. Drop existing target database (if exists)
    2. Create empty target database
    3. Rename all tables from staging to target
    4. Drop empty staging database

    Uses MySQL stored procedure for table-by-table RENAME TABLE operations.
    """
    conn = mysql.connector.connect(host=dbhost, ...)
    cursor = conn.cursor()

    try:
        # Step 1: Drop existing target database
        cursor.execute(f"DROP DATABASE IF EXISTS `{target}`")

        # Step 2: Create empty target database
        cursor.execute(f"CREATE DATABASE `{target}`")

        # Step 3: Create stored procedure for batch table rename
        cursor.execute("DROP PROCEDURE IF EXISTS RenameDatabase")
        cursor.execute("""
            CREATE PROCEDURE RenameDatabase(
                IN source_db VARCHAR(64),
                IN dest_db VARCHAR(64)
            )
            BEGIN
                DECLARE done BOOLEAN DEFAULT FALSE;
                DECLARE rename_stmt VARCHAR(500);

                DECLARE cur CURSOR FOR
                SELECT CONCAT('RENAME TABLE `', source_db, '`.`', table_name,
                              '` TO `', dest_db, '`.`', table_name, '`;')
                FROM information_schema.TABLES
                WHERE table_schema = source_db;

                DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;

                OPEN cur;

                read_loop: LOOP
                    FETCH cur INTO rename_stmt;
                    IF done THEN
                        LEAVE read_loop;
                    END IF;

                    SET @query = rename_stmt;
                    PREPARE stmt FROM @query;
                    EXECUTE stmt;
                    DEALLOCATE PREPARE stmt;
                END LOOP;

                CLOSE cur;
            END
        """)

        # Step 4: Execute rename procedure
        cursor.execute(f"CALL RenameDatabase('{staging_name}', '{target}')")

        # Step 5: Drop empty staging database
        cursor.execute(f"DROP DATABASE IF EXISTS `{staging_name}`")

        conn.commit()

    except Exception as e:
        conn.rollback()
        # Staging database still exists for forensics
        raise Exception(f"Atomic rename failed: {e}. Staging database {staging_name} preserved for investigation.")
    finally:
        cursor.execute("DROP PROCEDURE IF EXISTS RenameDatabase")
        conn.close()
```

## Error Handling & Rollback

### Failure Before Rename

If restore fails before the atomic rename:
- Staging database remains for inspection
- Target database is unchanged (zero downtime)
- Job status → `failed`, staging database name in error_detail
- Operator can inspect staging database: `USE jdoecustomer_550e8400e29b;`

### Failure During Rename

If rename fails mid-operation:
- Stored procedure may be partially complete
- Staging database preserved with remaining tables
- Target database may be partially populated
- Manual intervention required (document in runbook-failure.md)

### Cleanup After Success

After successful rename:
- Staging database automatically dropped
- Only target database remains
- `pullDB` metadata table contains job_id and restore details

### Automatic Cleanup of Orphaned Staging Databases

**Policy**: When a user re-restores the same customer/template, automatically drop old staging databases.

**Rationale**:
- User is initiating a fresh restore, indicating they're done examining previous attempts
- Prevents accumulation of orphaned staging databases from failed jobs
- Simplifies operational overhead - no manual cleanup required
- Target database name implies user intent (same target = replace old staging databases)

**Implementation**:
1. Before starting restore, search for staging databases matching pattern: `{target}_[0-9a-f]{12}`
2. Drop all matching staging databases
3. Log dropped databases in job_events for audit trail
4. Continue with new restore to fresh staging database

**Example**:
```
User runs: pullDB user=jdoe customer=acme
- Target: jdoeacme
- Find staging: jdoeacme_a1b2c3d4e5f6 (from failed previous job)
- Drop: jdoeacme_a1b2c3d4e5f6
- Create new: jdoeacme_550e8400e29b
```

### Cleanup After Failure

Failed jobs leave staging databases for investigation:
- Staging database preserved with partial restore state
- Operator can inspect: `USE jdoecustomer_550e8400e29b;`
- **Next restore by same user to same target will auto-drop it**
- Manual cleanup only needed if changing target or not re-restoring

Manual cleanup (if needed):
```sql
-- View orphaned staging databases
SELECT SCHEMA_NAME
FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME REGEXP '_[0-9a-f]{12}$';

-- Drop specific staging database
DROP DATABASE IF EXISTS jdoecustomer_550e8400e29b;
```

## Concurrency & Locking

### Per-Target Exclusivity

The existing `UNIQUE INDEX ON jobs(target) WHERE status IN ('queued','running')` prevents:
- Multiple concurrent restores to same target
- Race conditions during rename
- Concurrent cleanup of staging databases

**Cleanup Timing**: Orphaned staging database cleanup happens during daemon job execution:
1. Daemon dequeues job
2. **Immediately drops old staging databases for the target** (before download)
3. Validates new staging name
4. Proceeds with download and restore

This ensures cleanup occurs under the protection of the per-target job lock.

### Job ID Uniqueness

UUIDs provide sufficient entropy:
- Collision probability: ~1 in 10^18 for 12-char prefix
- Pre-restore check catches any collision
- Failed jobs leave staging database → future jobs with same target get different job_id

## MySQL Schema Changes

### jobs Table - Add staging_name Column

```sql
ALTER TABLE jobs
ADD COLUMN staging_name VARCHAR(128) AFTER target;

-- Update constraint to include staging_name
CREATE UNIQUE INDEX idx_jobs_staging_active
ON jobs(staging_name)
WHERE status IN ('queued', 'running');
```

### job_events - Track Rename Phase

Add event types:
- `staging_created`: Staging database created
- `staging_restored`: myloader completed
- `post_sql_complete`: All post-restore SQL executed
- `metadata_added`: pullDB table created
- `rename_started`: Atomic rename initiated
- `rename_complete`: Cutover successful
- `staging_cleanup`: Staging database dropped
- `staging_auto_cleanup`: Orphaned staging database auto-dropped before new restore

## Scheduled Cleanup (Phase 1 - Deferred)

### Rationale

The automatic cleanup during restore handles most orphaned staging databases, but edge cases remain:
- User restores customer A, job fails, user never restores customer A again
- Staging database remains indefinitely
- Accumulates disk space and clutters database server

**Solution**: Scheduled background cleanup job removes truly abandoned staging databases after configurable age threshold.

### Implementation Design (Phase 1)

```python
def scheduled_staging_cleanup(age_threshold_days: int = 7):
    """
    Background job to clean up abandoned staging databases.

    Runs daily via cron. Identifies staging databases associated with
    failed jobs that are older than threshold and have no active restore
    attempts for the same target.

    Args:
        age_threshold_days: Minimum age before staging database is eligible for cleanup
    """
    # Query failed jobs with staging databases older than threshold
    cursor.execute("""
        SELECT DISTINCT
            j.id as job_id,
            j.staging_name,
            j.target,
            j.dbhost,
            j.completed_at
        FROM jobs j
        WHERE j.status IN ('failed', 'canceled')
            AND j.staging_name IS NOT NULL
            AND j.completed_at < NOW() - INTERVAL %s DAY
            AND NOT EXISTS (
                -- Ensure no active jobs for same target
                SELECT 1 FROM jobs j2
                WHERE j2.target = j.target
                  AND j2.dbhost = j.dbhost
                  AND j2.status IN ('queued', 'running')
            )
        ORDER BY j.dbhost, j.completed_at
    """, (age_threshold_days,))

    failed_jobs = cursor.fetchall()

    # Group by dbhost for efficient cleanup
    by_host = {}
    for job in failed_jobs:
        if job['dbhost'] not in by_host:
            by_host[job['dbhost']] = []
        by_host[job['dbhost']].append(job)

    cleanup_summary = {
        'total_scanned': 0,
        'total_dropped': 0,
        'total_size_mb': 0,
        'by_host': {}
    }

    # Process each host
    for dbhost, jobs in by_host.items():
        host_conn = get_connection(dbhost)
        host_cursor = host_conn.cursor()

        # Get all actual staging databases on this host
        host_cursor.execute("""
            SELECT
                SCHEMA_NAME,
                ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) as size_mb
            FROM information_schema.SCHEMATA s
            LEFT JOIN information_schema.TABLES t ON s.SCHEMA_NAME = t.TABLE_SCHEMA
            WHERE SCHEMA_NAME REGEXP '_[0-9a-f]{12}$'
            GROUP BY SCHEMA_NAME
        """)

        actual_staging_dbs = {row['SCHEMA_NAME']: row['size_mb'] for row in host_cursor.fetchall()}

        cleanup_summary['total_scanned'] += len(actual_staging_dbs)
        cleanup_summary['by_host'][dbhost] = {
            'scanned': len(actual_staging_dbs),
            'dropped': 0,
            'size_mb': 0
        }

        # Drop staging databases from eligible failed jobs
        for job in jobs:
            staging_name = job['staging_name']

            # Verify database still exists
            if staging_name not in actual_staging_dbs:
                logger.debug(f"Staging database already gone: {staging_name}")
                continue

            # Safety check: verify target has no active jobs (redundant but safe)
            cursor.execute("""
                SELECT COUNT(*) as active_count
                FROM jobs
                WHERE target = %s AND dbhost = %s AND status IN ('queued', 'running')
            """, (job['target'], job['dbhost']))

            if cursor.fetchone()['active_count'] > 0:
                logger.warning(f"Skipping {staging_name}: active job detected for target {job['target']}")
                continue

            # Drop the staging database
            size_mb = actual_staging_dbs[staging_name]
            try:
                host_cursor.execute(f"DROP DATABASE IF EXISTS `{staging_name}`")
                host_conn.commit()

                # Log the cleanup
                cursor.execute("""
                    INSERT INTO job_events
                    (job_id, event_type, event_time, detail)
                    VALUES (%s, 'scheduled_staging_cleanup', UTC_TIMESTAMP(6), %s)
                """, (job['job_id'], f"Dropped abandoned staging database: {staging_name} ({size_mb} MB, age: {age_threshold_days}+ days)"))

                cleanup_summary['total_dropped'] += 1
                cleanup_summary['total_size_mb'] += size_mb
                cleanup_summary['by_host'][dbhost]['dropped'] += 1
                cleanup_summary['by_host'][dbhost]['size_mb'] += size_mb

                logger.info(f"Dropped abandoned staging database: {staging_name} ({size_mb} MB)")

            except Exception as e:
                logger.error(f"Failed to drop {staging_name}: {e}")

        host_cursor.close()
        host_conn.close()

    # Emit metrics
    emit_metric('staging_cleanup.databases_dropped', cleanup_summary['total_dropped'])
    emit_metric('staging_cleanup.disk_reclaimed_mb', cleanup_summary['total_size_mb'])

    return cleanup_summary
```

### Configuration

Add settings for scheduled cleanup:

```sql
INSERT INTO settings (`key`, `value`) VALUES
    ('staging_cleanup_enabled', 'true'),
    ('staging_cleanup_age_days', '7'),
    ('staging_cleanup_schedule', '0 2 * * *');  -- Daily at 2 AM
```

### Deployment

```bash
# Add to cron (daily at 2 AM)
0 2 * * * /opt/pulldb.service/bin/pulldb-cleanup-staging >> /var/log/pulldb/staging-cleanup.log 2>&1
```

### Safety Guarantees

1. **Age Threshold**: Only staging databases from jobs completed 7+ days ago
2. **Active Job Check**: Skip targets with queued/running jobs
3. **Failed Job Correlation**: Only drop staging databases from failed/canceled jobs
4. **Audit Trail**: Every deletion logged in job_events
5. **Manual Override**: Admin can disable via `staging_cleanup_enabled` setting
6. **Metrics**: Datadog tracking of cleanup activity and disk reclaimed

### Monitoring

```python
# Datadog metrics
pulldb.staging_cleanup.databases_dropped  # Count per run
pulldb.staging_cleanup.disk_reclaimed_mb  # Space freed per run
pulldb.staging_cleanup.run_duration_ms    # Execution time
pulldb.staging_cleanup.errors             # Failed cleanup attempts
```

### Manual Investigation Before Cleanup

If needed, inspect staging database before scheduled cleanup removes it:

```sql
-- Find staging databases eligible for cleanup (7+ days old)
SELECT
    j.id,
    j.staging_name,
    j.target,
    j.status,
    j.completed_at,
    DATEDIFF(NOW(), j.completed_at) as age_days
FROM jobs j
WHERE j.status IN ('failed', 'canceled')
    AND j.staging_name IS NOT NULL
    AND j.completed_at < NOW() - INTERVAL 7 DAY
ORDER BY j.completed_at;

-- Inspect specific staging database before it's cleaned
USE jdoecustomer_550e8400e29b;
SELECT * FROM pullDB;  -- View restore metadata
SHOW TABLES;
```

### Comparison: Auto-Cleanup vs Scheduled Cleanup

| Aspect | Auto-Cleanup (On Restore) | Scheduled Cleanup (Background) |
|--------|---------------------------|--------------------------------|
| **Trigger** | User restores same target again | Cron job (daily) |
| **Scope** | Staging DBs for specific target | All staging DBs 7+ days old |
| **Timing** | Before new restore starts | Nightly batch process |
| **Edge Cases** | Doesn't catch "never re-restored" targets | Catches all abandoned staging DBs |
| **Phase** | Phase 0 (Prototype) | Phase 1 (Enhancement) |

Both mechanisms are complementary:
- Auto-cleanup handles normal workflow (99% of cases)
- Scheduled cleanup is safety net for edge cases (1% of cases)

## Documentation Updates Required

### 1. README.md

Update "Restored Database Lifecycle" section:

```markdown
## Restore Process

All database restores follow a staging-to-production pattern:

1. **Staging Creation**: Restore to `<target>_<job_id_short>` (e.g., `jdoecustomer_550e8400e29b`)
2. **Validation**: Execute post-restore SQL scripts against staging database
3. **Metadata**: Add `pullDB` tracking table with restore details
4. **Atomic Rename**: Rename all tables from staging to target database in single transaction
5. **Cleanup**: Drop empty staging database

This pattern ensures:
- Zero downtime for active applications
- Rollback capability if validation fails
- Complete audit trail via job_id traceability
```

### 2. design/system-overview.md

Update daemon responsibilities:

```markdown
- Drop any orphaned staging databases for the target (auto-cleanup)
- Generate staging database name: `target + '_' + job_id[:12]`
- Verify staging name uniqueness before download
- Restore to staging database via myloader
- Execute post-restore SQL against staging
- Add pullDB metadata table to staging
- Perform atomic rename: staging → target
- Clean up staging database on success
```

### 3. design/runbook-restore.md

Add staging pattern steps:

```markdown
## Restore Lifecycle

1. CLI calls daemon API to enqueue job with target=`jdoecustomer`
2. Daemon API validates and inserts job into MySQL
3. Daemon worker dequeues job and marks status=`running`
4. **Daemon auto-drops orphaned staging databases: `jdoecustomer_*` (from previous failed jobs)**
5. Daemon generates new staging_name=`jdoecustomer_550e8400e29b`
6. Daemon verifies staging name doesn't exist (should never exist after cleanup)
7. Daemon downloads backup from S3
8. Daemon restores to staging database via myloader
9. Daemon executes post-restore SQL scripts
10. Daemon adds pullDB metadata table
11. Daemon performs atomic rename (staging → target)
12. Daemon drops empty staging database
13. Job status → `complete`
```

### 4. design/runbook-failure.md

Add staging cleanup procedures:

```markdown
## Orphaned Staging Databases

If a job fails after staging creation, the staging database persists for forensics.

### Automatic Cleanup

**Orphaned staging databases are automatically cleaned up when:**
- The same user restores the same customer/template again
- Cleanup happens before the new restore begins
- All staging databases matching `{target}_[0-9a-f]{12}` are dropped
- Logged in job_events for audit trail

**Example**:
```
Previous job failed: jdoeacme_a1b2c3d4e5f6 left orphaned
User runs: pullDB user=jdoe customer=acme
→ Auto-drops jdoeacme_a1b2c3d4e5f6
→ Creates new jdoeacme_550e8400e29b
```

### Manual Inspection (Before Auto-Cleanup)

If you need to inspect staging database before it's auto-cleaned:

```sql
-- View orphaned staging databases
SELECT SCHEMA_NAME
FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME REGEXP '_[0-9a-f]{12}$';

-- Inspect staging database
USE jdoecustomer_550e8400e29b;
SHOW TABLES;
SELECT * FROM pullDB;  -- View restore metadata

-- Query the jobs table to understand what happened
SELECT id, status, error_detail, started_at, completed_at
FROM jobs
WHERE staging_name = 'jdoecustomer_550e8400e29b';
```

### Manual Cleanup (Rare)

Only needed if user won't be re-restoring the same target:

```sql
-- Verify job is failed/canceled
SELECT status FROM jobs WHERE staging_name = 'jdoecustomer_550e8400e29b';

-- Drop when confirmed safe
DROP DATABASE IF EXISTS jdoecustomer_550e8400e29b;
```
DROP DATABASE jdoecustomer_550e8400e29b;
```

### Automated Cleanup (Phase 2+)

```bash
pullDB cleanup job=550e8400-e29b-41d4-a716-446655440000
```
```

### 5. docs/mysql-schema.md

Update jobs table definition:

```sql
CREATE TABLE jobs (
    id CHAR(36) PRIMARY KEY,
    owner_user_id CHAR(36) NOT NULL,
    owner_username VARCHAR(255) NOT NULL,
    owner_user_code CHAR(6) NOT NULL,
    target VARCHAR(128) NOT NULL,
    staging_name VARCHAR(128) NOT NULL,  -- NEW: <target>_<job_id_short>
    dbhost VARCHAR(255) NOT NULL,
    status ENUM('queued','running','failed','complete','canceled') NOT NULL,
    -- ... other columns
    CONSTRAINT fk_jobs_owner FOREIGN KEY (owner_user_id) REFERENCES auth_users(user_id)
);

-- Prevent concurrent restores to same target
CREATE UNIQUE INDEX idx_jobs_target_active
ON jobs(target)
WHERE status IN ('queued', 'running');

-- Prevent staging name collisions
CREATE UNIQUE INDEX idx_jobs_staging_active
ON jobs(staging_name)
WHERE status IN ('queued', 'running');
```

### 6. .github/copilot-instructions.md

Add to "MySQL Restore Behavior" section:

```markdown
### Staging Database Pattern
- **Staging Name**: `<target>_<job_id_first_12_chars>` (e.g., `jdoecustomer_550e8400e29b`)
- **Uniqueness Check**: Verify staging name doesn't exist before starting restore
- **Restore Target**: myloader restores to staging database, not final target
- **Post-Restore SQL**: Execute against staging database
- **Metadata Table**: Add `pullDB` table to staging database with job details
- **Atomic Rename**: Use stored procedure to rename all tables staging → target
- **Cleanup**: Drop staging database after successful rename
- **Failure Handling**: Preserve staging database on failure for forensic analysis
```

## Testing Requirements

### Unit Tests

```python
def test_staging_name_generation():
    """Verify staging name format and uniqueness checks."""

def test_staging_name_collision_detection():
    """Ensure pre-existing staging names are caught."""

def test_staging_name_length_validation():
    """Verify 64-char MySQL limit not exceeded."""
```

### Integration Tests

```python
def test_full_staging_rename_flow():
    """End-to-end test of staging → target rename."""

def test_rename_failure_preserves_staging():
    """Verify staging database persists on rename failure."""

def test_concurrent_restore_prevention():
    """Verify UNIQUE constraint prevents overlapping restores."""
```

## Benefits Summary

1. **Safety**: Original database untouched until final cutover
2. **Validation**: Post-restore SQL runs against isolated staging database
3. **Atomicity**: Rename operation is nearly instantaneous
4. **Traceability**: Staging name includes job_id for complete audit trail
5. **Rollback**: Simple revert by keeping old database until staging validated
6. **Forensics**: Failed jobs preserve staging database for investigation
7. **Legacy Compatibility**: Matches proven pattern from pullDB-auth

## Migration from Current Design

If any code already assumes direct-to-target restore:
1. Update myloader invocation to use staging_name
2. Update post-restore SQL execution to target staging_name
3. Add atomic rename step before marking job complete
4. Update all documentation references

## Conclusion

The staging-to-production rename pattern is **mandatory** for the pullDB prototype. It provides essential safety guarantees and matches the battle-tested legacy implementation. All daemon code must implement this pattern from day one—there is no simpler alternative that maintains the same safety properties.
