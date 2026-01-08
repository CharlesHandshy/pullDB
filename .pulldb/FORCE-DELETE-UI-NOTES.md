# Force-Complete Delete & Skip Database Drops UI Integration

## Implemented

✅ **Backend endpoint**: `POST /web/admin/jobs/{job_id}/force-complete-delete`  
✅ **Graceful host handling** in deletion workflow  
✅ **Maintenance credentials** for disabled hosts  
✅ **Skip database drops flag** (`skip_database_drops` parameter) - **NEW**

## New Feature: Skip Database Drops (2026-01-08)

### Purpose
Allow deletion of jobs when the host is inaccessible or has been removed from the system.

### Backend Changes

**Function**: `delete_job_databases()` in `pulldb/worker/cleanup.py`
- **New parameter**: `skip_database_drops: bool = False`
- When `True`: Bypasses credential retrieval and all database operations
- Returns immediately with `staging_existed=False, target_existed=False`
- Allows job to reach terminal state without requiring host access

**Web Endpoint**: `pulldb/web/features/jobs/routes.py`
- Parses `skip_database_drops` form parameter  
- Passes flag to `delete_job_databases()`

### Use Cases
1. Host decommissioned (removed from `db_hosts` table)
2. Host unreachable (network/DNS issues)
3. Failed jobs where host is missing
4. Emergency cleanup when databases are already gone

### Manual Cleanup (Current Method)

```sql
-- Mark job as deleted without database verification
UPDATE jobs 
SET status='deleted', 
    error_detail='Host inaccessible - marked deleted without verification' 
WHERE id='<job-id>';

-- Add audit event
INSERT INTO job_events (job_id, event_type, detail, logged_at)
VALUES ('<job-id>', 'deleted', 
        '{"reason": "host_inaccessible", "method": "skip_database_drops"}',
        UTC_TIMESTAMP(6));
```

## UI Integration (Optional Enhancement)

### Add Skip Database Drops Checkbox (Job Details Delete Form)

```html
<!-- Add after hard_delete checkbox in delete form -->
<div class="form-control">
    <label class="label cursor-pointer">
        <span class="label-text">Skip Database Drops</span>
        <input type="checkbox" name="skip_database_drops" class="checkbox checkbox-warning">
    </label>
    <div class="text-sm text-base-content/60 mt-1">
        ⚠️ Use when host is inaccessible. Marks job as deleted without verifying databases.
    </div>
</div>
```

### Add Force-Complete Button (For Stuck Deleting Jobs)

**Location**: After the status badge display (around line 86)

### Code to Add
```html
{% if user.is_admin and job.status.value == 'deleting' and job.retry_count >= 3 %}
<div class="alert alert-warning mt-4">
    <p><strong>Job stuck in deleting status</strong> ({{ job.retry_count }} retries)</p>
    <p>Host may be unavailable. Admin can force-complete this deletion:</p>
    <button class="btn btn-sm btn-danger" 
            onclick="forceCompleteDelete('{{ job.id }}')"
            style="margin-top: 8px;">
        Force Complete Deletion
    </button>
</div>
{% endif %}
```

### JavaScript Handler
Add to the `<script>` section at the bottom of details.html:

```javascript
async function forceCompleteDelete(jobId) {
    if (!confirm('Force-complete this deletion? The job will be marked deleted without verifying databases.')) {
        return;
    }
    
    try {
        const response = await fetch(`/web/admin/jobs/${jobId}/force-complete-delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.success) {
            alert(result.message);
            window.location.reload();
        } else {
            alert('Error: ' + result.message);
        }
    } catch (error) {
        alert('Request failed: ' + error.message);
    }
}
```

## Alternative: Use Directly

Admins can also force-complete via curl:

```bash
curl -X POST http://localhost:8000/web/admin/jobs/{job_id}/force-complete-delete \
  -H "Cookie: session=..." \
  -H "Content-Type: application/json"
```

## How It Works

1. **Automatic**: Deletion now handles missing/disabled hosts gracefully
2. **Manual**: Admin can force-complete stuck jobs via API or UI button
3. **Audit**: All force-completions logged with admin user and reason
