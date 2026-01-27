# Staging Database Lifecycle

> **EXTENDS**: engineering-dna/standards/database.md (schema patterns)

---

## Naming Convention

Staging databases use a predictable naming pattern to enable:
1. Orphan detection (abandoned restores)
2. Target deconfliction (multiple jobs for same target)
3. Atomic rename to production name

### Pattern

```
{target}_{job_id_first_12}
```

| Component | Source | Max Length | Example |
|-----------|--------|------------|---------|
| target | `jobs.target` | 51 chars | `acme_production` |
| separator | literal | 1 char | `_` |
| job_id_first_12 | `jobs.job_id[:12]` | 12 chars | `a1b2c3d4e5f6` |

**Total**: 64 characters (MySQL identifier limit)

### Implementation

```python
def generate_staging_name(target: str, job_id: str) -> str:
    """Generate staging database name from target and job ID.
    
    Args:
        target: Original database target name
        job_id: UUID job identifier
        
    Returns:
        Staging database name (max 64 chars)
        
    Raises:
        ValueError: If target exceeds 51 characters
    """
    MAX_TARGET_LEN = 51  # 64 - 1 (separator) - 12 (job_id prefix)
    
    if len(target) > MAX_TARGET_LEN:
        raise ValueError(
            f"Target name '{target}' exceeds {MAX_TARGET_LEN} characters. "
            f"Cannot generate staging name within MySQL 64-char limit."
        )
    
    job_prefix = job_id.replace("-", "")[:12]
    return f"{target}_{job_prefix}"
```

---

## Lifecycle Phases

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   CREATE    │────▶│   RESTORE   │────▶│  POST-SQL   │────▶│   RENAME    │
│  staging DB │     │  via myloader│     │  execution  │     │  atomic swap│
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │                   │
       ▼                   ▼                   ▼                   ▼
   CLEANUP on          CLEANUP on          CLEANUP on          SUCCESS
   failure             failure             failure             (or CLEANUP)
```

### Phase 1: Create Staging Database

```python
def create_staging_database(
    connection: MySQLConnection,
    staging_name: str,
    job_id: str,
) -> None:
    """Create empty staging database for restore target.
    
    FAIL HARD: Raises if database creation fails.
    """
    # Validate name is safe (no injection)
    if not SAFE_IDENTIFIER_RE.match(staging_name):
        raise StagingError(f"Invalid staging name: {staging_name}")
    
    cursor = connection.cursor()
    try:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{staging_name}`")
        logger.info("staging_created", job_id=job_id, database=staging_name)
    except MySQLError as e:
        raise StagingError(
            f"Failed to create staging database '{staging_name}'. "
            f"Error: {e}"
        ) from e
```

### Phase 2: Restore (see myloader.md)

### Phase 3: Post-SQL Execution (see post-sql.md)

### Phase 4: Atomic Rename

```sql
-- Stored procedure: pulldb_atomic_rename
-- Atomically swaps staging -> production

CALL pulldb_atomic_rename(
    @staging_db := 'acme_production_a1b2c3d4e5f6',
    @target_db := 'acme_production',
    @backup_suffix := '_backup_20251127'
);

-- Result:
-- 1. acme_production -> acme_production_backup_20251127
-- 2. acme_production_a1b2c3d4e5f6 -> acme_production
```

---

## Orphan Detection

Staging databases become orphans when:
1. Worker crashes mid-restore
2. Job is cancelled but cleanup fails
3. User abandons restore without completion

### Detection Query

```sql
-- Find staging databases with no active job
SELECT 
    staging_name,
    j.job_id,
    j.status,
    j.updated_at,
    TIMESTAMPDIFF(DAY, j.updated_at, NOW()) AS days_stale
FROM jobs j
JOIN db_hosts h ON j.dbhost_id = h.host_id
WHERE j.staging_name IS NOT NULL
  AND j.status IN ('failed', 'cancelled')
  AND TIMESTAMPDIFF(DAY, j.updated_at, NOW()) > 7;
```

### Cleanup Protocol

```python
def cleanup_orphan_staging(
    connection: MySQLConnection,
    staging_name: str,
    job_id: str,
    *,
    dry_run: bool = False,
) -> bool:
    """Remove orphaned staging database.
    
    Safety checks:
    1. Verify no active job references this staging DB
    2. Verify staging DB age > configured threshold (default 7 days)
    3. Log audit entry before deletion
    
    Args:
        connection: MySQL connection to target host
        staging_name: Staging database to remove
        job_id: Original job ID (for audit)
        dry_run: If True, only log what would be deleted
        
    Returns:
        True if deleted (or would be deleted in dry_run)
    """
    # Safety check: verify no active job
    if has_active_job(staging_name):
        logger.warning(
            "orphan_cleanup_skipped",
            staging_name=staging_name,
            reason="active_job_exists",
        )
        return False
    
    if dry_run:
        logger.info("orphan_cleanup_dry_run", staging_name=staging_name)
        return True
    
    cursor = connection.cursor()
    cursor.execute(f"DROP DATABASE IF EXISTS `{staging_name}`")
    
    logger.info(
        "orphan_cleanup_complete",
        staging_name=staging_name,
        original_job_id=job_id,
    )
    return True
```

---

## Failure Cleanup

When restore fails at any phase, staging must be cleaned up:

```python
def cleanup_staging_on_failure(
    connection: MySQLConnection,
    staging_name: str,
    job_id: str,
    phase: str,
    error: Exception,
) -> None:
    """Clean up staging database after restore failure.
    
    Always attempts cleanup, logs but doesn't raise on cleanup failure.
    """
    logger.error(
        "restore_failed_cleanup_started",
        job_id=job_id,
        staging_name=staging_name,
        phase=phase,
        error=str(error),
    )
    
    try:
        cursor = connection.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{staging_name}`")
        logger.info("staging_cleanup_complete", staging_name=staging_name)
    except MySQLError as cleanup_error:
        # Log but don't raise - original error is more important
        logger.error(
            "staging_cleanup_failed",
            staging_name=staging_name,
            cleanup_error=str(cleanup_error),
        )
```

---

## Automatic Cleanup

Staging database cleanup is implemented as functions in `pulldb/worker/cleanup.py` and `pulldb/worker/staging.py`:

### During Restore (`cleanup_orphaned_staging`)

Before each restore, orphaned staging databases matching the target pattern are automatically dropped:

```python
# pulldb/worker/staging.py
from pulldb.worker.staging import cleanup_orphaned_staging

# Called during restore workflow
staging_result = cleanup_orphaned_staging(
    mysql=mysql_client,
    target=job.target,
    current_staging=job.staging_name,
)
# Returns: StagingCleanupResult with dropped_count, errors
```

### Admin-Initiated Cleanup (`cleanup_host_staging`)

Administrators can trigger manual cleanup via CLI or Web UI:

```bash
# CLI: Preview and optionally clean
pulldb-admin cleanup staging --host dev-db-01 --dry-run
pulldb-admin cleanup staging --host dev-db-01 --force
```

```python
# API: pulldb/worker/cleanup.py
from pulldb.worker.cleanup import cleanup_host_staging

result = cleanup_host_staging(
    mysql=mysql_client,
    host_id=host.id,
    dry_run=False,
    age_threshold_days=7,  # From settings.staging_retention_days
)
```

---

## Related

- [engineering-dna/standards/database.md](../../engineering-dna/standards/database.md) - Base database patterns
- [.pulldb/standards/myloader.md](myloader.md) - Restore execution
- [.pulldb/standards/post-sql.md](post-sql.md) - Post-restore SQL
- [docs/mysql-schema.md](../../docs/mysql-schema.md) - Schema definition
