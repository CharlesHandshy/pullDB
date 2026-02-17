# Skip Database Drops Feature

**Status**: ✅ Fully Implemented and Deployed  
**Date**: 2025-01-28

## Overview

The `skip_database_drops` feature allows users to bypass database operations during job deletion when the target database host is known to be inaccessible (decommissioned, network failure, etc.).

## Use Cases

1. **Decommissioned hosts**: When a database server has been permanently removed
2. **Network failures**: When connectivity issues prevent database access
3. **Emergency cleanup**: When jobs need to be cleared quickly without waiting for host operations
4. **Test hosts**: When test environments are temporarily unavailable

## Implementation Stack

### UI Layer: [pulldb/web/templates/features/jobs/jobs.html](pulldb/web/templates/features/jobs/jobs.html)
- **Lines 81-86**: Checkbox in bulk delete modal
  ```html
  <input type="checkbox" id="bulk-delete-skip-drops" name="skip_database_drops">
  <span class="text-warning">⚠️ Skip database drops (use if hosts inaccessible)</span>
  <p class="text-muted">Marks jobs as deleted without verifying databases.</p>
  ```
- **Line 938**: JavaScript sends parameter in fetch body
  ```javascript
  skip_database_drops: document.getElementById('bulk-delete-skip-drops').checked
  ```

### Web Endpoint Layer: [pulldb/web/features/jobs/routes.py](pulldb/web/features/jobs/routes.py)
- **Lines 762-768**: Single delete endpoint parses form parameter
- **Lines 1147-1149**: Bulk delete endpoint parses JSON parameter
- **Line 1237**: Pass to `create_bulk_delete_task()`

### Repository Layer: [pulldb/infra/mysql_admin.py](pulldb/infra/mysql_admin.py)
- `create_bulk_delete_task()` method (AdminTaskRepository)
  - Added `skip_database_drops: bool = False` parameter
  - Stores in task parameters JSON

### Task Execution Layer: [pulldb/worker/admin_tasks.py](pulldb/worker/admin_tasks.py)
- **Line 668**: Parse from task parameters
  ```python
  skip_database_drops = params.get("skip_database_drops", False)
  ```
- **Line 858**: Pass to `delete_job_databases()`

### Core Logic Layer: [pulldb/worker/cleanup.py](pulldb/worker/cleanup.py)
- **Lines 576-631**: `delete_job_databases()` function
  - Added `skip_database_drops: bool = False` parameter
  - **Lines 610-631**: Early return when `skip_database_drops=True`
    ```python
    if skip_database_drops:
        logger.info(f"Skipping database drops for job {job_id} on host {dbhost}")
        result.staging_existed = False
        result.target_existed = False
        return result
    ```

## Behavior

### When `skip_database_drops=True`
1. No credential lookup attempted
2. No database connection attempted
3. No DROP DATABASE statements executed
4. Returns immediately with `staging_existed=False`, `target_existed=False`
5. Job marked as deleted in pulldb_service database
6. Event logged: "Database drops skipped (skip_database_drops=true)"

### When `skip_database_drops=False` (default)
1. Normal deletion flow with graceful degradation:
   - If host missing → immediate delete, no retry
   - If credentials missing → immediate delete, no retry
   - If connection fails → retry up to MAX_DELETE_RETRY_COUNT
   - If DROP fails → retry up to MAX_DELETE_RETRY_COUNT

## Testing Checklist

- [ ] Navigate to [http://localhost:8000/web/jobs](http://localhost:8000/web/jobs)
- [ ] Select jobs with inaccessible hosts
- [ ] Open bulk delete modal
- [ ] Verify checkbox appears with warning styling
- [ ] Check the "Skip database drops" checkbox
- [ ] Confirm deletion
- [ ] Verify jobs transition to "deleted" status
- [ ] Check job_events for skip audit log entry

## Related Documentation

- [.pulldb/FORCE-DELETE-UI-NOTES.md](.pulldb/FORCE-DELETE-UI-NOTES.md) - Full deletion feature overview
- [.pulldb/BUGFIX-DELETE-RETRY-LIMIT.md](.pulldb/BUGFIX-DELETE-RETRY-LIMIT.md) - State machine fixes
- [docs/mysql-schema.md](docs/mysql-schema.md) - Database schema and constraints

## Manual SQL Fallback

If needed, jobs can still be manually marked as deleted:
```sql
UPDATE jobs 
SET status = 'deleted',
    error_detail = 'Manually marked as deleted via skip_database_drops'
WHERE job_id = '<job_id>';
```

## Deployment

**Deployed**: 2025-01-28  
**Services**: All 5 services rebuilt and restarted
- pulldb-api (port 8080)
- pulldb-web (port 8000)
- pulldb-worker@1, pulldb-worker@2, pulldb-worker@3

**Deployment Command**: `./scripts/dev-rebuild.sh`
