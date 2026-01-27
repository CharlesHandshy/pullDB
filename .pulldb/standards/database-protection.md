# Database Protection Standard

> **NON-NEGOTIABLE**: These safeguards protect existing databases from accidental destruction.  
> **REMOVAL REQUIRES**: Direct user acknowledgment + explicit documentation of accepted risk.

**Version**: 1.0.0 | **Created**: January 26, 2026  
**Classification**: CRITICAL SAFETY | **Compliance**: MANDATORY

---

## Executive Summary

pullDB's database protection system prevents **catastrophic data loss** from:
1. Overwriting external (non-pullDB) databases
2. Overwriting databases owned by other users
3. Overwriting databases without explicit user consent

**MAXIMUM REQUIREMENT**: Existing databases MUST be protected at ALL costs.

---

## Non-Negotiable Invariants

### Invariant 1: EXISTENCE CHECK BEFORE QUEUEING

**Rule**: Every job MUST verify target database existence BEFORE being queued.

```
┌─────────────────────────────────────────────────────────────────┐
│ BEFORE JOB IS QUEUED:                                           │
│                                                                 │
│ 1. Check if target database EXISTS on host                      │
│ 2. If EXISTS, check for pullDB metadata table                   │
│ 3. If NO pullDB table → BLOCK (external database)               │
│ 4. If pullDB table exists, check owner_user_id                  │
│ 5. If different owner → BLOCK (cross-user protection)           │
│ 6. If same owner + overwrite=false → BLOCK (require consent)    │
│ 7. If same owner + overwrite=true → ALLOW (explicit consent)    │
└─────────────────────────────────────────────────────────────────┘
```

### Invariant 2: NO SILENT FAILURES

**Rule**: Safety check failures MUST fail HARD, not degrade silently.

```python
# ❌ FORBIDDEN: Silent failure (fail-open)
except Exception:
    return False  # Proceeds as if database doesn't exist

# ✅ REQUIRED: Loud failure (fail-closed)  
except Exception:
    raise DatabaseProtectionError("Cannot verify target safety - operation blocked")
```

### Invariant 3: DEFENSE IN DEPTH

**Rule**: THREE INDEPENDENT layers of protection required:

| Layer | Location | When Checked | Cannot Bypass |
|-------|----------|--------------|---------------|
| **API** | `enqueue_job()` | Job submission | ✓ |
| **Worker** | `pre_flight_verify_target_overwrite_safe()` | Before download | ✓ |
| **Stored Procedure** | `pulldb_atomic_rename` | Before DROP | ✓ |

ALL THREE layers MUST block external database overwrites.

### Invariant 4: CHECK REGARDLESS OF OVERWRITE FLAG

**Rule**: External database checks MUST run regardless of `overwrite` setting.

```
overwrite=false + external DB exists → BLOCK (inform user)
overwrite=true  + external DB exists → BLOCK (protect external data)
```

The `overwrite` flag is **user consent to replace THEIR OWN pullDB data**, not permission to destroy external systems.

---

## Protected Entity Classification

### External Databases (NEVER OVERWRITE)

Definition: Database that exists but has NO `pullDB` metadata table.

**Protection Status**: 🔴 **ABSOLUTE BLOCK**

- No user setting can override this protection
- No admin flag can disable this check  
- Requires manual database removal before restore

### Cross-User Databases (NEVER OVERWRITE)

Definition: pullDB-managed database owned by a different `owner_user_id`.

**Protection Status**: 🔴 **ABSOLUTE BLOCK**

- User A cannot overwrite User B's database
- Even if User A has admin privileges
- Ownership is verified via `pullDB.owner_user_id` column

### Same-User Databases (CONDITIONAL)

Definition: pullDB-managed database owned by the requesting user.

**Protection Status**: 🟡 **REQUIRES EXPLICIT CONSENT**

- Default: BLOCKED (overwrite=false)
- With overwrite=true: ALLOWED (user consents to replace their own data)

---

## Implementation Requirements

### API Layer (enqueue_job)

**File**: `pulldb/api/logic.py`

```python
# MANDATORY: Check ALWAYS, not just when overwrite=true
if _target_database_exists_on_host(state, target, dbhost):
    has_pulldb, owner_id, owner_code = _get_pulldb_metadata_owner(state, target, dbhost)
    
    # CASE 1: External database - ABSOLUTE BLOCK
    if not has_pulldb:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Database '{target}' exists but is NOT pullDB-managed. "
                   f"This is an external database that cannot be overwritten. "
                   f"Choose a different target name."
        )
    
    # CASE 2: Different owner - ABSOLUTE BLOCK  
    if owner_id and owner_id != user.user_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Database '{target}' is owned by another user. "
                   f"Choose a different target name."
        )
    
    # CASE 3: Same owner, no overwrite - REQUIRE CONSENT
    if not req.overwrite:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Database '{target}' already exists. "
                   f"Enable 'Allow Overwrite' to replace it."
        )
    
    # CASE 4: Same owner + overwrite - PROCEED
```

### Connection Error Handling

**Rule**: FAIL HARD on connection errors, do not proceed.

```python
# ❌ FORBIDDEN
except Exception:
    logger.debug("Check failed, proceeding anyway")
    return False

# ✅ REQUIRED  
except Exception as e:
    logger.error("Database protection check failed: %s", e)
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Cannot verify database safety. Please try again."
    )
```

### Worker Layer (pre-flight)

**File**: `pulldb/worker/executor.py`

The worker pre-flight check MUST:
1. Run regardless of `overwrite` setting
2. Block external databases even when overwrite=false
3. Fail HARD on connection errors (do not proceed "with caution")

```python
def pre_flight_verify_target_overwrite_safe(job, credentials):
    """ALWAYS verify target is safe BEFORE expensive operations."""
    
    # Connect to MySQL - FAIL HARD if cannot
    try:
        conn = mysql.connector.connect(...)
    except mysql.connector.Error as e:
        raise TargetCollisionError(
            job_id=job.id,
            target=job.target,
            dbhost=job.dbhost,
            collision_type="connection_failed",
            error=str(e),
        )
    
    # Check if database exists
    cursor.execute("SHOW DATABASES LIKE %s", (job.target,))
    if cursor.fetchone() is None:
        return  # Safe - database doesn't exist
    
    # Database exists - MUST verify it's pullDB-managed
    cursor.execute(f"SHOW TABLES IN {quote_identifier(job.target)} LIKE 'pullDB'")
    has_pulldb_table = cursor.fetchone() is not None
    
    if not has_pulldb_table:
        # EXTERNAL DATABASE - ABSOLUTE BLOCK
        raise TargetCollisionError(
            job_id=job.id,
            target=job.target,
            dbhost=job.dbhost,
            collision_type="external_db",
        )
    
    # Check ownership (only needed if overwrite=true)
    if overwrite:
        # ... ownership check ...
```

### Stored Procedure (Last Resort)

**File**: `docs/hca/features/atomic_rename_procedure.sql`

The stored procedure is the FINAL safety net:

```sql
-- SAFETY: Only drop if target has pullDB table (ownership marker)
IF EXISTS (
    SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = p_target_db
) THEN
    SELECT COUNT(*) INTO v_has_pulldb_table
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = p_target_db AND TABLE_NAME = 'pullDB';

    IF v_has_pulldb_table = 0 THEN
        -- Target exists but has no pullDB table - refuse to drop
        SET v_msg = CONCAT('Target database ', p_target_db, 
            ' exists but has no pullDB table - refusing to overwrite');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
END IF;
```

---

## Removal Policy

### Requirements to Remove ANY Protection

These safeguards are **NON-NEGOTIABLE** and cannot be removed via:
- ❌ Configuration flags
- ❌ Environment variables  
- ❌ Admin commands
- ❌ Code changes without explicit documentation

### Authorized Removal Process

If business requirements ABSOLUTELY require modifying protection:

1. **Written Request**: Document the specific use case requiring removal
2. **Risk Assessment**: Detail the data loss scenarios that become possible
3. **User Acknowledgment**: Explicit sign-off on accepted risk
4. **Code Comment**: Reference the authorization in the code:

```python
# PROTECTION MODIFIED: Ticket PULL-XXX
# Authorized by: [Name], [Date]
# Risk accepted: [Description of accepted risk]
# Reversal plan: [How to restore protection]
```

5. **Audit Trail**: Log all operations that bypass protection

---

## Audit Checklist

### Mandatory Code Review Items

Before approving any change to `enqueue_job`, `pre_flight_verify_target_overwrite_safe`, or `pulldb_atomic_rename`:

- [ ] External database check runs ALWAYS (not conditional on overwrite)
- [ ] Connection errors fail HARD (not silent/open)
- [ ] All three protection layers preserved
- [ ] No new bypass paths introduced
- [ ] Tests cover external database blocking
- [ ] Tests cover cross-user blocking  
- [ ] Tests cover connection failure handling

### Test Requirements

```python
# REQUIRED test cases for database protection
def test_blocks_external_database_overwrite_false():
    """External DB blocked even when overwrite=false."""

def test_blocks_external_database_overwrite_true():
    """External DB blocked even when overwrite=true."""

def test_blocks_cross_user_database():
    """Cannot overwrite another user's database."""

def test_fails_hard_on_connection_error():
    """Connection errors block operation, not proceed."""

def test_worker_preflight_blocks_external():
    """Worker pre-flight catches external DBs."""

def test_stored_procedure_refuses_external():
    """Final safety net in stored procedure works."""
```

---

## Related Documents

- `.pulldb/standards/hca.md` - Hierarchical Containment Architecture
- `engineering-dna/protocols/fail-hard.md` - FAIL HARD protocol
- `docs/hca/features/atomic_rename_procedure.sql` - Stored procedure implementation
- `docs/CUSTOM-TARGET-NAME-PLAN.md` - Original protection design

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01-26 | Initial creation after critical safety audit |
