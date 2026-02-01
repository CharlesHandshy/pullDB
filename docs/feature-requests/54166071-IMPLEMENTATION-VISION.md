# Implementation Vision: Overlord Companies Integration

> **Feature Request**: `54166071`  
> **Document Type**: Engineering Vision & Safety Plan  
> **Created**: 2026-01-31  
> **Revision**: 2 - Updated with real-world constraints

---

## ⚠️ CRITICAL SAFETY DECLARATION

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   pullDB MUST NOT CAUSE DATA LOSS IN THE OVERLORD DATABASE                 │
│                                                                             │
│   The overlord.companies table is a PRODUCTION ROUTING TABLE that          │
│   controls which database hosts serve company data. Corruption or          │
│   incorrect deletion could break company access across the entire          │
│   system.                                                                   │
│                                                                             │
│   PRINCIPLE: "First, do no harm"                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚨 REAL-WORLD CONSTRAINTS

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ CONSTRAINT 1: CANNOT MODIFY overlord.companies SCHEMA                       │
│   • No ALTER TABLE                                                          │
│   • No adding tracking columns                                              │
│   • Schema is owned by overlord team, read-only for us                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ CONSTRAINT 2: CAN ADD/REMOVE ROWS (with proof of ownership)                │
│   • INSERT new rows for databases we manage                                 │
│   • UPDATE rows where database name matches our jobs                       │
│   • DELETE rows ONLY where database name is in our jobs table              │
├─────────────────────────────────────────────────────────────────────────────┤
│ CONSTRAINT 3: CAN CREATE TABLES IN pulldb_service DATABASE                 │
│   • Our tracking tables live in OUR database                               │
│   • Full control over our schema                                           │
│   • This is where we track state and audit                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Executive Summary

### What We're Building
A feature that allows pullDB users to manage `overlord.companies` rows when a database restore job is deployed, enabling the overlord routing system to direct traffic to the correct database host.

### Why It's Dangerous
- **overlord.companies** is a live production table
- Incorrect updates could route company traffic to wrong hosts
- Incorrect deletes could orphan companies (no routing = broken access)
- Some data in this table was NOT created by pullDB

### Our Safety Philosophy
```
TRACK LOCALLY → VERIFY OWNERSHIP → BACKUP FIRST → OPERATE SAFELY → LOG EVERYTHING
```

---

## 2. Safety Architecture

### 2.1 The Key Insight: Track State in OUR Database

Since we cannot add tracking columns to `overlord.companies`, we track everything in **our own table**:

```sql
-- In pulldb_service database (OUR database, full control)
CREATE TABLE overlord_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- What we're tracking
    database_name VARCHAR(50) NOT NULL UNIQUE,
    company_id INT NULL,  -- overlord.companies.companyID if row exists
    
    -- Ownership proof
    job_id VARCHAR(36) NOT NULL,
    job_target VARCHAR(255) NOT NULL,
    
    -- State tracking
    status ENUM('claimed', 'synced', 'released') NOT NULL DEFAULT 'claimed',
    
    -- Backup for restoration
    previous_dbhost VARCHAR(253) NULL,
    previous_dbhost_read VARCHAR(253) NULL,
    previous_snapshot JSON NULL,  -- Full row backup
    row_existed_before BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Current state (what we set)
    current_dbhost VARCHAR(253) NULL,
    current_dbhost_read VARCHAR(253) NULL,
    
    -- Audit
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    released_at DATETIME NULL,
    created_by VARCHAR(50) NOT NULL,
    
    -- Indexes
    INDEX idx_job_id (job_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 2.2 The Golden Rules

```python
# RULE 1: ALWAYS VERIFY OWNERSHIP BEFORE ANY OPERATION
# ────────────────────────────────────────────────────
# Before touching overlord.companies, verify the database exists in our jobs

def verify_ownership(database_name: str) -> Job:
    """Verify we have a deployed job for this database."""
    job = job_repository.find_deployed_by_target(database_name)
    if not job:
        raise OwnershipError(
            f"Cannot operate on '{database_name}' - no deployed job found"
        )
    return job
```

```python
# RULE 2: CHECK TRACKING TABLE BEFORE OPERATING
# ─────────────────────────────────────────────
# Our tracking table is the source of truth for what WE manage

def is_managed_by_us(database_name: str) -> bool:
    """Check if we're currently managing this database in overlord."""
    tracking = tracking_repository.get(database_name)
    return tracking is not None and tracking.status in ('claimed', 'synced')
```

```python
# RULE 3: BACKUP BEFORE MODIFY (in our tracking table)
# ───────────────────────────────────────────────────
# Before changing overlord, snapshot current state to our tracking table

def backup_current_state(database_name: str) -> dict:
    """Backup current overlord row to our tracking table."""
    current = overlord_repo.get_by_database(database_name)
    
    if current:
        tracking_repo.update(
            database_name=database_name,
            previous_dbhost=current['dbHost'],
            previous_dbhost_read=current['dbHostRead'],
            previous_snapshot=json.dumps(current),  # Full backup
            row_existed_before=True,
            company_id=current['companyID']
        )
    else:
        tracking_repo.update(
            database_name=database_name,
            row_existed_before=False
        )
    
    return current
```

```python
# RULE 4: DELETE ONLY ROWS WE CREATED
# ──────────────────────────────────
# If we created the row (row_existed_before=False), we can delete it
# If the row existed before, we RESTORE it instead of deleting

def release_overlord_row(database_name: str):
    """Release overlord row - restore or delete based on history."""
    tracking = tracking_repo.get(database_name)
    
    if not tracking:
        return  # Nothing to release
    
    if tracking.row_existed_before:
        # RESTORE the original values - don't delete!
        overlord_repo.update(
            database=database_name,
            dbHost=tracking.previous_dbhost,
            dbHostRead=tracking.previous_dbhost_read
        )
        audit_log("OVERLORD_RESTORE", database_name, tracking.previous_snapshot)
    else:
        # We created this row, safe to delete
        overlord_repo.delete(database=database_name)
        audit_log("OVERLORD_DELETE", database_name, None)
    
    # Mark as released in our tracking
    tracking_repo.update(database_name, status='released', released_at=now())
```

### 2.3 Operation Flow: Creating/Updating

```
User clicks "Manage Overlord" on deployed job
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 1. VERIFY OWNERSHIP                     │
│    SELECT * FROM jobs                   │
│    WHERE target = 'database_name'       │
│    AND status = 'DEPLOYED'              │
│    → Must return exactly 1 job          │
└─────────────────────────────────────────┘
                    │ Found
                    ▼
┌─────────────────────────────────────────┐
│ 2. CHECK/CREATE TRACKING RECORD         │
│    INSERT INTO overlord_tracking        │
│    (database_name, job_id, status, ...) │
│    ON DUPLICATE KEY UPDATE ...          │
│    → Creates claim in OUR database      │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 3. BACKUP CURRENT STATE                 │
│    SELECT * FROM overlord.companies     │
│    WHERE database = 'database_name'     │
│    → Store in tracking.previous_*       │
│    → Set row_existed_before flag        │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 4. SHOW MODAL WITH FORM                 │
│    Pre-fill with current values         │
│    User edits fields                    │
└─────────────────────────────────────────┘
                    │ Submit
                    ▼
┌─────────────────────────────────────────┐
│ 5. VALIDATE INPUT                       │
│    Sanitize strings                     │
│    Check lengths vs schema              │
│    Parameterized queries only           │
└─────────────────────────────────────────┘
                    │ Valid
                    ▼
┌─────────────────────────────────────────┐
│ 6. WRITE TO OVERLORD                    │
│    IF row exists:                       │
│      UPDATE companies SET ...           │
│      WHERE database = %s                │
│    ELSE:                                │
│      INSERT INTO companies ...          │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 7. UPDATE TRACKING & AUDIT              │
│    UPDATE overlord_tracking             │
│    SET status = 'synced',               │
│        current_dbhost = %s              │
│    INSERT INTO audit_logs ...           │
└─────────────────────────────────────────┘
```

### 2.4 Operation Flow: Release on Job Delete

```
Job deletion triggered
        │
        ▼
┌───────────────────────────────────────────┐
│ 1. CHECK TRACKING TABLE                   │
│    SELECT * FROM overlord_tracking        │
│    WHERE job_id = 'deleting_job_id'       │
│    AND status IN ('claimed', 'synced')    │
└───────────────────────────────────────────┘
        │
        ▼ Found tracking record?
        │
    ┌───┴───┐
    │ No    │ Yes
    │       │
    ▼       ▼
  Done  ┌───────────────────────────────────┐
        │ 2. CHECK row_existed_before       │
        └───────────────────────────────────┘
                │
        ┌───────┴───────┐
        │ TRUE          │ FALSE
        │               │
        ▼               ▼
┌──────────────┐  ┌──────────────┐
│ 3a. RESTORE  │  │ 3b. DELETE   │
│ UPDATE ...   │  │ DELETE FROM  │
│ SET dbHost = │  │ companies    │
│ previous_*   │  │ WHERE db=%s  │
└──────────────┘  └──────────────┘
        │               │
        └───────┬───────┘
                ▼
┌───────────────────────────────────────────┐
│ 4. UPDATE TRACKING                        │
│    UPDATE overlord_tracking               │
│    SET status = 'released'                │
└───────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────┐
│ 5. AUDIT LOG                              │
│    Record what we did (restore/delete)    │
└───────────────────────────────────────────┘
```

---

## 3. Threat Model

### 3.1 What Could Go Wrong

| Threat | Impact | Likelihood | Mitigation |
|--------|--------|------------|------------|
| Delete row we didn't create | **CRITICAL** | Medium | `row_existed_before` check |
| Update wrong company's dbHost | **CRITICAL** | Medium | Ownership verification via jobs table |
| SQL injection | **CRITICAL** | Low | Parameterized queries ONLY |
| Race condition: two jobs same target | **HIGH** | Medium | UNIQUE constraint in tracking table |
| Tracking table out of sync | **MEDIUM** | Medium | Sync verification on each operation |
| Delete row when job doesn't exist | **HIGH** | Low | Re-verify ownership before delete |

### 3.2 Extra Safety: Double-Check Before Delete

```python
def safe_delete_overlord_row(database_name: str, job_id: str):
    """Delete with maximum safety - verify everything twice."""
    
    # Check 1: Tracking record exists and we own it
    tracking = tracking_repo.get(database_name)
    if not tracking:
        raise SafetyError("No tracking record - cannot delete unknown row")
    
    if tracking.job_id != job_id:
        raise SafetyError(f"Job mismatch: tracking={tracking.job_id}, requested={job_id}")
    
    # Check 2: Row existed before we touched it?
    if tracking.row_existed_before:
        # RESTORE, don't delete
        logger.info(f"Restoring {database_name} to original state")
        overlord_repo.update(
            database=database_name,
            dbHost=tracking.previous_dbhost,
            dbHostRead=tracking.previous_dbhost_read
        )
    else:
        # We created it, verify it's really ours by checking if 
        # dbHost matches what we set (extra paranoia)
        current = overlord_repo.get_by_database(database_name)
        if current and current['dbHost'] != tracking.current_dbhost:
            raise SafetyError(
                f"dbHost mismatch - someone else modified this row! "
                f"Expected={tracking.current_dbhost}, "
                f"Actual={current['dbHost']}"
            )
        
        logger.info(f"Deleting {database_name} - row was created by pullDB")
        overlord_repo.delete(database=database_name)
    
    # Mark released
    tracking_repo.update(database_name, status='released')
```

---

## 4. Database Permissions

### 4.1 Service Account

```sql
-- Service account for pullDB (created by overlord DBA)
-- Note: We do NOT modify the schema, just data

GRANT SELECT, INSERT, UPDATE, DELETE ON overlord.companies TO 'pulldb_service'@'%';

-- That's it - no ALTER, no TRUNCATE, no DROP
-- DELETE is allowed because we track what we created
```

### 4.2 Our Tracking Table (in pulldb_service)

We have full control over our own database, so we create:
- `overlord_tracking` - tracks what we manage
- Uses `audit_logs` for change history

---

## 5. Testing Strategy

### 5.1 Unit Tests

```python
class TestOverlordTracking:
    """Test our tracking table logic."""
    
    def test_claim_creates_tracking_record(self, mock_tracking_repo):
        """Claiming a database creates local tracking."""
        manager = OverlordManager(mock_tracking_repo)
        manager.claim("test_db", job_id="job-123", user="testuser")
        
        mock_tracking_repo.create.assert_called_once()
    
    def test_cannot_claim_already_claimed(self, mock_tracking_repo):
        """Cannot claim database already claimed by another job."""
        mock_tracking_repo.get.return_value = {
            "database_name": "test_db",
            "job_id": "other-job",
            "status": "synced"
        }
        
        manager = OverlordManager(mock_tracking_repo)
        
        with pytest.raises(AlreadyClaimedError):
            manager.claim("test_db", job_id="job-123", user="testuser")
    
    def test_release_restores_if_row_existed(self, mock_tracking_repo, mock_overlord_repo):
        """Release restores original values if row existed before."""
        mock_tracking_repo.get.return_value = {
            "database_name": "test_db",
            "job_id": "job-123",
            "status": "synced",
            "row_existed_before": True,
            "previous_dbhost": "original.host.com"
        }
        
        manager = OverlordManager(mock_tracking_repo, mock_overlord_repo)
        manager.release("test_db", job_id="job-123")
        
        # Should UPDATE to restore, not DELETE
        mock_overlord_repo.update.assert_called_once()
        mock_overlord_repo.delete.assert_not_called()
    
    def test_release_deletes_if_we_created_row(self, mock_tracking_repo, mock_overlord_repo):
        """Release deletes row if we created it (row_existed_before=False)."""
        mock_tracking_repo.get.return_value = {
            "database_name": "test_db",
            "job_id": "job-123", 
            "status": "synced",
            "row_existed_before": False
        }
        
        manager = OverlordManager(mock_tracking_repo, mock_overlord_repo)
        manager.release("test_db", job_id="job-123")
        
        # Should DELETE since we created it
        mock_overlord_repo.delete.assert_called_once_with(database="test_db")
```

### 5.2 Integration Tests

```python
class TestOverlordIntegration:
    """Integration tests with real databases."""
    
    def test_full_lifecycle_new_row(self, pulldb_db, overlord_test_db):
        """Complete lifecycle when creating new overlord row."""
        # Setup: No existing overlord row
        assert overlord_test_db.get("new_company") is None
        
        # Create a deployed job in pulldb
        job = create_deployed_job(pulldb_db, target="new_company")
        
        # Claim + Sync
        manager = OverlordManager(pulldb_db, overlord_test_db)
        manager.claim("new_company", job.id, "testuser")
        manager.sync("new_company", {"dbHost": "new.host.com", "name": "New Company"})
        
        # Verify tracking: row_existed_before = False
        tracking = pulldb_db.get_tracking("new_company")
        assert tracking.row_existed_before == False
        
        # Release (should delete since we created it)
        manager.release("new_company", job.id)
        
        # Verify overlord row DELETED
        assert overlord_test_db.get("new_company") is None
    
    def test_full_lifecycle_existing_row(self, pulldb_db, overlord_test_db):
        """Complete lifecycle when overlord row already exists."""
        # Setup: Existing overlord row
        overlord_test_db.insert({
            "database": "existing_company",
            "dbHost": "original.host.com",
            "dbHostRead": "original-ro.host.com",
            "name": "Existing Company"
        })
        
        # Create deployed job
        job = create_deployed_job(pulldb_db, target="existing_company")
        
        # Claim + Sync
        manager = OverlordManager(pulldb_db, overlord_test_db)
        manager.claim("existing_company", job.id, "testuser")
        manager.sync("existing_company", {"dbHost": "new.host.com"})
        
        # Verify backup captured
        tracking = pulldb_db.get_tracking("existing_company")
        assert tracking.row_existed_before == True
        assert tracking.previous_dbhost == "original.host.com"
        
        # Release (should RESTORE since row existed)
        manager.release("existing_company", job.id)
        
        # Verify overlord row RESTORED (not deleted!)
        overlord_row = overlord_test_db.get("existing_company")
        assert overlord_row is not None
        assert overlord_row["dbHost"] == "original.host.com"  # RESTORED!
```

### 5.3 Safety Tests

```python
class TestOverlordSafety:
    """Tests that verify safety invariants."""
    
    def test_cannot_operate_without_deployed_job(self, manager):
        """Must have deployed job to operate on overlord."""
        with pytest.raises(OwnershipError):
            manager.claim("orphan_database", "fake-job", "user")
    
    def test_cannot_claim_others_database(self, manager, pulldb_db):
        """Cannot claim database already claimed by another job."""
        job_a = create_deployed_job(pulldb_db, target="company_x")
        manager.claim("company_x", job_a.id, "user_a")
        
        job_b = create_deployed_job(pulldb_db, target="company_x")
        
        with pytest.raises(AlreadyClaimedError):
            manager.claim("company_x", job_b.id, "user_b")
    
    def test_delete_verifies_ownership_twice(self, manager, overlord_test_db):
        """Delete operation double-checks everything."""
        # Setup tracking for row we "created"
        tracking = create_tracking(
            database_name="test_db",
            job_id="job-123",
            row_existed_before=False,
            current_dbhost="our.host.com"
        )
        
        # Sneaky: Someone else modified the overlord row
        overlord_test_db.update("test_db", dbHost="someone-elses.host.com")
        
        # Our delete should FAIL because dbHost doesn't match
        with pytest.raises(SafetyError) as exc:
            manager.release("test_db", "job-123")
        
        assert "mismatch" in str(exc.value)
        
        # Row should NOT be deleted
        assert overlord_test_db.get("test_db") is not None
```

---

## 6. Security Checklist

### 6.1 Pre-Implementation

- [ ] **Service account created** (`pulldb_service`) with SELECT/INSERT/UPDATE/DELETE on overlord.companies
- [ ] **Credentials stored in AWS Secrets Manager**
- [ ] **overlord_tracking table created** in pulldb_service database
- [ ] **Network access verified** (security groups)

### 6.2 Code Review Requirements

- [ ] **All queries parameterized** (no string interpolation)
- [ ] **Ownership verification** before every operation
- [ ] **Tracking table updated** before overlord modification
- [ ] **Backup captured** before modifying existing rows
- [ ] **row_existed_before check** before any delete
- [ ] **Audit logging** for every operation

---

## 7. Rollback Plan

### 7.1 If Something Goes Wrong

```sql
-- Find all rows pullDB is managing
SELECT * FROM pulldb_service.overlord_tracking
WHERE status IN ('claimed', 'synced');

-- Restore rows that existed before
UPDATE overlord.companies c
JOIN pulldb_service.overlord_tracking t 
  ON c.database = t.database_name
SET c.dbHost = t.previous_dbhost,
    c.dbHostRead = t.previous_dbhost_read
WHERE t.row_existed_before = TRUE
  AND t.status = 'synced';

-- Delete rows we created
DELETE c FROM overlord.companies c
JOIN pulldb_service.overlord_tracking t 
  ON c.database = t.database_name
WHERE t.row_existed_before = FALSE
  AND t.status = 'synced';

-- Mark all as released
UPDATE pulldb_service.overlord_tracking
SET status = 'released', released_at = NOW()
WHERE status IN ('claimed', 'synced');
```

### 7.2 Recovery Guarantees

Because we:
1. **Track everything in our table** - know exactly what we touched
2. **Record row_existed_before** - know whether to restore or delete
3. **Backup original values** - can always restore
4. **Log everything** - full audit trail

We can **always recover** to pre-pullDB state.

---

## 8. Implementation Phases

| Phase | Days | Risk | Description |
|-------|------|------|-------------|
| 1. Tracking Infrastructure | 2 | SAFE | Create `overlord_tracking` table, repository |
| 2. Read Operations | 1 | SAFE | Connect to overlord, display current state |
| 3. Claim Logic | 2 | LOW | Ownership verification, backup capture |
| 4. Sync Operations | 2 | MEDIUM | INSERT for new, UPDATE for existing |
| 5. Release Logic | 2 | MEDIUM | RESTORE vs DELETE based on history |
| 6. UI Integration | 2 | LOW | Modal form, HTMX routes |
| 7. Cleanup Hook | 1 | LOW | Auto-release on job delete |
| **Total** | **12** | - | - |

---

## 9. Open Questions

| # | Question | Status | Answer |
|---|----------|--------|--------|
| 1 | Can we modify overlord schema? | ✅ ANSWERED | **NO** - track in our DB instead |
| 2 | Can we delete overlord rows? | ✅ ANSWERED | **YES** - if we can prove ownership |
| 3 | Can we INSERT new rows? | ✅ ANSWERED | **YES** - for databases in our jobs |
| 4 | Do we have a `pulldb_service` database? | ❓ PENDING | Need to verify |
| 5 | Service account permissions? | ❓ PENDING | Need SELECT/INSERT/UPDATE/DELETE |

---

## 10. Sign-Off Required

- [ ] **Engineering Lead** - Architecture approved
- [ ] **Security Team** - Threat model reviewed  
- [ ] **DBA Team** - Permissions and access approved
- [ ] **Product Owner** - Requirements confirmed

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-01-31 | AI Team | Initial vision document |
| 2026-01-31 | AI Team | **Rev 2**: Updated with real constraints - no schema mods, track in our DB |
