# Database Protection Audit Report

**Date:** 2025-01-28  
**Scope:** Comprehensive audit of ALL database destruction vectors in pullDB  
**Standard:** Maximum protection for existing databases  

---

## Executive Summary

### Status: ✅ STRONG (with previous fixes in place)

The pullDB codebase implements **defense-in-depth** protection for databases with multiple independent layers. The recent fixes (Phase 1) addressed critical vulnerabilities where `overwrite=false` bypassed external database checks. This audit confirms the fixes are complete and documents all remaining destruction vectors.

---

## Protection Layers Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        LAYER 1: API ENQUEUE CHECK                          │
│  pulldb/api/logic.py::enqueue_job()                                        │
│  ✅ Blocks external DBs (no pullDB table)                                  │
│  ✅ Blocks cross-user DBs (owner_mismatch)                                 │
│  ✅ Blocks exists-without-overwrite                                        │
│  ✅ Fails HARD on connection error (503)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                     LAYER 2: WORKER PRE-FLIGHT CHECK                       │
│  pulldb/worker/executor.py::pre_flight_verify_target_overwrite_safe()      │
│  ✅ Defense-in-depth (redundant to Layer 1)                                │
│  ✅ Runs ALWAYS regardless of overwrite setting                            │
│  ✅ Fails HARD on connection error (TargetCollisionError)                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                    LAYER 3: STORED PROCEDURE CHECK                         │
│  pulldb_atomic_rename (Version 1.0.2)                                      │
│  ✅ Verifies pullDB table exists before DROP target                        │
│  ✅ REFUSES to overwrite if no pullDB table found                          │
│  ✅ SIGNAL error preserved for audit                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                    LAYER 4: PROTECTED DATABASE LIST                        │
│  pulldb/worker/cleanup.py::PROTECTED_DATABASES                             │
│  ✅ Hardcoded frozenset: mysql, information_schema, performance_schema,    │
│     sys, pulldb, pulldb_service                                            │
│  ✅ HARD BLOCK in ALL drop functions                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                     LAYER 5: STAGING NAME VALIDATION                       │
│  pulldb/worker/cleanup.py::is_valid_staging_name()                         │
│  ✅ Validates {target}_[0-9a-f]{12} pattern                                │
│  ✅ HARD BLOCK in _drop_database()                                         │
│  ✅ Additional safety for orphan cleanup                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                       LAYER 6: OWNERSHIP VERIFICATION                      │
│  pulldb/worker/staging.py::_has_pulldb_table()                             │
│  ✅ Only drops if pullDB metadata table exists                             │
│  ✅ Fail-safe: returns False on error (don't drop)                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## All Database Destruction Vectors

### 1. Job Restore Flow (Target Database Overwrite)

**File:** [pulldb/api/logic.py](pulldb/api/logic.py)  
**Function:** `enqueue_job()` → `_target_database_exists_on_host()`

| Check | Status | Line(s) |
|-------|--------|---------|
| External DB check (no pullDB table) | ✅ BLOCKS | ~728-747 |
| Cross-user DB check (owner mismatch) | ✅ BLOCKS | ~757-773 |
| Exists without overwrite consent | ✅ BLOCKS | ~775-790 |
| Connection error handling | ✅ FAILS HARD (503) | ~700-710 |

**Critical Fix Applied (Phase 1):**
- External DB check now runs REGARDLESS of `overwrite` setting
- Connection errors raise HTTPException instead of returning False

---

### 2. Worker Pre-flight (Defense-in-Depth)

**File:** [pulldb/worker/executor.py](pulldb/worker/executor.py)  
**Function:** `pre_flight_verify_target_overwrite_safe()`

| Check | Status | Line(s) |
|-------|--------|---------|
| External DB check | ✅ BLOCKS | ~190-210 |
| Runs when overwrite=false | ✅ ALWAYS RUNS | ~130-145 |
| Connection error handling | ✅ RAISES TargetCollisionError | ~155-165 |

**Critical Fix Applied (Phase 1):**
- Removed early return when `overwrite=false`
- Connection errors raise `TargetCollisionError` instead of returning True

---

### 3. Atomic Rename Procedure (Final Gate)

**File:** [docs/hca/features/atomic_rename_procedure.sql](docs/hca/features/atomic_rename_procedure.sql)  
**Procedure:** `pulldb_atomic_rename` (Version 1.0.2)

| Check | Status | SQL Line(s) |
|-------|--------|-------------|
| Target exists check | ✅ CHECKS | ~92-96 |
| pullDB table ownership | ✅ VERIFIES | ~98-102 |
| Refuses non-pullDB target | ✅ SIGNALS ERROR | ~104-107 |
| Only drops owned targets | ✅ DROPS SAFELY | ~110-116 |

**Contract:**
```sql
IF v_has_pulldb_table = 0 THEN
    SET v_msg = CONCAT('Target database ', p_target_db, 
        ' exists but has no pullDB table - not created by pullDB, refusing to overwrite');
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
END IF;
```

---

### 4. Admin Task: Force Delete User

**File:** [pulldb/worker/admin_tasks.py](pulldb/worker/admin_tasks.py)  
**Function:** `_drop_target_database()`

| Check | Status | Line(s) |
|-------|--------|---------|
| Protected databases check | ✅ HARD BLOCK | ~421-426 |
| pullDB table ownership | ✅ VERIFIES | ~432-439 |
| User code in name check | ✅ VALIDATES | ~244-266 |
| Audit logging | ✅ LOGGED | Throughout |

**Contract:** Database MUST have pullDB table to be dropped.

---

### 5. Admin Task: Bulk Delete Jobs

**File:** [pulldb/worker/admin_tasks.py](pulldb/worker/admin_tasks.py)  
**Function:** `_execute_bulk_delete_jobs()`

| Check | Status | Line(s) |
|-------|--------|---------|
| Delegates to `delete_job_databases()` | ✅ USES PROTECTED FUNCTION | ~908-920 |
| Skip superseded jobs (no DBs owned) | ✅ SKIPS | ~890-905 |
| Audit logging | ✅ LOGGED | Throughout |

---

### 6. User-Initiated Job Deletion

**File:** [pulldb/worker/cleanup.py](pulldb/worker/cleanup.py)  
**Function:** `delete_job_databases()`

| Check | Status | Line(s) |
|-------|--------|---------|
| Protected database check | ✅ BLOCKS | ~820-830 |
| Target protection check | ✅ CALLS `is_target_database_protected()` | ~840-855 |
| User code validation | ✅ VALIDATES | ~858-875 |
| Fail-safe on exception | ✅ FAIL-SAFE | ~910-920 |
| pullDB table for custom_target | ✅ REQUIRES | ~860-875 |

---

### 7. Staging Orphan Cleanup

**File:** [pulldb/worker/staging.py](pulldb/worker/staging.py)  
**Function:** `cleanup_orphaned_staging()`

| Check | Status | Line(s) |
|-------|--------|---------|
| Staging pattern validation | ✅ VALIDATES | ~273-280 |
| pullDB table ownership check | ✅ REQUIRES | ~315-328 |
| Skip if no pullDB table | ✅ SKIPS | ~315-328 |
| Skip if active connections | ✅ SKIPS | ~298-310 |

**Fail-Safe:** If `_has_pulldb_table()` throws, returns `False` → don't drop.

---

### 8. Scheduled Retention Cleanup

**File:** [pulldb/worker/cleanup.py](pulldb/worker/cleanup.py)  
**Function:** `run_retention_cleanup()` → `_drop_database()`

| Check | Status | Line(s) |
|-------|--------|---------|
| Protected databases | ✅ HARD BLOCK | ~700-705 |
| Staging name pattern | ✅ VALIDATES | ~707-712 |
| Only staging DBs | ✅ ONLY STAGING | By design |

---

### 9. Admin Orphan Deletion

**File:** [pulldb/worker/cleanup.py](pulldb/worker/cleanup.py)  
**Function:** `admin_delete_orphan_databases()`

| Check | Status | Line(s) |
|-------|--------|---------|
| Staging pattern validation | ✅ VALIDATES | ~2067-2072 |
| Delegates to `_drop_database()` | ✅ USES PROTECTED FUNCTION | ~2083-2087 |
| Admin user logged | ✅ AUDIT TRAIL | ~2088 |

---

### 10. Target Protection Check (Single Source of Truth)

**File:** [pulldb/worker/cleanup.py](pulldb/worker/cleanup.py)  
**Function:** `is_target_database_protected()`

| Protection | Status | Logic |
|------------|--------|-------|
| Protected database list | ✅ BLOCKS | In `PROTECTED_DATABASES` frozenset |
| Deployed jobs | ✅ PROTECTS | Status='deployed' |
| Locked jobs | ✅ PROTECTS | `locked_at IS NOT NULL` |
| Returns `TargetProtectionResult` | ✅ DETAILED | Includes reason |

---

## Risk Assessment Matrix

| Vector | Severity | Protection Layers | Risk Level |
|--------|----------|-------------------|------------|
| Restore overwrite external DB | CRITICAL | 3 (API + Worker + Stored Proc) | ✅ LOW |
| Admin force delete | HIGH | 2 (pullDB table + audit) | ✅ LOW |
| Bulk delete jobs | HIGH | 2 (protection check + audit) | ✅ LOW |
| Staging orphan cleanup | MEDIUM | 2 (pullDB table + pattern) | ✅ LOW |
| Retention cleanup | MEDIUM | 2 (pattern + protected list) | ✅ LOW |
| Admin orphan deletion | HIGH | 2 (pattern + _drop_database) | ✅ LOW |

---

## Hardcoded Protected Databases

**Location:** `pulldb/worker/cleanup.py` line ~55

```python
PROTECTED_DATABASES = frozenset({
    "mysql",
    "information_schema",
    "performance_schema",
    "sys",
    "pulldb",
    "pulldb_service",
})
```

**Also duplicated in:** `pulldb/worker/admin_tasks.py` line ~86

⚠️ **RECOMMENDATION:** Consider centralizing to `pulldb/domain/constants.py`

---

## Error Types for Database Collisions

**Location:** `pulldb/domain/errors.py`

| Collision Type | Description | Response |
|----------------|-------------|----------|
| `external_db` | DB exists without pullDB table | HTTP 409 |
| `owner_mismatch` | DB owned by different user | HTTP 409 |
| `exists_no_overwrite` | DB exists, overwrite not consented | HTTP 409 |
| `connection_failed` | Cannot verify DB state | HTTP 503 |

---

## Critical Invariants

### Non-Negotiable Rules (from `.pulldb/standards/database-protection.md`)

1. **External databases are NEVER destroyed** - If a database exists without a `pullDB` metadata table, refuse to touch it
2. **Connection failures FAIL HARD** - Never proceed when database state cannot be verified
3. **Protected databases are HARDCODED** - mysql, information_schema, performance_schema, sys, pulldb, pulldb_service
4. **Three independent protection layers** - API, Worker, Stored Procedure each independently verify
5. **Audit everything** - All deletion operations logged with actor, timestamp, and target

---

## Potential Improvements (Future)

1. **Centralize PROTECTED_DATABASES** - Currently duplicated in cleanup.py and admin_tasks.py
2. **Add retention cleanup to audit log** - Currently logs to application logs, not audit_logs table
3. **Add circuit breaker for bulk deletes** - Stop if error rate exceeds threshold
4. **Add confirmation dialogs in Web UI** - Double-confirm before delete operations

---

## Test Coverage Summary

| Component | Test File | Key Tests |
|-----------|-----------|-----------|
| API Protection | `test_custom_target.py` | 56 tests including collision scenarios |
| Worker Pre-flight | `test_executor.py` | 30 tests including fail-hard behavior |
| Cleanup Functions | `test_cleanup.py` | Protection check tests |
| Admin Tasks | (TODO) | Admin delete scenarios |

---

## Conclusion

The pullDB codebase implements **robust multi-layer protection** for databases:

1. ✅ **Layer 1 (API):** Blocks at job queueing time
2. ✅ **Layer 2 (Worker):** Defense-in-depth pre-flight check
3. ✅ **Layer 3 (Stored Proc):** Final gate before DROP
4. ✅ **Layer 4 (Protected List):** Hardcoded sacred databases
5. ✅ **Layer 5 (Pattern):** Staging name validation
6. ✅ **Layer 6 (Ownership):** pullDB table verification

**The critical fixes from Phase 1 ensure that:**
- `overwrite=false` no longer bypasses any checks
- Connection errors fail HARD instead of silently proceeding
- External databases are NEVER destroyed

**Status: MAXIMUM PROTECTION ACHIEVED** ✅
