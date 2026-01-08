# Atomic Rename Silent Failure Fix - Implementation Plan

## Problem Summary

Job `380a026a-5dc9-4eb2-b699-17681534c230` on aurora-test for user charleshandshy had atomic rename fail silently:
- Staging database still exists with tables
- Target database does not exist
- pullDB reported job as successful
- Root cause: No validation after stored procedure execution, assumed success if no exception

## Solution: KISS Approach - Basic Validation & Version Management

### Implementation Steps (Sequential Order)

#### 1. Create Deployment Audit Table
**File**: `schema/pulldb_service/00800_procedure_deployments.sql`
```sql
CREATE TABLE procedure_deployments (
    id CHAR(36) PRIMARY KEY,
    host VARCHAR(255) NOT NULL,
    procedure_name VARCHAR(64) NOT NULL,
    version_deployed VARCHAR(20) NOT NULL,
    deployed_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
    deployed_by VARCHAR(50),
    deployment_reason ENUM('initial','version_mismatch','missing') NOT NULL,
    job_id CHAR(36) NULL,
    INDEX idx_host_proc_time (host, procedure_name, deployed_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

#### 2. Add CREATE ROUTINE Grant
**File**: `pulldb/infra/mysql_provisioning.py`
**Function**: `create_mysql_user()` around line 900-950
**Change**: Add `CREATE ROUTINE` to the GRANT statement
```sql
GRANT CREATE, DROP, ALTER, SELECT, INSERT, UPDATE, DELETE, INDEX, CREATE ROUTINE ON *.* TO '{username}'@'%'
```

#### 3. Update Procedure to v1.0.0 with Streaming Progress
**File**: `docs/hca/features/atomic_rename_procedure.sql`
**Changes**:
- Line 2: Change version from `1.1.0` to `1.0.0`
- Add streaming progress output: Before building the RENAME statement, iterate through tables and output:
  ```sql
  -- For each table, output progress as separate result set
  SELECT table_name, 'renaming' AS status FROM information_schema.TABLES 
  WHERE TABLE_SCHEMA = p_staging_db;
  ```

#### 4. Add Pre-Validation Function
**File**: `pulldb/worker/atomic_rename.py`
**Location**: Insert at line ~200 (before `atomic_rename_staging_to_target`)
```python
def _pre_validate_atomic_rename(
    conn: MySQLConnection,
    staging_db: str,
    target_db: str,
) -> int:
    """Validate preconditions before atomic rename.
    
    Returns:
        int: Table count in staging database
        
    Raises:
        AtomicRenameError: If validation fails
    """
    cursor = conn.cursor()
    
    # Check staging has tables
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
        (staging_db,)
    )
    staging_count = cursor.fetchone()[0]
    if staging_count == 0:
        raise AtomicRenameError(
            staging_name=staging_db,
            target_name=target_db,
            error_message=f"Pre-validation failed: Staging database '{staging_db}' has no tables"
        )
    
    # Check target doesn't exist
    cursor.execute("SHOW DATABASES LIKE %s", (target_db,))
    if cursor.fetchone():
        raise AtomicRenameError(
            staging_name=staging_db,
            target_name=target_db,
            error_message=f"Pre-validation failed: Target database '{target_db}' already exists"
        )
    
    cursor.close()
    return staging_count
```

#### 5. Add Post-Validation Function
**File**: `pulldb/worker/atomic_rename.py`
**Location**: Insert at line ~210 (after pre-validation)
```python
def _post_validate_atomic_rename(
    conn: MySQLConnection,
    staging_db: str,
    target_db: str,
    expected_table_count: int,
) -> None:
    """Validate postconditions after atomic rename.
    
    Raises:
        AtomicRenameError: If validation fails
    """
    cursor = conn.cursor()
    errors = []
    
    # Check staging is gone
    cursor.execute("SHOW DATABASES LIKE %s", (staging_db,))
    if cursor.fetchone():
        errors.append(f"Staging database '{staging_db}' still exists after rename")
    
    # Check target exists
    cursor.execute("SHOW DATABASES LIKE %s", (target_db,))
    if not cursor.fetchone():
        errors.append(f"Target database '{target_db}' does not exist after rename")
    else:
        # Check table count matches
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
            (target_db,)
        )
        actual_count = cursor.fetchone()[0]
        if actual_count != expected_table_count:
            logger.warning(
                f"Table count mismatch: expected {expected_table_count}, got {actual_count}"
            )
            errors.append(
                f"Table count mismatch: expected {expected_table_count} tables, got {actual_count}"
            )
    
    cursor.close()
    
    if errors:
        raise AtomicRenameError(
            staging_name=staging_db,
            target_name=target_db,
            error_message=f"Post-validation failed: {'; '.join(errors)}"
        )
```

#### 6. Enhance Version Enforcement with Auto-Deploy
**File**: `pulldb/worker/atomic_rename.py`
**Function**: `ensure_atomic_rename_procedure()` around line 152-168
**Changes**:
1. Add constant: `EXPECTED_PROCEDURE_VERSION = "1.0.0"`
2. Check `conn._pulldb_procedure_version` attribute (once per connection)
3. Check if host is disabled first, skip if disabled
4. Acquire 30s advisory lock: `GET_LOCK('pulldb_proc_deploy_{host}', 30)`
5. Check for stale locks via `IS_USED_LOCK()`, if >30s disable host
6. Query `SHOW CREATE PROCEDURE`, parse version with regex: `r'Version:?\s*v?(\d+\.\d+\.\d+)'`
7. If version mismatch, recheck after acquiring lock (another worker may have deployed)
8. If still mismatch, deploy procedure from `docs/hca/features/atomic_rename_procedure.sql`
9. Insert record to `procedure_deployments` table
10. Verify `RELEASE_LOCK()` returns 1
11. Recheck version after deployment
12. Cache version in `conn._pulldb_procedure_version`
13. If deployment fails, disable host and raise error

#### 7. Integrate Validations into atomic_rename_staging_to_target
**File**: `pulldb/worker/atomic_rename.py`
**Function**: `atomic_rename_staging_to_target()` around line 174-203
**Changes**:
1. Add pre-validation call before `_execute_atomic_rename_procedure`:
   ```python
   staging_table_count = _pre_validate_atomic_rename(conn, rename_spec.staging_db, rename_spec.target_db)
   ```
2. After `_execute_atomic_rename_procedure`, consume streaming result sets and log:
   ```python
   for rs in cursor.stored_results():
       rows = rs.fetchall()
       if rows:
           for row in rows:
               logger.info(f"Rename progress: {row}")
   ```
3. Add post-validation call:
   ```python
   _post_validate_atomic_rename(conn, rename_spec.staging_db, rename_spec.target_db, staging_table_count)
   ```
4. Add final staging dropped check:
   ```python
   cursor.execute("SHOW DATABASES LIKE %s", (rename_spec.staging_db,))
   if cursor.fetchone():
       raise AtomicRenameError(
           staging_name=rename_spec.staging_db,
           target_name=rename_spec.target_db,
           error_message="Staging database still exists after DROP DATABASE"
       )
   ```
5. Log `atomic_rename_complete` event to job_events with validation details

#### 8. Handle Lock Timeout in Worker
**File**: `pulldb/worker/service.py`
**Function**: `_execute_restore_workflow()` around line 650-700
**Change**: Wrap atomic rename in try/except for `ProcedureLockTimeoutError`:
```python
try:
    atomic_rename_staging_to_target(rename_conn, rename_spec)
except ProcedureLockTimeoutError as e:
    # Check if lock is stale
    cursor = rename_conn.cursor()
    cursor.execute("SELECT IS_USED_LOCK(%s)", (f'pulldb_proc_deploy_{host}',))
    lock_thread_id = cursor.fetchone()[0]
    if lock_thread_id:
        logger.critical(f"Stale procedure deployment lock detected on {host}, disabling host")
        # Disable host
        # Release job for retry
    cursor.close()
    raise
```

#### 9. Create Debug Script for Failed Job
**File**: `scripts/debug_atomic_rename_silent_failure.py`
**Purpose**: Retry job `380a026a-5dc9-4eb2-b699-17681534c230`
**Contents**: Script from research findings that:
1. Queries job details from pulldb_service.jobs
2. Gets host credentials from AWS Secrets Manager
3. Verifies staging/target database state
4. Calls atomic_rename_staging_to_target() manually
5. Marks job complete or failed based on outcome
6. Outputs comprehensive diagnostics

#### 10. Apply Schema Migration
Run migration to create procedure_deployments table:
```bash
sudo mysql pulldb_service < schema/pulldb_service/00800_procedure_deployments.sql
```

#### 11. Deploy Updated Procedure to All Hosts
For each enabled host in db_hosts:
```bash
mysql -h <host> -u <admin> -p < docs/hca/features/atomic_rename_procedure.sql
```
Or rely on auto-deploy (preferred - will happen on first job)

#### 12. Run Debug Script to Fix Failed Job
```bash
cd /home/charleshandshy/Projects/pullDB
source .venv/bin/activate
python3 scripts/debug_atomic_rename_silent_failure.py
```

#### 13. Rebuild and Restart Services
```bash
make dev-rebuild
# Or for production:
./scripts/build_deb.sh
sudo systemctl restart pulldb-worker@{1,2,3}
```

## Key Design Decisions

1. **KISS Principle**: Simple validation checks, no complex notification systems
2. **Always-On Validation**: Pre and post validation ALWAYS run, no configuration flags
3. **Once-Per-Connection Version Check**: Cached in connection object to avoid repeated checks
4. **30s Advisory Lock**: Prevents concurrent deployments, stale lock detection disables host
5. **Streaming Progress**: Procedure outputs result sets for real-time job log updates
6. **Exact Table Count**: Post-validation requires exact match, logs warning if mismatch
7. **Auto-Deploy on Mismatch**: Automatically deploys correct version, disables host if fails
8. **Fail Hard**: Validation failures preserve staging database and mark job as failed

## Testing Checklist

- [ ] Create procedure_deployments table
- [ ] Add CREATE ROUTINE grant to mysql_provisioning.py
- [ ] Update procedure to v1.0.0 with streaming output
- [ ] Implement pre-validation function
- [ ] Implement post-validation function
- [ ] Enhance ensure_atomic_rename_procedure with auto-deploy
- [ ] Integrate validations into atomic_rename_staging_to_target
- [ ] Handle lock timeout in worker service
- [ ] Create and run debug script for failed job
- [ ] Verify job 380a026a completes successfully or fails with preserved staging
- [ ] Test new job on aurora-test with validation
- [ ] Verify procedure auto-deploys on version mismatch
- [ ] Test stale lock detection and host disable
- [ ] Verify streaming progress appears in job logs

## Files to Modify

1. `schema/pulldb_service/00800_procedure_deployments.sql` - NEW
2. `docs/hca/features/atomic_rename_procedure.sql` - MODIFY (version + streaming)
3. `pulldb/infra/mysql_provisioning.py` - MODIFY (add CREATE ROUTINE grant)
4. `pulldb/worker/atomic_rename.py` - MAJOR CHANGES (validations, version enforcement)
5. `pulldb/worker/service.py` - MODIFY (lock timeout handling)
6. `scripts/debug_atomic_rename_silent_failure.py` - NEW

## References

- Job ID: `380a026a-5dc9-4eb2-b699-17681534c230`
- Host: `aurora-test`
- User: `charleshandshy`
- MySQL Version: 8.x / Aurora 3.x
- Current Procedure Version: 1.1.0 (needs downgrade to 1.0.0)
- Expected Procedure Version: 1.0.0
