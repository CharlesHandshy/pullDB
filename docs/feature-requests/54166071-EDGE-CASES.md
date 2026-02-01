# Overlord External Change Edge Cases

**Feature**: 54166071 - Button to update overlord.companies  
**Date**: 2026-01-31  
**Status**: ✅ High-Priority Mitigations Implemented

## Overview

The `overlord.companies` table is **not under pullDB's control**. External systems or manual DBA operations can modify it at any time. This document analyzes all edge cases and proposes defensive measures.

---

## Implementation Status

### ✅ Implemented (2026-01-31)

1. **ExternalStateCheck dataclass** - Tracks row_exists, dbhost_changed, current/expected values
2. **verify_external_state() method** - Pre-release verification of overlord row
3. **release() edge case handling**:
   - Row deleted externally → DELETE succeeds (no-op), RESTORE/CLEAR fails gracefully
   - dbHost changed externally → Warning logged, proceed for RESTORE/CLEAR
4. **affected_rows check** - _release_restore() and _release_clear() detect race conditions
5. **external_change_detected flag** - Added to ReleaseResult and audit logs
6. **New error classes** - OverlordExternalChangeError, OverlordRowDeletedError

### ⏳ Future Enhancements (Phase 2)

- UI warning banner when external changes detected
- "Refresh State" button in modal
- Schema change graceful degradation

---

## Edge Case Matrix

| # | Scenario | Current Behavior | Risk Level | Mitigation |
|---|----------|-----------------|------------|------------|
| 1 | Row deleted externally during claim | Claim succeeds (row_existed_before=false) | 🟡 Medium | Detect & warn |
| 2 | Row deleted externally after sync | ✅ **HANDLED** - Fails gracefully | 🔴 High | ✅ Verify before action |
| 3 | Row modified externally (dbHost changed) | ✅ **HANDLED** - Warning + proceed | 🟡 Medium | ✅ Detect and log |
| 4 | Row created externally for same database | We might claim thinking it's new | 🔴 High | Race condition check |
| 5 | companyID changes (row recreated) | Our snapshot references stale ID | 🟡 Medium | Re-fetch before release |
| 6 | Schema changes (column renamed/removed) | SQL errors, failures | 🔴 High | Graceful degradation |
| 7 | Overlord DB unreachable | Connection timeout | 🟡 Medium | Already has timeout handling |
| 8 | Row locked by external transaction | Timeout waiting for lock | 🟢 Low | MySQL handles this |
| 9 | Duplicate database entries | Wrong row modified | 🔴 High | Query by unique key |
| 10 | Data corruption in snapshot | Restore puts back garbage | 🟡 Medium | Validate snapshot format |

---

## Detailed Analysis

### Edge Case 1: Row Deleted Externally During Claim

**Scenario**: User clicks "Manage Overlord", we read the row, external process deletes it, we create tracking with `row_existed_before=true` but row is gone.

**Current Code**:
```python
# In claim():
current = self._overlord_repo.get_row_snapshot(database_name)
# ... time passes ...
self._tracking_repo.create(
    row_existed_before=current is not None,  # Stale!
    previous_dbhost=current.get("dbHost") if current else None,
)
```

**Problem**: We stored backup data for a row that no longer exists. On release with RESTORE, we'd try to UPDATE a non-existent row.

**Mitigation**: Add `verify_row_exists()` before restore/clear operations.

---

### Edge Case 2: Row Deleted Externally After Sync

**Scenario**: We sync successfully, row exists. External DBA deletes it. User tries to release.

**Current Code**:
```python
def _release_restore(self, database_name, tracking):
    self._overlord_repo.update(database_name, {...})  # No row to update!
```

**Problem**: UPDATE affects 0 rows, silently fails.

**Mitigation**: Check `affected_rows` after UPDATE, raise if 0.

---

### Edge Case 3: Row Modified Externally (dbHost Changed)

**Scenario**: We set `dbHost=staging.example.com`. External process changes it to `prod.example.com`. User releases.

**Current Code** (DELETE only):
```python
def _release_delete(self, database_name, tracking):
    if tracking.current_dbhost:
        current = self._overlord_repo.get_by_database(database_name)
        if current and current.db_host != tracking.current_dbhost:
            raise OverlordSafetyError("dbHost mismatch")
```

**Problem**: RESTORE and CLEAR don't check - they blindly overwrite.

**Mitigation**: Add same check to restore/clear with user confirmation option.

---

### Edge Case 4: Row Created Externally for Same Database

**Scenario**: Database "acme_prod" has no overlord row. External system creates one. User claims in pullDB.

**Current Code**:
```python
# In claim():
current = self._overlord_repo.get_row_snapshot(database_name)
self._tracking_repo.create(
    row_existed_before=current is not None,  # True - someone else created it
)
```

**Analysis**: Actually handled correctly! We'd back up their values. **No change needed.**

---

### Edge Case 5: companyID Changes (Row Recreated)

**Scenario**: Row deleted and recreated with new companyID. Our `company_id` in tracking is stale.

**Problem**: If we use company_id for queries, we'd reference wrong row.

**Current Code**: We query by `database` column, not `companyID`. **No change needed.**

---

### Edge Case 6: Schema Changes

**Scenario**: Overlord team renames `dbHost` to `db_host` or removes column.

**Problem**: SQL errors, unhandled exceptions.

**Mitigation**: 
1. Wrap overlord operations in try/catch
2. Log schema errors distinctly
3. Provide graceful degradation (disable feature vs crash)

---

### Edge Case 7: Overlord DB Unreachable

**Already Handled**: `OverlordConnection` has timeouts. Operations will fail with clear error.

---

### Edge Case 8: Row Locked by External Transaction

**Already Handled**: MySQL will timeout/wait based on `innodb_lock_wait_timeout`.

---

### Edge Case 9: Duplicate Database Entries

**Question**: Can `database` column have duplicates in overlord.companies?

**Schema Check Needed**: If `database` is not UNIQUE, we could modify wrong row.

**Mitigation**: Query by both `database` AND `companyID` (if known).

---

### Edge Case 10: Data Corruption in Snapshot

**Scenario**: JSON serialization of snapshot fails or produces invalid data.

**Mitigation**: Validate snapshot can be deserialized before storing.

---

## Recommended Code Changes

### 1. Add `OverlordStateChange` Detection

```python
@dataclass
class OverlordStateCheck:
    """Result of checking if external state changed."""
    row_exists: bool
    dbhost_changed: bool
    current_dbhost: str | None
    expected_dbhost: str | None
    
def verify_state_unchanged(self, database_name: str, tracking: OverlordTracking) -> OverlordStateCheck:
    """Verify overlord row hasn't been modified externally."""
    current = self._overlord_repo.get_by_database(database_name)
    
    return OverlordStateCheck(
        row_exists=current is not None,
        dbhost_changed=(
            current is not None 
            and tracking.current_dbhost is not None
            and current.db_host != tracking.current_dbhost
        ),
        current_dbhost=current.db_host if current else None,
        expected_dbhost=tracking.current_dbhost,
    )
```

### 2. Add Affected Rows Check to Repository

```python
def update(self, database_name: str, data: dict[str, Any]) -> int:
    """Update overlord row. Returns affected row count."""
    # ... execute UPDATE ...
    affected = cursor.rowcount
    if affected == 0:
        logger.warning(f"UPDATE affected 0 rows for database={database_name}")
    return affected
```

### 3. Add Pre-Release Verification

```python
def release(self, database_name, job_id, action) -> ReleaseResult:
    # ... existing ownership checks ...
    
    # NEW: Verify external state before release
    state = self.verify_state_unchanged(database_name, tracking)
    
    if not state.row_exists:
        if action == ReleaseAction.DELETE:
            # Row already gone - that's what we wanted
            return ReleaseResult(success=True, action_taken=action,
                message="Row already deleted externally")
        else:
            # Can't restore/clear a non-existent row
            return ReleaseResult(success=False, action_taken=action,
                message="Row no longer exists - cannot restore/clear")
    
    if state.dbhost_changed and action != ReleaseAction.DELETE:
        # Warn user about external modification
        logger.warning(f"External modification detected for {database_name}: "
                      f"expected={state.expected_dbhost}, found={state.current_dbhost}")
        # Proceed anyway for restore/clear (user explicitly chose this)
```

### 4. Add Schema Resilience

```python
def get_by_database(self, database_name: str) -> OverlordCompany | None:
    try:
        # ... existing query ...
    except mysql.connector.Error as e:
        if "Unknown column" in str(e):
            logger.error(f"Overlord schema changed - column missing: {e}")
            raise OverlordSchemaError("Overlord schema has changed") from e
        raise
```

### 5. Add Snapshot Validation

```python
def create(self, ..., previous_snapshot: dict | None = None, ...):
    # Validate snapshot is serializable
    if previous_snapshot:
        try:
            json.dumps(previous_snapshot)
        except (TypeError, ValueError) as e:
            logger.error(f"Cannot serialize snapshot: {e}")
            previous_snapshot = None  # Store without snapshot
```

---

## UI Implications

### Show Warning Banner When External Changes Detected

```html
<div class="alert alert-warning" x-show="externalChangeDetected">
    ⚠️ The overlord row has been modified externally since you claimed it.
    Current dbHost: <code x-text="currentDbHost"></code>
    Expected dbHost: <code x-text="expectedDbHost"></code>
    
    <button @click="proceedAnyway()">Proceed Anyway</button>
    <button @click="refreshState()">Refresh State</button>
</div>
```

### Add "Refresh" Button to Modal

Before any action, user can click "Refresh" to re-read current overlord state.

---

## Testing Recommendations

1. **Unit Test**: `test_release_when_row_deleted_externally`
2. **Unit Test**: `test_release_when_row_modified_externally`
3. **Unit Test**: `test_claim_race_condition`
4. **Integration Test**: Simulate external DELETE during sync
5. **Integration Test**: Simulate schema error handling

---

## Summary

| Priority | Change | Effort | Status |
|----------|--------|--------|--------|
| 🔴 High | Add row-exists check before restore/clear | Small | ✅ Implemented |
| 🔴 High | Return affected_rows from update | Small | ✅ Implemented |
| 🟡 Medium | Add state verification before release | Medium | ✅ Implemented |
| 🟡 Medium | Wrap operations with schema error handling | Small | ⏳ Phase 2 |
| 🟢 Low | Add UI warning for external changes | Medium | ⏳ Phase 2 |
| 🟢 Low | Add "Refresh State" button | Small | ⏳ Phase 2 |

**Recommendation**: ~~Implement High priority items before shipping.~~ ✅ High priority items implemented.

## Test Coverage

29 unit tests covering edge cases:
- `test_release_restore_when_row_deleted_externally` - Row gone, RESTORE fails gracefully
- `test_release_clear_when_row_deleted_externally` - Row gone, CLEAR fails gracefully  
- `test_release_delete_when_row_deleted_externally` - Row gone, DELETE succeeds (no-op)
- `test_release_restore_when_dbhost_modified_externally` - dbHost changed, proceed with warning
- `test_release_update_fails_race_condition` - UPDATE returns 0 rows, fail gracefully
