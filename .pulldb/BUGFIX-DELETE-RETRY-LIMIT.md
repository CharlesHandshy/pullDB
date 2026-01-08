# Bug Fix: Delete Job Retry Limit Enforcement

## Summary
Fixed a regression where the graceful degradation feature for missing hosts bypassed the max retry limit check, allowing jobs to be marked as deleted even after exceeding MAX_DELETE_RETRY_COUNT.

## Timeline
- **2026-01-07**: Original graceful degradation code deployed (missing retry check)
- **2026-01-08 02:37:53**: Job picked up for attempt 6 after being marked failed at attempt 5
- **2026-01-08 12:53**: Bug fixed and deployed

## Root Cause
The graceful degradation code itself was correct - when a host is deleted from the system, there's no point retrying because the databases are inaccessible. The real bug was in the delete endpoints: both web and admin bulk delete allowed re-deletion of jobs already in `failed` status, causing `mark_job_deleting()` to increment retry_count beyond the max (5 → 6).

### Why Immediate "Deleted" Status is Correct
When `get_host_credentials_for_maintenance()` raises "Host not found":
- The host record has been deleted from `db_hosts` table
- No credentials available to access the databases
- Databases are either:
  - Already dropped (host decommissioned)
  - Inaccessible (no way to verify or drop them)
- **Retrying is pointless** - condition won't change

The graceful degradation immediately marks the job as deleted, which is the correct terminal state. The job owned databases we can no longer manage.

### Contributing Factors
1. **Delete endpoints don't block FAILED jobs**: Both web and admin bulk delete endpoints allowed re-deletion of jobs in `failed` status, causing `mark_job_deleting()` to increment retry_count beyond the max (5 → 6).
2. **Fresh started_at timestamp**: When a failed job was re-deleted, it got a fresh `started_at` timestamp, making it appear non-stale and bypassing the `claim_stale_deleting_job` query's filter.

## Fixes Applied

### 1. Primary Fix: Immediate Graceful Completion (No Retry) for Missing Hosts
**File**: `pulldb/worker/cleanup.py`
**Location**: `execute_delete_job()` function, lines 766-789

**Logic**: When host is not found, immediately mark job as deleted WITHOUT retrying:
- Host being deleted is a terminal condition
- No credentials means databases are inaccessible
- Retrying won't help - we'll never be able to access those databases
- Mark as deleted immediately so job reaches terminal state

**Code**:
```python
if "not found" in str(e):
    logger.warning(
        f"Host {job.dbhost} not found - marking job as deleted immediately (no retry needed)",
        extra={
            "job_id": job.id,
            "dbhost": job.dbhost,
            "retry_count": job.retry_count,
            "reason": "Host record deleted from system - databases inaccessible"
        }
    )
    detail = json.dumps({
        "reason": "host_not_found",
        "message": f"Host {job.dbhost} deleted from system - databases no longer managed",
        "retry_count": job.retry_count,
    })
    job_repo.append_job_event(job.id, "deleted", detail)
    job_repo.mark_job_deleted(
        job.id,
        f"Host no longer exists - databases inaccessible (marked deleted without verification)"
    )
    result.success = True
    result.databases_already_gone = True
    return result
```

### 2. Secondary Fix: Block Re-Deletion of FAILED Jobs (Web Endpoint)
**File**: `pulldb/web/features/jobs/routes.py`
**Location**: `delete_job_database()` function, after line 742

**Added**:
```python
# Block if delete already failed (exhausted retries)
if job.status == JobStatus.FAILED:
    return redirect_error("Delete failed after max retries - contact admin for manual cleanup")
```

### 3. Secondary Fix: Block Re-Deletion of FAILED/DELETING Jobs (Admin Bulk Delete)
**File**: `pulldb/worker/admin_tasks.py`
**Location**: `execute_bulk_delete_task()` function, after line 753

**Added**:
```python
# Skip jobs already deleting (worker will retry)
if job.status == JobStatus.DELETING:
    skipped_list.append({
        "job_id": job_id,
        "reason": "Delete already in progress - worker will retry automatically",
    })
    progress["processed"] += 1
    self.task_repo.update_task_result(task.task_id, result)
    continue

# Skip jobs that failed deletion (exhausted retries)
if job.status == JobStatus.FAILED:
    failed_list.append({
        "job_id": job_id,
        "error": "Delete failed after max retries - use force-complete-delete admin endpoint",
    })
    progress["errors"].append(f"{job_id[:12]}: delete failed (max retries)")
    self.task_repo.update_task_result(task.task_id, result)
    continue
```

## Manual Database Fix
For the stuck job (09bb6685-4311-4789-bdf3-a5f6351e31b8) with retry_count=6:
```sql
UPDATE jobs 
SET status='failed', 
    error_detail='Host test-localhost not found - max retries (5) exceeded' 
WHERE id='09bb6685-4311-4789-bdf3-a5f6351e31b8';
```

## Validation
- ✅ Graceful degradation: Host not found → immediate mark as deleted (no retry needed)
- ✅ Web endpoint blocks re-deletion of FAILED jobs
- ✅ Admin bulk delete blocks re-deletion of FAILED and DELETING jobs
- ✅ Stuck job manually marked as failed
- ✅ All services restarted and running (api, web, worker@{1,2,3})

## Lessons Learned
1. **Terminal conditions don't need retries**: When a prerequisite (host record) is permanently gone, immediate graceful completion is correct
2. **Delete endpoints need status validation**: FAILED and DELETING jobs should not be re-queued
3. **State machine integrity**: Preventing invalid state transitions (failed → deleting) is critical

## Related Issues
- Original issue: Jobs stuck in deleting when hosts deleted from system
- Original fix: Graceful degradation + split credentials (maintenance vs restore)
- This fix: Ensures graceful degradation respects retry limits

## Testing Recommendations
The graceful degradation logic (immediate delete when host missing) is correct and needs no retry logic. Test coverage should focus on:

```python
def test_host_not_found_marks_deleted_immediately(self, mock_job_repo, mock_host_repo, sample_deleting_job):
    """Test that jobs are marked deleted immediately when host not found (no retry needed)."""
    # Set any retry count - should not matter
    job_with_retries = replace(sample_deleting_job, retry_count=3)
    mock_host_repo.get_host_credentials_for_maintenance.side_effect = ValueError("Host 'test-host' not found")
    
    result = execute_delete_job(job_with_retries, mock_job_repo, mock_host_repo)
    
    assert result.success is True
    assert result.databases_already_gone is True
    mock_job_repo.mark_job_deleted.assert_called_once()
    mock_job_repo.mark_job_delete_failed.assert_not_called()
```
