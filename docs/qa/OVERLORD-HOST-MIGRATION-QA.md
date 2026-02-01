# QA Evaluation: Overlord Host Migration Feature

**Date**: 2026-02-01  
**Feature**: Safe Host Migration for Overlord Integration  
**Status**: Ready for QA

---

## Feature Summary

When a user changes the overlord database host to a different server, the system now requires cleaning up the old host before provisioning on the new one. This prevents orphaned MySQL users and AWS secrets.

---

## Additional Changes: Overlord Companies Modal

The following changes were made to the Overlord Companies modal:

### Changed Fields

| Field | Before | After |
|-------|--------|-------|
| **Subdomain** | Read-only display | **Editable text input** (required) |
| **Database Name** | Read-only display | Read-only display (unchanged) |
| **Primary Host (dbHost)** | Empty by default | **Auto-populated** from job's restore host |
| **Read Replica (dbHostRead)** | Empty by default | **Auto-populated** from job's restore host |

### Auto-Population Logic

- **Database Name**: Always set from `job.target` (the database being restored)
- **Primary Host**: If no existing value in overlord.companies, uses `job.dbhost` (the host where DB was restored)
- **Read Replica**: Same as Primary Host for initial population

---

## Files Changed

| File | Changes |
|------|---------|
| `pulldb/domain/services/overlord_provisioning.py` | Added `is_host_changing()`, `get_current_host()`, `cleanup_old_host()` methods |
| `pulldb/web/features/admin/routes.py` | Added `/overlord/check-host-change` and `/overlord/cleanup-old-host` endpoints |
| `pulldb/web/templates/features/admin/partials/_overlord_setup.html` | Added cleanup modal, modified `submitOverlordSetup()` flow |
| `pulldb/web/templates/partials/overlord_modal.html` | Made subdomain editable, auto-populate dbHost fields from job.dbhost |
| `pulldb/api/overlord.py` | Added `subdomain` to `OverlordSyncRequest` model and sync logic |

---

## Test Scenarios - Host Migration

### Scenario 1: First-Time Setup (No Host Change)

**Preconditions**: Overlord is not configured

**Steps**:
1. Navigate to Admin → Settings
2. Click "Setup Overlord Connection"
3. Enter host, database, table, and admin credentials
4. Click "Provision Access"

**Expected**: 
- No cleanup modal appears
- Provisioning proceeds directly
- Success toast and page reload

---

### Scenario 2: Reconfigure Same Host (No Host Change)

**Preconditions**: Overlord is already configured with `host-a.example.com`

**Steps**:
1. Click "Reconfigure" button
2. Keep the same host (`host-a.example.com`)
3. Change database or table name
4. Enter admin credentials
5. Click "Update Configuration"

**Expected**:
- No cleanup modal appears
- Provisioning proceeds directly (re-provisions on same host)

---

### Scenario 3: Host Change Detected - Successful Cleanup

**Preconditions**: Overlord is configured with `old-host.example.com`

**Steps**:
1. Click "Reconfigure" button
2. Change host to `new-host.example.com`
3. Enter admin credentials for the NEW host
4. Click "Provision Access"
5. **Cleanup modal should appear** showing:
   - Current Host: `old-host.example.com`
   - New Host: `new-host.example.com`
6. Enter admin credentials for the OLD host
7. Click "Clean Up Old Host"

**Expected**:
- Progress steps show:
  - ✓ Check Configuration
  - ✓ Test Old Host Connection
  - ✓ Drop MySQL User
  - ✓ Delete AWS Secret
  - ✓ Clear Settings
- Success toast: "Old host cleaned up successfully. Proceeding with new host setup..."
- Cleanup modal closes
- Setup modal reappears with provisioning progress
- New host is provisioned successfully

---

### Scenario 4: Host Change - Cleanup Fails (Bad Credentials)

**Preconditions**: Overlord is configured with `old-host.example.com`

**Steps**:
1. Click "Reconfigure" button
2. Change host to `new-host.example.com`
3. Click "Provision Access"
4. Cleanup modal appears
5. Enter **incorrect** admin credentials for old host
6. Click "Clean Up Old Host"

**Expected**:
- Progress steps show failure at "Test Old Host Connection"
- Error toast appears
- Button changes to "Retry Cleanup"
- User can correct credentials and retry
- **Provisioning is blocked** until cleanup succeeds

---

### Scenario 5: Host Change - Cannot Connect to Old Host

**Preconditions**: Overlord is configured with `old-host.example.com` but that server is now unreachable

**Steps**:
1. Click "Reconfigure" button
2. Change host to `new-host.example.com`
3. Click "Provision Access"
4. Cleanup modal appears
5. Enter correct admin credentials for old host
6. Click "Clean Up Old Host"

**Expected**:
- Progress steps show failure at "Test Old Host Connection" with network error
- Error message explains the connection failure
- Suggestions may include checking network connectivity

**Note for QA**: This is a valid edge case. If old host is permanently gone, user may need manual intervention (delete AWS secret manually, then provision fresh).

---

### Scenario 6: Cancel Cleanup Flow

**Steps**:
1. Trigger host change scenario
2. Cleanup modal appears
3. Click "Cancel" button

**Expected**:
- Cleanup modal closes
- Setup modal also closes (user is back to settings page)
- No changes made to old or new host
- Original configuration remains intact

---

### Scenario 7: Escape Key Closes Modals

**Steps**:
1. Trigger host change scenario
2. Cleanup modal appears
3. Press Escape key

**Expected**:
- Cleanup modal closes
- No changes made

---

### Scenario 8: Simulation Mode

**Preconditions**: Running in simulation mode (`PULLDB_SIMULATION_MODE=true`)

**Steps**:
1. Configure overlord in simulation mode
2. Change host to trigger cleanup flow
3. Complete cleanup

**Expected**:
- All steps show "(simulated)" suffix
- No actual MySQL or AWS operations occur
- Flow completes successfully

---

## API Endpoint Tests

### POST /web/admin/overlord/check-host-change

**Request**:
```
Content-Type: application/x-www-form-urlencoded

new_host=new-server.example.com
```

**Response (host is changing)**:
```json
{
  "is_changing": true,
  "current_host": "old-server.example.com",
  "new_host": "new-server.example.com"
}
```

**Response (host is same)**:
```json
{
  "is_changing": false,
  "current_host": "old-server.example.com",
  "new_host": "old-server.example.com"
}
```

**Response (first setup, no current host)**:
```json
{
  "is_changing": false,
  "current_host": null,
  "new_host": "new-server.example.com"
}
```

---

### POST /web/admin/overlord/cleanup-old-host

**Request**:
```
Content-Type: application/x-www-form-urlencoded

old_admin_username=admin
old_admin_password=secret123
```

**Response (success)**:
```json
{
  "success": true,
  "message": "Old host old-server.example.com cleaned up successfully",
  "steps": [
    {"name": "Check Configuration", "success": true, "message": "Found existing host: old-server.example.com"},
    {"name": "Test Old Host Connection", "success": true, "message": "Admin connection successful"},
    {"name": "Drop MySQL User", "success": true, "message": "User pulldb_overlord dropped"},
    {"name": "Delete AWS Secret", "success": true, "message": "Secret deleted"},
    {"name": "Clear Settings", "success": true, "message": "Settings cleared"}
  ]
}
```

**Response (failure)**:
```json
{
  "success": false,
  "message": "Failed to clean up old host",
  "error": "Access denied for admin user",
  "steps": [
    {"name": "Check Configuration", "success": true, "message": "Found existing host"},
    {"name": "Test Old Host Connection", "success": false, "message": "Access denied"}
  ],
  "suggestions": ["Verify admin credentials are correct", "Check user has DROP USER privilege"]
}
```

---

## UI/UX Verification

- [ ] Cleanup modal has warning styling (orange/yellow theme)
- [ ] Modal displays both current and new host clearly
- [ ] Bullet points explain what will be deleted
- [ ] Admin credential fields are labeled "Old Host Admin Credentials"
- [ ] Progress steps render correctly with ✓ / ✗ icons
- [ ] Button text updates: "Clean Up Old Host" → "Cleaning up..." → "Retry Cleanup" (on failure)
- [ ] Escape key closes modal
- [ ] Cancel button returns to settings page

---

## Regression Checks

- [ ] Existing provisioning flow works (no host change)
- [ ] Test connection button still works
- [ ] Rotate secret button still works
- [ ] Enable/Disable toggle still works
- [ ] Overlord Companies modal still loads data correctly

---

## Test Scenarios - Overlord Companies Modal

### Scenario A: New Database - Fields Auto-Populated

**Preconditions**: Job is deployed to `staging-db.example.com` with target `acme_db`, no existing overlord.companies record

**Steps**:
1. Open Overlord Companies modal for the job

**Expected**:
- **Status banner shows**: "**Create New Record** — No existing overlord.companies entry found. Fill in the details below to create one."
- Database Name shows `acme_db` (read-only)
- Subdomain is auto-populated with `acme_db` (editable)
- Primary Host (dbHost) is auto-populated with `staging-db.example.com`
- Read Replica (dbHostRead) is auto-populated with `staging-db.example.com`

---

### Scenario B: Existing Record - Subdomain Editable

**Preconditions**: overlord.companies has existing record with subdomain `acme`

**Steps**:
1. Open Overlord Companies modal
2. Verify subdomain shows `acme` in input field
3. Change subdomain to `acme-staging`
4. Save

**Expected**:
- Subdomain field is editable (not read-only)
- Change is saved successfully
- overlord.companies.subdomain is updated to `acme-staging`

---

### Scenario C: Subdomain Required

**Steps**:
1. Open Overlord Companies modal
2. Clear the subdomain field
3. Try to save

**Expected**:
- Form validation prevents submission
- "Subdomain is required" error shown

---

### Scenario D: Existing dbHost Not Overwritten

**Preconditions**: 
- Job restored to `staging-db.example.com`
- overlord.companies already has `dbHost = production-db.example.com`

**Steps**:
1. Open Overlord Companies modal

**Expected**:
- dbHost shows `production-db.example.com` (existing value preserved)
- NOT overwritten with `staging-db.example.com`

---

## Security Considerations

- [ ] Old host admin credentials are not logged
- [ ] Old host admin credentials are not stored
- [ ] Audit log entry is created for cleanup operation
- [ ] Endpoint requires admin authentication

---

## Notes for QA

1. **Test Environment Setup**: You'll need access to two different MySQL servers to properly test the host change flow.

2. **AWS Secrets Manager**: The cleanup deletes the secret `/pulldb/mysql/overlord`. Verify this in the AWS console after successful cleanup.

3. **MySQL User**: Verify `pulldb_overlord` user is removed from old host after cleanup:
   ```sql
   SELECT user, host FROM mysql.user WHERE user = 'pulldb_overlord';
   ```

4. **Partial Failure Recovery**: If cleanup partially succeeds (e.g., MySQL user dropped but AWS secret deletion fails), the system should handle retry gracefully.
