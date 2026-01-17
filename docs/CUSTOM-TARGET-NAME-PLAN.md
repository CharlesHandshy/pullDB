# Custom Target Database Name Feature Plan

> **Status**: Implementation (Core Complete)  
> **Created**: 2026-01-16  
> **Author**: Charles Handshy  
> **Last Audit**: 2026-01-16 (Fourth Pass)
> **Implementation**: 2026-01-16 (Core pipeline, Web UI, Safety checks)

## Overview

Allow users to specify a custom target database name instead of relying on the auto-generated `{user_code}{customer}{suffix}` pattern. This enables scenarios where users want shorter, more memorable database names while restoring from any backup.

### Example Use Case

User `charles` (user_code: `charle`) wants to restore customer `actionpest` but use a custom name:

```
Before (auto):  charle + actionpestcontrolservices = charleactionpestcontrolservices
After (custom): target=tanner     → tanner
After (custom): target=mytest     → mytest  
After (custom): target=prod       → prod
```

**Custom target = FULL USER CONTROL**:
- 1-51 lowercase letters (a-z)
- NO prefix requirement - user chooses any valid name
- Auto-generated targets STILL use `{user_code}{customer}{suffix}` pattern

### Ownership Model

**Target name does NOT declare ownership.**

Ownership is proven by (in order of authority):
1. **pullDB metadata table** (AUTHORITATIVE) - `owner_user_id`, `owner_user_code` in target database
2. **Job record** (if exists) - `owner_user_id` in jobs table

- External databases (no pullDB table) are NEVER deleted/overwritten
- Auto-generated targets: pullDB ownership + user_code-in-name check (belt-and-suspenders)
- Custom targets: pullDB ownership only (no name check)

![Target Configuration Screenshot](screenshots/target-config-custom-name.png)

---

## Audit Notes (2026-01-16 - Fourth Pass)

### ✅ What the Plan Gets Right

1. **Safety constraint identification** - Correctly identified critical safety invariants
2. **File inventory** - Identified most key files involved
3. **Length constraints** - 51 char max is correct (64 - 13 staging suffix)
4. **API-first approach** - Correct to modify API layer first
5. **Backward compatibility** - Custom target as optional field preserves existing behavior
6. **Pre-flight for ALL targets** - External DB protection applies to all overwrites, not just custom targets
7. **pullDB metadata as authoritative** - Master ownership record in target database

### ⚠️ Key Clarifications (Fourth Pass - FINAL)

1. **NO user_code prefix for custom targets** - User has FULL control (1-51 lowercase letters)
2. **Auto-generated STILL uses pattern** - `{user_code}{customer}{suffix}` unchanged for non-custom
3. **pullDB metadata = AUTHORITATIVE** - Master ownership record for all databases
4. **Target collision check** - Shows FULL username of owner for resolution
5. **Cleanup safety**: 
   - Auto-generated: pullDB ownership check + user_code-in-name (belt-and-suspenders)
   - Custom targets: pullDB ownership check only (no name check)
6. **Customer names blocked** - Uses existing customer search, checked BEFORE job queued
7. **Worker pre-flight** - Fails FAST (FAILED status) on collision, before any downloads
8. **Manager ownership** - Manager submits for user → user owns the database
9. **Customer change in UI** - Clears custom target edits (intentional)

### ✅ Resolved Items

1. **`_options_snapshot()` function** - Plan addresses storing `custom_target_used` in `options_json`
2. **`derive_backup_lookup_target()` in executor.py** - Uses `customer_id` from `options_json` as Priority 1
3. **Worker entry point** - Pre-flight check goes in `WorkerJobExecutor.execute()` at line ~410
4. **Job detail display** - Target name shown as normal, no special indicator needed
5. **CLI status output** - Same as normal, target displayed as-is

### ❌ All Major Issues Resolved

1. ~~S3 Backup Discovery Impact~~ - customer parameter required, stored in options_json ✅
2. ~~`JobResponse` schema~~ - Added `custom_target_used: bool` flag ✅
3. ~~Supersede/overwrite logic~~ - Works correctly with exact target match ✅
4. ~~Manager "submit as user" flow~~ - User owns database, manager just submits ✅
5. ~~QA template + custom target~~ - Allowed, works correctly ✅
6. ~~Target collision error~~ - Shows full username for resolution ✅
7. ~~Customer names as targets~~ - Blocked with validation ✅
8. ~~Orphan with removed user~~ - Cleaned up normally ✅

---

## Current Architecture

### Target Name Generation Flow

```
User selects customer → {user_code} + {sanitized_customer} + {suffix} = target
```

The target database name is computed server-side and cannot be customized by the user.

### Key Files Involved

| Layer | File | Responsibility | Audit Status |
|-------|------|----------------|--------------|
| **API Schema** | `pulldb/api/schemas.py` | `JobRequest` model | ✅ Verified |
| **API Logic** | `pulldb/api/logic.py:65-130` | `_construct_target()` - builds target | ✅ Verified |
| **API Logic** | `pulldb/api/logic.py:21-30` | `TargetResult` dataclass | ⚠️ Missing from plan |
| **API Logic** | `pulldb/api/logic.py:131-275` | `_options_snapshot()` - stores job params | ⚠️ Needs `custom_target` |
| **API Logic** | `pulldb/api/logic.py:281-294` | `validate_job_request()` - validates XOR | ✅ No change needed |
| **Web UI** | `pulldb/web/templates/features/restore/restore.html` | Target preview (read-only) | ✅ Verified |
| **JavaScript** | `pulldb/web/static/js/pages/restore.js:474-480` | `getUserCode()` - handles manager flow | ✅ Verified |
| **JavaScript** | `pulldb/web/static/js/pages/restore.js:503-527` | `updateTargetPreview()` | ✅ Verified |
| **Web Route** | `pulldb/web/features/restore/routes.py:281-490` | `restore_submit()` - builds JobRequest | ✅ Verified |
| **CLI Parse** | `pulldb/cli/parse.py` | `RestoreCLIOptions` dataclass, token parsing | ✅ Verified |
| **CLI Main** | `pulldb/cli/main.py:850-950` | `restore_cmd()` - builds API payload | ✅ Verified |
| **Domain** | `pulldb/domain/naming.py` | Customer name normalization | ✅ No change needed |
| **Models** | `pulldb/domain/models.py:211-280` | `Job` dataclass with `target` field | ✅ No change needed |
| **Cleanup** | `pulldb/worker/cleanup.py:724-730` | Safety validation for deletion | ✅ Verified critical |
| **Worker** | `pulldb/worker/executor.py:72-115` | `derive_backup_lookup_target()` | ⚠️ **CRITICAL** - see below |
| **Worker** | `pulldb/worker/executor.py:396-500` | `WorkerJobExecutor.execute()` - job entry | 🔄 **ADD pre-flight check** |
| **Staging** | `pulldb/worker/staging.py:86-130` | `generate_staging_name()` - length validation | ✅ Handles max 51 chars |
| **Tests** | `tests/qa/cli/test_restore.py:27` | Documents `target=` as NOT valid | ⚠️ Needs update |

---

## ⚠️ CRITICAL: Worker Backup Discovery Impact

**File**: `pulldb/worker/executor.py:72-115`  
**Function**: `derive_backup_lookup_target()`

This function extracts the customer name from the job to find S3 backups:

```python
def derive_backup_lookup_target(job: Job) -> str:
    """Return the canonical S3 target name for a job.
    
    Priority order:
    1. customer_id from options_json (cleanest source)
    2. is_qatemplate flag -> returns "qatemplate"
    3. Strip user_code prefix from target (legacy fallback)
    4. job.target as last resort
    """
```

**Impact Analysis**:
- ✅ **Priority 1 works**: If `customer_id` is in `options_json`, backup discovery works regardless of custom target
- ✅ **Priority 2 works**: QA template flag is independent of target name
- ⚠️ **Priority 3 FAILS**: If custom target doesn't follow `{user_code}{customer}` pattern, stripping user_code won't yield valid S3 path
- ⚠️ **Priority 4 FAILS**: Raw target (e.g., `charletanner`) won't match S3 path `actionpest/daily_mydumper_actionpest_*`

**SOLUTION**: The `customer` parameter MUST still be provided for backup discovery. Custom target only changes the destination database name, not the source backup lookup. This is already the case since `backup_path` or `customer` is required.

**Validation Required**: Ensure `options_json` always contains `customer_id` when custom_target is used.

### Data Flow Diagram (Customer vs Custom Target)

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           USER REQUEST                                     │
│  customer="actionpest"  +  custom_target="charletanner"                   │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                ┌───────────────────┴───────────────────┐
                │                                       │
                ▼                                       ▼
┌───────────────────────────┐           ┌───────────────────────────────────┐
│     Backup Discovery      │           │       Target Generation           │
│  (USES customer)          │           │  (USES custom_target)             │
├───────────────────────────┤           ├───────────────────────────────────┤
│ customer_id: "actionpest" │           │ target: "charletanner"            │
│ s3_path: .../actionpest/  │           │ staging: "charletanner_abc123..."│
│ backup: daily_mydumper_*  │           │                                   │
└───────────────────────────┘           └───────────────────────────────────┘
```

**Key Insight**: `customer` and `custom_target` serve different purposes:
- `customer` → S3 backup discovery (what to restore)
- `custom_target` → Database naming (where to restore)

---

## Safety Constraints (MUST PRESERVE)

### 1. Ownership Verification (UPDATED)

**Target name no longer declares ownership for custom targets.** Ownership is verified via pullDB metadata table.

**For Auto-Generated Targets**: pullDB ownership check + user_code-in-name (belt-and-suspenders)
**For Custom Targets**: pullDB ownership check only (no name pattern to check)

**Ownership is verified via** (in order of authority):
1. **pullDB metadata table** (AUTHORITATIVE) - query target database for `owner_user_code`
2. **Job record** (if exists) - `owner_user_id` matches requesting user

**Location**: `pulldb/worker/cleanup.py` - UPDATED

```python
def _verify_database_ownership(
    target: str, 
    dbhost: str, 
    requesting_user: User,
    is_custom_target: bool,
) -> bool:
    """Verify user owns the database.
    
    For ALL targets: pullDB metadata is AUTHORITATIVE.
    For auto-generated targets: ALSO check user_code in target name.
    """
    pulldb_info = _get_pulldb_metadata(creds, target)
    
    if pulldb_info is None:
        # No pullDB table = external database, NEVER allow deletion
        return False
    
    # Check 1: pullDB metadata ownership (AUTHORITATIVE for all)
    if pulldb_info.owner_user_code != requesting_user.user_code:
        return False
    
    # Check 2: For auto-generated targets, also verify user_code in name
    if not is_custom_target:
        if requesting_user.user_code not in target:
            return False
    
    return True
```

> ⚠️ **CRITICAL**: pullDB metadata table is AUTHORITATIVE. Auto-generated targets have additional user_code-in-name check.

### 1b. pullDB Metadata Table Ownership (AUTHORITATIVE)

**Problem**: For orphaned databases (no job record), we need a way to verify ownership before cleanup.

**Solution**: The `pullDB` metadata table is the AUTHORITATIVE ownership record:

```sql
-- UPDATED pullDB metadata table schema
CREATE TABLE IF NOT EXISTS `pullDB` (
    `job_id` VARCHAR(36) NOT NULL COMMENT 'UUID of restore job',
    `owner_user_id` CHAR(36) NOT NULL COMMENT 'UUID of database owner',      -- NEW
    `owner_user_code` CHAR(6) NOT NULL COMMENT '6-char owner identifier',    -- NEW
    `restored_by` VARCHAR(255) NOT NULL COMMENT 'Username who initiated restore',
    `restored_at` DATETIME(6) NOT NULL COMMENT 'UTC timestamp of restore completion',
    `target_database` VARCHAR(64) NOT NULL COMMENT 'Final target database name',
    `backup_filename` VARCHAR(512) NOT NULL COMMENT 'S3 backup filename used',
    `restore_duration_seconds` DECIMAL(10, 3) NOT NULL COMMENT 'Total restore duration',
    `custom_target` TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Whether custom target was used', -- NEW
    `post_sql_report` JSON NULL COMMENT 'Post-SQL execution status (JSON)',
    PRIMARY KEY (`job_id`),
    INDEX `idx_pulldb_owner` (`owner_user_id`),                               -- NEW
    INDEX `idx_pulldb_user_code` (`owner_user_code`)                          -- NEW
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='pullDB restore metadata - do not modify';
```

**Ownership Verification Order**:
1. **pullDB metadata** (AUTHORITATIVE): Query `owner_user_code` from target database's `pullDB` table
2. **Job record** (if exists): Check `owner_user_id` in jobs table
3. **No pullDB table**: Database is external - NEVER delete/overwrite

### 1c. Jobs Table Schema Update (NEW)

Add `custom_target` column to track whether a job used custom target naming:

```sql
-- Add to jobs table
ALTER TABLE jobs ADD COLUMN custom_target TINYINT(1) NOT NULL DEFAULT 0 
    COMMENT 'Whether custom target naming was used' AFTER options_json;
```

This enables:
- Fast queries for custom target jobs
- Audit trail without parsing options_json
- Cleanup logic can quickly identify custom targets

### 2. Per-Target Exclusivity

**Location**: MySQL schema `jobs` table

```sql
active_target_key VARCHAR(520) GENERATED ALWAYS AS (
    CASE WHEN status IN ('queued','running','canceling') 
    THEN CONCAT(target,'@@',dbhost) ELSE NULL END
) VIRTUAL,

CREATE UNIQUE INDEX idx_jobs_active_target ON jobs(active_target_key);
```

Only one active job per `target + dbhost` combination is allowed.

### 3. Lowercase Letters Only

**Location**: `pulldb/api/logic.py:116-123`

```python
if not target.isalpha() or not target.islower():
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail="Target database name must contain only lowercase letters (a-z)."
    )
```

### 4. Maximum Length: 51 Characters

**Rationale**: Staging name format is `{target}_{job_id[:12]}` which must not exceed MySQL's 64-character database name limit.

```
51 (target) + 1 (_) + 12 (job_id prefix) = 64 chars max
```

---

## Q&A: Custom Target Compatibility Analysis

### Q1: How Does This Work With User Ownership?

**Short Answer**: Custom target works seamlessly with ownership because **target name does NOT declare ownership**. Ownership is verified via pullDB metadata table (authoritative) or job record.

**Details**:

The `jobs` table stores ownership explicitly:
```sql
-- From pulldb/docs/hca/entities/mysql-schema.md
owner_user_id CHAR(36) NOT NULL,      -- User's UUID
owner_username VARCHAR(255) NOT NULL,  -- User's login name  
owner_user_code CHAR(6) NOT NULL,      -- 6-char identifier
```

**What the target name is used for**:
1. **Per-target exclusivity** (`active_target_key`): Prevents concurrent jobs to same database
2. **Human readability**: Users can identify their databases
3. **Database naming**: The actual MySQL database name

**What the target name is NOT used for**:
- ~~Ownership determination~~ (uses pullDB metadata table or job record)
- Job querying by user (uses `owner_username` index)
- Permission checks (uses `owner_user_id` vs `user.user_id`)

**Custom Target Impact**: ✅ **Works correctly** - ownership is via pullDB metadata or job record, not target name pattern.

**Code References**:
- Ownership queries: `pulldb/infra/mysql.py:2785-2910` (`get_deployed_job_for_target()` uses `owner_user_id` parameter)
- Job creation: `pulldb/api/logic.py:510-520` (stores `owner_user_id`, `owner_username`, `owner_user_code`)

---

### Q2: Cleanup Processes - How Do They Work With Custom Target?

**Short Answer**: Cleanup processes verify ownership via:
1. **pullDB metadata table** (AUTHORITATIVE) - `owner_user_code` in target database
2. **For auto-generated targets**: ALSO check user_code in target name (belt-and-suspenders)
3. **Job record** (if exists) - `owner_user_id` matches requesting user

**Ownership Verification** (`cleanup.py` - UPDATED):
```python
def _verify_database_ownership(
    target: str, 
    dbhost: str, 
    requesting_user: User,
    is_custom_target: bool,
) -> bool:
    """Verify user owns the database.
    
    Ownership proof:
    1. pullDB metadata table (AUTHORITATIVE for all)
    2. For auto-generated: user_code in target name (additional check)
    """
    # First: Check pullDB metadata table (AUTHORITATIVE)
    pulldb_info = _get_pulldb_metadata(creds, target)
    
    if pulldb_info is None:
        # No pullDB table = external database, NEVER allow deletion
        return False
    
    # pullDB metadata is authoritative for ownership
    if pulldb_info.owner_user_code != requesting_user.user_code:
        return False
    
    # For auto-generated targets: additional user_code-in-name check
    if not is_custom_target:
        if requesting_user.user_code not in target:
            return False
    
    return True
```

**Target Protection Check** (`cleanup.py:232-280`) - **UNCHANGED**:
```python
def is_target_database_protected(target, dbhost, job_repo):
    # 1. Check protected database list (mysql, sys, etc.)
    # 2. Check if ANY user has deployed job for this target
    # 3. Check if ANY user has locked job for this target
```
- ✅ **Works with custom target**: Uses exact target match, not pattern

**Cleanup Flow**:
```
delete_job_databases() / cleanup operations
    ├─► Verify ownership via pullDB metadata  ─────────► BLOCKS if no pullDB table
    ├─► Verify owner_user_code matches  ───────────────► BLOCKS if owner mismatch
    ├─► If auto-generated: verify user_code in name ──► BLOCKS if missing (belt-and-suspenders)
    ├─► is_target_database_protected()  ───────────────► BLOCKS if deployed/locked
    │       ├─► Check protected databases
    │       ├─► has_any_deployed_job_for_target()  ◄── Exact match on `target`
    │       └─► has_any_locked_job_for_target()    ◄── Exact match on `target`
    └─► Proceed to drop staging/target databases
```

**Custom Target Impact**: ✅ **Fully compatible** - ownership via pullDB metadata, not target name.

---

### Q3: What Other Areas Are Specifically Developed for `{user_code}{customer}{suffix}`?

Several areas assume this pattern. Here's the impact analysis:

| Area | Location | Pattern Usage | Custom Target Impact |
|------|----------|---------------|---------------------|
| **Backup Discovery** | `executor.py:103-112` | Strips `user_code` to find S3 path | ⚠️ **Fallback only** - uses `customer_id` from `options_json` first |
| **Staging Name** | `staging.py:85-130` | `{target}_{job_id[:12]}` | ✅ **Works** - uses target as-is |
| **Target Preview** | `restore.js:503-527` | `{userCode}{customer}{suffix}` | 🔄 **Needs update** - change to fully editable input |
| **CLI Validation** | `parse.py:15` | Validates total ≤ 51 chars | ✅ **Works** - validates final target length |
| **Customer Normalization** | `naming.py` | Truncates long customers | 🔄 **Bypassed** - custom target skips normalization |
| **Job Display** | `cli/main.py:298` | Shows target in status | ✅ **Works** - displays target as-is |
| **Per-Target Exclusivity** | `mysql-schema.md:213` | `CONCAT(target,'@@',dbhost)` | ✅ **Works** - uses exact target |
| **Overwrite Detection** | `logic.py:471-491` | Finds deployed by target | ✅ **Works** - exact match query |
| **Cleanup Validation** | `cleanup.py:723-730` | `user_code in target` | ✅ **KEPT for auto-generated** - removed only for custom targets |

**Detailed Analysis of Areas Needing Attention**:

#### 1. S3 Backup Discovery (executor.py:103-112) ⚠️
```python
# Priority 3: Strip user_code prefix from target (for legacy jobs without options)
user_code = job.owner_user_code or ""
target = job.target or ""
if user_code and target.startswith(user_code):
    remainder = target[len(user_code):]  # e.g., "tanner" from "charletanner"
    if remainder:
        return remainder  # Used for S3 path like "tanner/daily_mydumper_tanner_*"
```
**Impact**: If custom target is `charletest` but customer is `actionpest`, stripping gives `test` not `actionpest`.
**Mitigation**: This is **Priority 3 fallback**. Priority 1 (`customer_id` from `options_json`) is used for all new jobs. Plan already includes storing `customer_id`.

#### 2. Target Preview JavaScript (restore.js) 🔄
```javascript
function updateTargetPreview() {
    const target = `${userCode}${normalizedCustomer}${suffix}`;
    // Displays computed target - NOT editable
}
```
**Impact**: Currently read-only, computed from selection.
**Required Change**: Convert to editable input with user_code prefix locked.

#### 3. Customer Normalization (naming.py) 🔄
Long customer names (> 42 chars) get truncated + hash:
```
"actionpestcontrolservicesofsouthfloridainc" → "actionpestcontrolservices5a3b"
```
**Impact**: Custom target bypasses this - user is responsible for choosing a valid length.
**Benefit**: Users can choose shorter names without hash ugliness.

---

### Q4: How Are External Databases Protected From Accidental Overwrites?

**Problem Statement**: If a database `production` exists on the host (created externally, not by pullDB), and a user submits a custom target restore with `target=production` + `overwrite=true`, the external database could be destroyed.

**Current Protection (Being Updated)**:
1. `PROTECTED_DATABASES` - Only protects `mysql`, `sys`, `information_schema`, etc.
2. `user_code in target_name` - **KEPT for auto-generated**, removed for custom targets
3. Deployed/locked job check - External DB has no job record

**Solution: pullDB Metadata Table Fingerprint + Ownership Collision Check**

Every database restored by pullDB contains a `pullDB` metadata table (see `pulldb/worker/metadata.py`).

**New Safety Checks** (in order):

1. **Check if target exists on host**
2. **If exists, check for pullDB table** (is it pullDB-managed?)
3. **If pullDB table exists, check `owner_user_code`** (does current user own it?)
4. **If owner mismatch → REFUSE with error showing owner info**

```python
# In enqueue_job(), for custom targets:

if db_exists:
    if not has_pulldb_table:
        # External database - BLOCK
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"Database '{target}' exists but was not created by pullDB "
                f"(missing pullDB metadata table). Cannot overwrite external databases."
            ),
        )
    
    # Has pullDB table - check ownership
    pulldb_info = _get_pulldb_ownership(state, target, dbhost)
    if pulldb_info.owner_user_code != user.user_code:
        # Owned by different user - BLOCK with owner info
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"Database '{target}' exists and is owned by user '{pulldb_info.owner_user_code}'. "
                f"You cannot overwrite databases owned by other users."
            ),
        )
```

```sql
CREATE TABLE IF NOT EXISTS `pullDB` (
    `job_id` VARCHAR(36) NOT NULL COMMENT 'UUID of restore job',
    `restored_by` VARCHAR(255) NOT NULL COMMENT 'Username who initiated restore',
    `restored_at` DATETIME(6) NOT NULL COMMENT 'UTC timestamp of restore completion',
    `target_database` VARCHAR(64) NOT NULL COMMENT 'Final target database name',
    `backup_filename` VARCHAR(512) NOT NULL COMMENT 'S3 backup filename used',
    `restore_duration_seconds` DECIMAL(10, 3) NOT NULL COMMENT 'Total restore duration',
    `post_sql_report` JSON NULL COMMENT 'Post-SQL execution status (JSON)',
    PRIMARY KEY (`job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='pullDB restore metadata - do not modify';
```

**Proposed Safety Check** (NEW for Custom Target feature):

Before allowing overwrite when `custom_target` is provided:
1. Check if target database exists on the host
2. If exists, verify it contains the `pullDB` table
3. If `pullDB` table is missing → **BLOCK overwrite** with error:
   ```
   "Database 'charleproduction' exists but was not created by pullDB 
   (missing pullDB metadata table). Cannot overwrite external databases.
   Use a different target name or manually drop the database first."
   ```

**Implementation Location**: `pulldb/api/logic.py` in `enqueue_job()` function, after deployed job check (lines ~470-490).

```python
# NEW: Check for external database (only when overwrite + custom_target)
if req.overwrite and req.custom_target:
    if _target_database_exists(state, target, dbhost):
        if not _is_pulldb_managed_database(state, target, dbhost):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"Database '{target}' exists but was not created by pullDB "
                    f"(missing pullDB metadata table). Cannot overwrite external databases. "
                    f"Use a different target name or manually drop the database first."
                )
            )
```

**Helper Functions Needed**:
```python
def _target_database_exists(state: APIState, target: str, dbhost: str) -> bool:
    """Check if a database exists on the host."""
    # Use host_repo to get credentials, then SHOW DATABASES LIKE 'target'

def _is_pulldb_managed_database(state: APIState, target: str, dbhost: str) -> bool:
    """Check if a database has the pullDB metadata table."""
    # Query: SHOW TABLES IN `target` LIKE 'pullDB'

def _get_pulldb_ownership(state: APIState, target: str, dbhost: str) -> tuple[str, str] | None:
    """Get owner_user_id and owner_user_code from pullDB metadata table.
    
    Returns (owner_user_id, owner_user_code) or None if not found.
    Used for orphan cleanup verification.
    """
    # Query: SELECT owner_user_id, owner_user_code FROM `target`.pullDB LIMIT 1
```

**Why This Is Safe**:
- The `pullDB` table is injected by `metadata.py` into the **staging database** during restore
- When atomic rename happens (`staging → target`), the table moves with the database
- Any database that was ever restored by pullDB will have this fingerprint
- External databases will NOT have this table unless someone manually creates it
- **NEW**: Ownership info (`owner_user_id`, `owner_user_code`) in pullDB table enables orphan cleanup

**Edge Cases**:
| Scenario | Result |
|----------|--------|
| External DB, no `pullDB` table | ❌ BLOCKED |
| pullDB-restored DB, has `pullDB` table | ✅ Allowed (overwrite) |
| DB exists but user_code doesn't match | ❌ BLOCKED (existing check) |
| DB doesn't exist | ✅ Allowed (new restore) |
| Can't connect to check | ❌ BLOCKED (fail-closed) |
| Orphan DB with pullDB table | ✅ Can verify ownership via pullDB.owner_user_code |

---

## Metadata Table & Worker Updates

### 1. Update pullDB Metadata Table Schema

**File**: `pulldb/worker/metadata.py`

Add ownership columns to enable orphan cleanup:

```python
_CREATE_METADATA_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `pullDB` (
    `job_id` VARCHAR(36) NOT NULL COMMENT 'UUID of restore job',
    `owner_user_id` CHAR(36) NOT NULL COMMENT 'UUID of database owner',
    `owner_user_code` CHAR(6) NOT NULL COMMENT '6-char owner identifier',
    `restored_by` VARCHAR(255) NOT NULL COMMENT 'Username who initiated restore',
    `restored_at` DATETIME(6) NOT NULL COMMENT 'UTC timestamp of restore completion',
    `target_database` VARCHAR(64) NOT NULL COMMENT 'Final target database name',
    `backup_filename` VARCHAR(512) NOT NULL COMMENT 'S3 backup filename used',
    `restore_duration_seconds` DECIMAL(10, 3) NOT NULL COMMENT 'Total restore duration',
    `custom_target` TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Whether custom target was used',
    `post_sql_report` JSON NULL COMMENT 'Post-SQL execution status (JSON)',
    PRIMARY KEY (`job_id`),
    INDEX `idx_pulldb_owner` (`owner_user_id`),
    INDEX `idx_pulldb_user_code` (`owner_user_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='pullDB restore metadata - do not modify';
"""
```

### 2. Update MetadataSpec Dataclass

```python
@dataclass(slots=True, frozen=True)
class MetadataSpec:
    job_id: str
    owner_user_id: str       # NEW
    owner_user_code: str     # NEW
    owner_username: str
    target_db: str
    backup_filename: str
    restore_started_at: datetime
    restore_completed_at: datetime
    custom_target: bool      # NEW
    post_sql_result: PostSQLExecutionResult | None
```

### 3. Update inject_metadata_table() INSERT

```python
insert_sql = """
    INSERT INTO `pullDB` (
        job_id,
        owner_user_id,
        owner_user_code,
        restored_by,
        restored_at,
        target_database,
        backup_filename,
        restore_duration_seconds,
        custom_target,
        post_sql_report
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
cursor.execute(insert_sql, (
    metadata_spec.job_id,
    metadata_spec.owner_user_id,
    metadata_spec.owner_user_code,
    metadata_spec.owner_username,
    metadata_spec.restore_completed_at,
    metadata_spec.target_db,
    metadata_spec.backup_filename,
    restore_duration,
    1 if metadata_spec.custom_target else 0,
    post_sql_json,
))
```

---

## Admin Cleanup Script Updates

### 1. Orphan Database Detection (`cleanup.py` or admin scripts)

When finding orphaned databases (databases that exist but have no job record):

```python
def find_orphaned_databases(
    dbhost: str,
    host_repo: HostRepository,
    job_repo: JobRepository,
) -> list[OrphanedDatabase]:
    """Find databases that exist on host but have no job record.
    
    Uses pullDB metadata table to verify ownership before cleanup.
    """
    orphans = []
    creds = host_repo.get_host_credentials(dbhost)
    
    # Get all databases on host
    all_dbs = _list_databases(creds)
    
    for db_name in all_dbs:
        # Skip system databases
        if db_name in PROTECTED_DATABASES:
            continue
            
        # Check if job record exists
        has_job = job_repo.has_any_job_for_target(db_name, dbhost)
        
        if not has_job:
            # Orphan detected - check pullDB table for ownership
            pulldb_info = _get_pulldb_metadata(creds, db_name)
            
            orphans.append(OrphanedDatabase(
                target=db_name,
                dbhost=dbhost,
                has_pulldb_table=pulldb_info is not None,
                owner_user_code=pulldb_info.owner_user_code if pulldb_info else None,
                owner_user_id=pulldb_info.owner_user_id if pulldb_info else None,
                custom_target=pulldb_info.custom_target if pulldb_info else None,
                job_id=pulldb_info.job_id if pulldb_info else None,
            ))
    
    return orphans


def safe_drop_orphaned_database(
    orphan: OrphanedDatabase,
    requesting_user: User,
    host_repo: HostRepository,
) -> DropResult:
    """Safely drop an orphaned database with ownership verification.
    
    Safety checks:
    1. Must have pullDB table (proves pullDB-managed)
    2. Verify ownership via pullDB.owner_user_code
    3. For auto-generated targets: also check user_code in target name
    4. For custom targets: pullDB ownership is sufficient (no name check)
    5. If owner user no longer exists: allow cleanup (orphaned user)
    """
    # Check 1: Must have pullDB table (proves it's a pullDB-managed database)
    if not orphan.has_pulldb_table:
        return DropResult(
            success=False,
            error="Cannot drop: database has no pullDB metadata table (external database)",
        )
    
    # Check 2: Verify ownership via pullDB table
    # Special case: if owner user no longer exists, allow cleanup
    if orphan.owner_user_code is None:
        # Should never happen - ownership is always set on restore
        return DropResult(
            success=False,
            error="Cannot drop: pullDB table has no owner_user_code (corrupted metadata)",
        )
    
    if orphan.owner_user_code != requesting_user.user_code:
        # Check if owner user still exists - if not, allow admin cleanup
        # (handled separately by admin cleanup flow)
        return DropResult(
            success=False,
            error=(
                f"Cannot drop: pullDB table shows owner '{orphan.owner_user_code}' "
                f"but requesting user has code '{requesting_user.user_code}'"
            ),
        )
    
    # Check 3: For auto-generated targets, also verify user_code in name
    # For custom targets (pullDB.custom_target=1), skip this check
    if not orphan.custom_target:
        # Auto-generated target: belt-and-suspenders check
        if requesting_user.user_code not in orphan.target:
            return DropResult(
                success=False,
                error=(
                    f"Cannot drop: target '{orphan.target}' does not contain "
                    f"user code '{requesting_user.user_code}' (auto-generated target mismatch)"
                ),
            )
    # Custom targets: pullDB ownership check is sufficient
    
    # All checks passed - safe to drop
    creds = host_repo.get_host_credentials(orphan.dbhost)
    _drop_database(creds, orphan.target)
    
    return DropResult(success=True, dropped=orphan.target)
```

### 2. Admin Bulk Cleanup (scripts/admin_cleanup.py)

```python
def admin_cleanup_orphaned_databases(
    dbhost: str,
    dry_run: bool = True,
) -> CleanupReport:
    """Admin tool to find and clean up orphaned databases.
    
    For each orphan:
    - If has pullDB table: Show owner info for review
    - If no pullDB table: Flag as EXTERNAL (never auto-delete)
    """
    orphans = find_orphaned_databases(dbhost, host_repo, job_repo)
    
    report = CleanupReport()
    
    for orphan in orphans:
        if not orphan.has_pulldb_table:
            report.external_databases.append(orphan)
            logger.warning(
                f"EXTERNAL DATABASE: {orphan.target} on {dbhost} - "
                f"NO pullDB table, cannot verify ownership, SKIPPING"
            )
        else:
            report.pulldb_managed.append(orphan)
            logger.info(
                f"Orphan: {orphan.target} on {dbhost} - "
                f"Owner: {orphan.owner_user_code}, Job: {orphan.job_id}, "
                f"Custom target: {orphan.custom_target}"
            )
            
            if not dry_run:
                # Only drop if all safety checks pass
                # (in practice, admin may want manual review)
                pass
    
    return report
```

---

## Proposed Changes
### 0. **Pre-requisite: Understand the Data Flow** (ADDED)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ USER INPUT                                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  customer="actionpest"    →  Used for S3 backup discovery                   │
│  custom_target="charletanner"  →  Used for destination database name        │
│  backup_path="s3://..."   →  Alternative to customer for backup selection   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ API LAYER (logic.py)                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. _construct_target(): Uses custom_target if provided, else auto-generate │
│  2. _options_snapshot(): Stores customer_id for worker backup discovery     │
│  3. enqueue_job(): Creates job with target and options_json                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ WORKER (executor.py)                                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  derive_backup_lookup_target(): Uses options_json["customer_id"] for S3     │
│  job.target: Used for staging_name and final database name                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Insight**: `customer` and `custom_target` serve different purposes:
- `customer` → S3 backup discovery (what to restore)
- `custom_target` → Database naming (where to restore)

### 1. **API Schema** (`pulldb/api/schemas.py`)

Add optional `custom_target` field to `JobRequest`:

```python
class JobRequest(pydantic.BaseModel):
    """Incoming job submission payload."""

    user: str = pydantic.Field(min_length=1)
    customer: str | None = None
    qatemplate: bool = False
    dbhost: str | None = None
    date: str | None = None
    env: str | None = None
    overwrite: bool = False
    suffix: str | None = pydantic.Field(
        default=None,
        pattern=r"^[a-z]{1,3}$",
    )
    backup_path: str | None = None
    # NEW FIELD
    custom_target: str | None = pydantic.Field(
        default=None,
        pattern=r"^[a-z]{1,51}$",
        description="Custom target database name. 1-51 lowercase letters, user has FULL control.",
    )


class JobResponse(pydantic.BaseModel):
    """Response payload for successful job submission."""

    job_id: str
    target: str
    staging_name: str
    status: str
    owner_username: str
    owner_user_code: str
    submitted_at: datetime | None = None
    # Customer name normalization info (for long names)
    original_customer: str | None = None
    customer_normalized: bool = False
    normalization_message: str | None = None
    # NEW: Indicate if custom target was used
    custom_target_used: bool = False
```

**AUDIT NOTE**: The existing `backup_path` field shows the pattern for optional override fields. Custom target follows the same pattern. The `JobResponse.custom_target_used` field parallels the existing `customer_normalized` pattern.

### 2. **API Logic** (`pulldb/api/logic.py`)

**AUDIT NOTE**: The `TargetResult` dataclass is defined in logic.py around line 32-40. Verify location and structure when implementing.

#### 2a. Modify `_construct_target()` (lines 65-130)

```python
def _construct_target(user: User, req: JobRequest) -> TargetResult:
    """Construct target database name from user code and customer/qatemplate.
    
    If custom_target is provided, use it directly (user has FULL control).
    Auto-generated targets still use {user_code}{customer}{suffix} pattern.
    """
    # NEW: Handle custom target override
    if req.custom_target:
        custom = req.custom_target.lower()
        
        # Validate format: lowercase letters only, 1-51 chars
        if not custom.isalpha():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Target database name must contain only lowercase letters (a-z).",
            )
        
        if len(custom) < 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Target database name must be at least 1 character.",
            )
        
        if len(custom) > 51:  # MAX_TARGET_LEN from staging.py constants
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Target database name exceeds maximum length of 51 characters.",
            )
        
        # NEW: Prevent using customer database names as custom targets
        # This avoids confusion between S3 backup path and target database
        if _is_known_customer_name(state, custom):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot use customer name '{custom}' as custom target. "
                    f"Customer names are reserved for S3 backup discovery. "
                    f"Choose a different target name."
                ),
            )
        
        return TargetResult(
            target=custom,
            original_customer=None,
            normalized_customer=None,
            was_normalized=False,
            normalization_message="",
        )
    
    # Existing auto-generation logic continues below...
    # Uses {user_code}{customer}{suffix} pattern (unchanged)


def _is_known_customer_name(state: APIState, name: str) -> bool:
    \"\"\"Check if a name EXACTLY matches a known customer using existing customer search.
    
    Uses the same customer search that powers the restore page dropdown.
    This check happens at job submission (before queue) to fail fast.
    
    Prevents custom targets from using customer names, which would cause
    confusion between backup discovery paths and target database names.
    
    NOTE: This is an EXACT match check (case-insensitive). Partial matches are allowed.
    e.g., 'actionpest' is blocked, but 'actionpestdev' is allowed.
    \"\"\"
    if not hasattr(state, 's3_client') or not state.s3_client:
        return False  # Can't check - allow (fail open for customer check only)
    
    # Use existing customer search functionality
    # Same search that populates the customer dropdown on restore page
    try:
        # Get all customers from S3 (cached in most deployments)
        customers = state.s3_client.list_customers()
        
        # EXACT match check (case-insensitive only)
        name_lower = name.lower()
        
        for customer in customers:
            if name_lower == customer.lower():
                return True
        
        return False
    except Exception:
        return False  # Can't check - allow (S3 issue shouldn't block restore)
```

**When This Check Runs**:
- At API validation time in `_construct_target()` 
- BEFORE job is added to queue
- User gets immediate feedback if custom target matches a customer name
- No worker resources wasted on invalid jobs

**Match Behavior**:
- `actionpest` → ❌ BLOCKED (exact match)
- `ACTIONPEST` → ❌ BLOCKED (case-insensitive exact match)
- `actionpestdev` → ✅ ALLOWED (not exact match)
- `myactionpest` → ✅ ALLOWED (not exact match)
- `action` → ✅ ALLOWED (partial, not exact)

#### 2b. Modify `_options_snapshot()` (lines 131-275)

**AUDIT FINDING**: `_options_snapshot()` stores job parameters in `options_json` for self-contained execution and audit trail. Should store a `custom_target_used` flag.

```python
def _options_snapshot(req: JobRequest, state: APIState, dbhost: str) -> dict[str, str]:
    opts: dict[str, str] = {
        "customer_id": req.customer or "",
        "is_qatemplate": str(req.qatemplate).lower(),
        "overwrite": str(req.overwrite).lower(),
        "api_version": "v2",
    }
    
    # NEW: Track if custom target was used (for audit trail)
    if req.custom_target:
        opts["custom_target_used"] = "true"
    
    # ... rest of function unchanged ...
```

**Rationale**: This allows distinguishing between auto-generated and custom targets in job history/audit views without pattern matching.

#### 2c. Add External Database Protection (NEW)

**Location**: `pulldb/api/logic.py` in `enqueue_job()` function, after deployed job check.

**APPLIES TO ALL TARGETS** (both custom and auto-generated) when `overwrite=true`. This protects against overwriting external databases in ALL cases.

```python
# In enqueue_job(), after the deployed job check (~line 490):

# NEW: External database protection for ALL overwrites
if req.overwrite:
    # Check if target database exists and is pullDB-managed
    db_exists = _target_database_exists_on_host(state, target, dbhost)
    
    if db_exists is None:
        # FAIL HARD: Can't verify - don't risk overwriting external DB
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Cannot verify database '{target}' on '{dbhost}' - host unreachable. "
                f"Overwrites require verification that the database "
                f"is pullDB-managed. Try again later."
            ),
        )
    
    if db_exists:
        is_managed = _has_pulldb_metadata_table(state, target, dbhost)
        
        if is_managed is None:
            # FAIL HARD: Can't verify metadata table
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"Cannot verify database '{target}' is pullDB-managed - connection failed. "
                    f"Overwrites require verification. Try again later."
                ),
            )
        
        if not is_managed:
            emit_event(
                "job_enqueue_blocked",
                f"Blocked overwrite of external database '{target}' on '{dbhost}'",
                labels=MetricLabels(target=target, phase="enqueue", status="blocked"),
            )
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"Database '{target}' exists on '{dbhost}' but was not created by pullDB "
                    f"(missing pullDB metadata table). Cannot overwrite external databases. "
                    f"Use a different target name or manually drop the database first."
                ),
            )

# Helper functions (add to logic.py):

def _target_database_exists_on_host(state: APIState, target: str, dbhost: str) -> bool | None:
    """Check if a target database exists on the specified host.
    
    Uses host_repo to resolve credentials and queries SHOW DATABASES.
    Returns None on connection errors (caller must handle - FAIL HARD).
    """
    if not state.host_repo:
        return None  # Can't check without host_repo - caller decides
    try:
        creds = state.host_repo.get_host_credentials(dbhost)
        conn = mysql.connector.connect(
            host=creds.host,
            port=creds.port,
            user=creds.username,
            password=creds.password,
            connect_timeout=10,
        )
        try:
            cursor = conn.cursor()
            cursor.execute("SHOW DATABASES LIKE %s", (target,))
            return cursor.fetchone() is not None
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to check if database exists: {e}")
        return None  # Caller must handle - FAIL HARD


def _has_pulldb_metadata_table(state: APIState, target: str, dbhost: str) -> bool | None:
    """Check if a database has the pullDB metadata table (fingerprint).
    
    The pullDB table is injected into every database restored by pullDB.
    Its presence indicates the database is pullDB-managed.
    Returns None on connection errors (caller must handle - FAIL HARD).
    """
    if not state.host_repo:
        return None  # Can't check without host_repo - caller decides
    try:
        creds = state.host_repo.get_host_credentials(dbhost)
        conn = mysql.connector.connect(
            host=creds.host,
            port=creds.port,
            user=creds.username,
            password=creds.password,
            database=target,
            connect_timeout=10,
        )
        try:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES LIKE 'pullDB'")
            return cursor.fetchone() is not None
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to check pullDB table: {e}")
        return None  # Caller must handle - FAIL HARD
```

**Design Decisions**:
- **FAIL HARD**: If we can't connect to verify, BLOCK the job (don't risk overwriting external DB)
- **Defense in depth**: API check + Worker pre-flight check (see section 2d below)
- **Applies to ALL targets**: Both custom and auto-generated targets get the same protection

#### 2d. Worker Pre-Flight Check (Defense in Depth)

**Location**: `pulldb/worker/executor.py` in `WorkerJobExecutor.execute()` method, **AT THE START** after getting host credentials (~line 410) but BEFORE Discovery phase.

> ⚠️ **CRITICAL**: This check MUST happen BEFORE downloading, extracting, myloader, etc. Checking before atomic rename is way too late - you've already done all the work and can't proceed anyway.

The API check at enqueue time provides early validation, but the worker MUST re-verify at job start. This catches race conditions where an external database is created between enqueue and execution.

**APPLIES TO ALL TARGETS** (both custom and auto-generated) when overwrite is enabled.

```python
# In worker, AT THE START of execute() - BEFORE any downloads or processing:

def _pre_flight_verify_target_overwrite_safe(
    target: str,
    dbhost: str,
    credentials: MySQLCredentials,
    job: Job,
) -> None:
    """PRE-FLIGHT CHECK: Verify target is safe to overwrite BEFORE doing any work.
    
    Called by worker at the START of restore, before:
    - Downloading backup from S3
    - Extracting archive
    - Running myloader
    - Any other expensive operations
    
    APPLIES TO ALL TARGETS (custom and auto-generated) when overwrite=true.
    
    Raises:
        RestoreError: If target exists but is not pullDB-managed.
    """
    overwrite = job.options_json.get("overwrite", "false") == "true"
    
    # Only check when overwrite is enabled
    if not overwrite:
        return  # No overwrite: skip check (new DB will be created)
    
    logger.info(
        f"Pre-flight check: verifying target '{target}' is safe to overwrite",
        extra={"job_id": job.id, "target": target, "dbhost": dbhost},
    )
    
    # Check if target database exists
    conn = mysql.connector.connect(
        host=credentials.host,
        port=credentials.port,
        user=credentials.username,
        password=credentials.password,
        connect_timeout=30,
    )
    try:
        cursor = conn.cursor()
        cursor.execute("SHOW DATABASES LIKE %s", (target,))
        if cursor.fetchone() is None:
            logger.info(f"Target '{target}' does not exist - safe to proceed")
            return  # DB doesn't exist - safe to proceed
        
        # DB exists - check for pullDB table
        cursor.execute(f"SHOW TABLES IN `{target}` LIKE 'pullDB'")
        if cursor.fetchone() is None:
            # FAIL HARD, FAIL FAST: External database detected
            # Job status will be set to FAILED immediately
            raise RestoreError(
                job_id=job.id,
                phase="pre_flight_validation",
                message=(
                    f"COLLISION DETECTED: Target database '{target}' exists but is not "
                    f"pullDB-managed (missing pullDB metadata table). Cannot overwrite "
                    f"external databases. Either choose a different target name or "
                    f"manually drop the existing database."
                ),
            )
        
        # DB exists with pullDB table - check ownership
        cursor.execute(f"SELECT owner_user_code FROM `{target}`.pullDB LIMIT 1")
        row = cursor.fetchone()
        if row:
            db_owner_code = row[0]
            if db_owner_code != job.owner_user_code:
                # FAIL HARD: Database owned by different user
                raise RestoreError(
                    job_id=job.id,
                    phase="pre_flight_validation",
                    message=(
                        f"OWNERSHIP COLLISION: Target database '{target}' exists and is "
                        f"owned by user '{db_owner_code}'. You cannot overwrite databases "
                        f"owned by other users. Contact the owner or choose a different target."
                    ),
                )
        
        logger.info(
            f"Target '{target}' verified as pullDB-managed, safe to overwrite",
            extra={"job_id": job.id, "target": target},
        )
    finally:
        conn.close()
```

**Why Pre-Flight (Not Pre-Rename)**:
1. **Don't waste resources**: Downloading, extracting, and restoring can take 5-30+ minutes
2. **Fail fast**: Know immediately if the job will fail, not after hours of work
3. **Race condition window**: Check happens closer to when external DB might be created
4. **Better UX**: User sees failure immediately, not after long wait

**Call Site** (in `pulldb/worker/executor.py` - inside `execute()` method):
```python
def execute(self, job: Job) -> None:
    """Run the full restore workflow for a job."""
    logger.info(
        "Executing job",
        extra={"job_id": job.id, "target": job.target, "phase": "executor_start"},
    )
    job_dir, download_dir, extract_dir = self._prepare_job_dirs(job.id)
    profiler = RestoreProfiler(job.id)

    try:
        host_credentials = self.host_repo.get_host_credentials(job.dbhost)
        
        # ▼▼▼ INSERT PRE-FLIGHT CHECK HERE ▼▼▼
        _pre_flight_verify_target_overwrite_safe(
            target=job.target,
            dbhost=job.dbhost,
            credentials=host_credentials,
            job=job,
        )
        # ▲▲▲ PRE-FLIGHT CHECK END ▲▲▲

        # Phase: Discovery (expensive S3 operations start here)
        with profiler.phase(RestorePhase.DISCOVERY) as discovery_profile:
            backup_spec, location, lookup_target = self.discover_backup_for_job(job)
        # ... download, extract, myloader, etc.
```

### 3. **Web Template** (`pulldb/web/templates/features/restore/restore.html`)

Replace read-only target preview with fully editable input (no locked prefix):

```html
<!-- Target Database Name - FULLY EDITABLE -->
<div class="target-input-group" id="target-input-group">
    <div class="target-preview-label">Target Database Name</div>
    <div class="target-input-wrapper">
        <input type="text" 
               id="custom-target-input" 
               name="custom_target"
               class="form-input target-input lowercase"
               placeholder="mytestdb"
               pattern="[a-z]{1,51}"
               maxlength="51"
               value="">
    </div>
    <p class="form-hint-sm">
        Auto-filled from selection. Edit to use any custom name (1-51 lowercase letters).
    </p>
</div>
```

### 4. **JavaScript** (`pulldb/web/static/js/pages/restore.js`)

Update target preview logic to support full editing:

```javascript
function updateTargetPreview() {
    const preview = $('target-input-group');
    const targetInput = $('custom-target-input');
    
    if (!preview || !targetInput) {
        return;
    }
    
    // Show input when customer is selected OR qatemplate is checked
    if (!selectedCustomer && !$('qatemplate')?.checked) {
        hide(preview);
        return;
    }
    
    const userCode = getUserCode();
    const suffix = $('suffix')?.value || '';
    
    // Auto-fill with default pattern if user hasn't manually edited
    if (!targetInput.dataset.userEdited) {
        if ($('qatemplate')?.checked) {
            // QA template: just use 'qatemplate' or let user customize
            targetInput.value = userCode + 'qatemplate' + suffix;
        } else if (selectedCustomer) {
            const normResult = normalizeCustomerName(selectedCustomer);
            targetInput.value = userCode + normResult.normalized + suffix;
        }
    }
    
    show(preview);
}

// Track manual edits - user can type ANY valid target
function initTargetInput() {
    const input = $('custom-target-input');
    if (!input) return;
    
    input.addEventListener('input', (e) => {
        e.target.dataset.userEdited = 'true';
        // Force lowercase, letters only
        e.target.value = e.target.value.toLowerCase().replace(/[^a-z]/g, '');
        updateSummary();
    });
}

// Reset auto-fill when customer selection changes
// NOTE: Changing customer CLEARS any custom target edits - this is intentional
// User must re-enter custom target if they switch customers
function onCustomerChanged() {
    const input = $('custom-target-input');
    if (input) {
        // Clear the edit flag AND the value - start fresh with new auto-fill
        delete input.dataset.userEdited;
        input.value = '';  // Clear previous custom value
    }
    updateTargetPreview();
}
```

### 5. **Web Route** (`pulldb/web/features/restore/routes.py`)

Accept and pass through `custom_target`:

```python
@router.post("/")
async def restore_submit(
    request: Request,
    customer: str = Form(...),
    s3env: str = Form(...),
    dbhost: str = Form(...),
    suffix: str | None = Form(None),
    backup_key: str | None = Form(None),
    overwrite: str | None = Form(None),
    submit_as_user: str | None = Form(None),
    qatemplate: str | None = Form(None),
    custom_target: str | None = Form(None),  # NEW
    state: Any = Depends(get_api_state),
    user: User = Depends(require_login),
) -> Any:
    # ... existing validation ...
    
    # Validate custom_target if provided
    if custom_target:
        custom_target = custom_target.lower().strip()
        if not custom_target:
            custom_target = None  # Empty string → None
        elif not custom_target.isalpha():
            return templates.TemplateResponse(
                "features/restore/restore.html",
                {
                    "request": request,
                    "allowed_hosts": allowed_hosts,  # Must include for re-render
                    "default_host": user.default_host,
                    "user": user,
                    "error": "Target database name must contain only lowercase letters (a-z).",
                    "active_nav": "restore",
                    "form": {
                        "customer": customer,
                        "s3env": s3env,
                        "dbhost": dbhost,
                        "suffix": suffix,
                        "overwrite": overwrite == "true",
                        "custom_target": custom_target,  # PRESERVE for re-render
                    },
                },
                status_code=400
            )
    
    req = JobRequest(
        user=effective_username,
        customer=customer_for_api if not is_qatemplate else None,
        qatemplate=is_qatemplate,
        env=env_val,
        dbhost=dbhost if dbhost else None,
        suffix=suffix if suffix and not custom_target else None,  # suffix ignored if custom_target
        overwrite=overwrite_val,
        backup_path=validated_backup_path,

# NOTE: Web UI silently ignores suffix when custom_target is provided.
# CLI rejects suffix + custom_target with an error.
# This asymmetry is intentional: Web auto-fills the custom target field
# which may still contain a suffix from a previous selection. Rather than
# forcing users to manually clear the suffix field, we just ignore it.
        custom_target=custom_target,  # NEW
    )
```

**AUDIT NOTE**: All `templates.TemplateResponse` error returns in routes.py include a `form` dict. When adding custom_target, ensure ALL error branches include `custom_target` in the form dict to preserve user input on validation errors.

**Form Preservation Locations** (routes.py - must add `custom_target` to form dict):

| Line | Error Scenario |
|------|---------------|
| ~330 | Invalid customer format |
| ~350 | Customer not found in S3 |
| ~370 | Invalid dbhost |
| ~390 | Host not allowed for user |
| ~425 | Backup validation failed |
| ~445 | Backup not found |
| ~498 | API error during enqueue |
| ~515 | Unexpected exception |

Each location should include: `"custom_target": custom_target,` in the form dict.
```

### 6. CLI Parse (`pulldb/cli/parse.py`)

Add `target=` token parsing:

```python
# Add regex pattern
_TOKEN_TARGET = re.compile(r"^(?:--)?target=([a-z]{1,51})$")

# Update RestoreCLIOptions dataclass
@dataclass(frozen=True)
class RestoreCLIOptions:
    raw_tokens: tuple[str, ...]
    username: str | None
    customer_id: str | None
    is_qatemplate: bool
    suffix: str | None
    dbhost: str | None
    date: str | None
    s3env: str | None
    overwrite: bool
    original_customer: str | None = None
    customer_normalized: bool = False
    normalization_message: str = ""
    custom_target: str | None = None  # NEW

# Add to _tokenize() function
# Check target= token
if tok.lstrip("-").startswith("target="):
    if custom_target is not None:
        raise CLIParseError("target specified more than once")
    target_value = tok.split("=", 1)[1].lower()  # Force lowercase
    if not re.match(r"^[a-z]{1,51}$", target_value):
        if len(target_value) < 1:
            raise CLIParseError(
                f"target must be at least 1 lowercase letter. "
                f"Got: '{target_value}'."
            )
        if len(target_value) > 51:
            raise CLIParseError(
                f"target exceeds maximum length of 51 characters. "
                f"Got: '{target_value}' ({len(target_value)} chars)."
            )
        raise CLIParseError(
            f"target must contain only lowercase letters (a-z). Got: '{target_value}'."
        )
    custom_target = target_value
    i += 1
    continue

# Add validation in parse_restore_args()
if custom_target is not None and suffix is not None:
    raise CLIParseError(
        "Cannot use suffix= with target=. Include the suffix in the target name directly."
    )
```

### 7. **CLI Main** (`pulldb/cli/main.py`)

Update help text and payload:

```python
@cli.command("restore", ...)
def restore_cmd(options: tuple[str, ...]) -> None:
    """Submit a database restore job.

    \b
    OPTIONS:
      target=<name>         Custom target database name (1-51 lowercase letters)
      ...
    """
    """
    # ... existing code ...
    
    payload: dict[str, t.Any] = {
        "user": username,
        "customer": parsed.customer_id,
        "qatemplate": parsed.is_qatemplate,
        "suffix": parsed.suffix,
        "dbhost": parsed.dbhost,
        "date": parsed.date,
        "overwrite": parsed.overwrite,
        "custom_target": parsed.custom_target,  # NEW
    }
```

**AUDIT NOTE**: Existing test `tests/qa/cli/test_restore.py:27` explicitly documents `target=` as NOT a valid token:
```python
# As of 2026-01-09, the only valid tokens are:
# customer, qatemplate, suffix=<suffix>, host=<host>, date=<date>, env=<env>, overwrite
# The following are NOT valid: target=<target>, path=<path>
```
This test comment must be updated when implementing. Consider converting this comment into an actual test case.

------

## CSS Updates (`pulldb/web/pages/css/restore.css`)

Style the editable target input:

```css
/* Target Input Group */
.target-input-group {
    background: var(--surface-secondary);
    border: 1px solid var(--border-secondary);
    border-radius: 8px;
    padding: 16px;
    margin-top: 16px;
}

.target-input-wrapper {
    display: flex;
    align-items: center;
    background: var(--surface-primary);
    border: 1px solid var(--border-primary);
    border-radius: 6px;
    overflow: hidden;
}

.target-input {
    flex: 1;
    border: none;
    padding: 8px 12px;
    font-family: var(--font-mono);
    font-size: 14px;
    background: transparent;
    width: 100%;
}

.target-input:focus {
    outline: none;
    box-shadow: inset 0 0 0 2px var(--accent-primary);
}

/* Dark mode */
[data-theme="dark"] .target-input-group {
    background: var(--dark-surface-secondary);
    border-color: var(--dark-border-secondary);
}
```

---

## Test Coverage Required

### API Tests (`tests/qa/api/`)

| Test | Description |
|------|-------------|
| `test_custom_target_accepted` | Valid custom_target (1-51 lowercase letters) is accepted |
| `test_custom_target_max_length` | Rejects target > 51 chars |
| `test_custom_target_min_length` | Accepts target of 1 char (e.g., `a`) |
| `test_custom_target_lowercase_only` | Rejects target with non-letters |
| `test_custom_target_overrides_suffix` | suffix ignored when custom_target provided |
| `test_custom_target_used_in_response` | `JobResponse.custom_target_used` is True when custom target provided |
| `test_custom_target_used_in_options_json` | `options_json["custom_target_used"]` stored for audit |
| `test_overwrite_blocks_external_db` | Rejects overwrite of DB without pullDB table (ALL targets) |
| `test_overwrite_allows_pulldb_managed` | Allows overwrite of DB with pullDB table (ALL targets) |
| `test_custom_target_allows_new_db` | Allows custom target when DB doesn't exist |
| `test_external_db_check_connection_fails_blocked` | Job BLOCKED (503) if DB existence check fails |
| `test_external_db_check_metadata_fails_blocked` | Job BLOCKED (503) if pullDB table check fails |
| `test_target_collision_different_user` | Rejects target owned by different user, shows FULL username |
| `test_target_collision_same_user_allowed` | Allows overwrite if owned by same user |
| `test_custom_target_rejects_customer_name` | Rejects custom target matching known customer name |
| `test_custom_target_collision_error_format` | Error message includes full owner username for resolution |

**AUDIT NOTE**: Consider adding `custom_target_used: bool = False` to `JobResponse` schema (line 38) to indicate in API responses whether a custom target was used. This parallels existing `customer_normalized: bool = False` pattern.

### Worker Tests (`tests/qa/worker/`)

| Test | Description |
|------|-------------|
| `test_worker_preflight_blocks_external_db` | Worker fails BEFORE download if target is external DB (ALL targets) |
| `test_worker_preflight_allows_pulldb_managed` | Worker proceeds past pre-flight when pullDB table exists |
| `test_worker_preflight_allows_new_db` | Worker proceeds past pre-flight when target DB doesn't exist |
| `test_worker_preflight_catches_race_condition` | Worker catches external DB created after enqueue (before download) |
| `test_worker_preflight_skipped_without_overwrite` | Pre-flight check skipped when overwrite=false |
| `test_metadata_table_stores_ownership` | pullDB table contains owner_user_id, owner_user_code columns |
| `test_metadata_table_stores_custom_target_flag` | pullDB table `custom_target` column set correctly |

### CLI Tests (`tests/qa/cli/`)

| Test | Description |
|------|-------------|
| `test_parse_target_token` | `target=mytestdb` parses correctly |
| `test_parse_target_min_length` | `target=a` parses correctly (1 char minimum) |
| `test_parse_target_too_long` | `target=<52 chars>` raises CLIParseError |
| `test_parse_target_with_suffix_error` | `target=x suffix=y` raises CLIParseError |
| `test_custom_target_in_options` | `RestoreCLIOptions.custom_target` populated |
| `test_parse_target_case_insensitive` | `target=MyTestDB` → lowercase conversion |

### Web/E2E Tests (`tests/e2e/`)

| Test | Description |
|------|-------------|
| `test_target_input_autofills` | Target field auto-fills when customer selected |
| `test_target_input_fully_editable` | User can edit target field to ANY valid value |
| `test_target_preserves_on_error` | Edited target preserved on validation error |
| `test_target_clears_on_customer_change` | Auto-fill reset when customer selection changes |

### Cleanup Safety Tests (`tests/qa/worker/`)

| Test | Description |
|------|-------------|
| `test_delete_auto_target_validates_user_code` | Auto-generated target: validates user_code in target name |
| `test_delete_custom_target_skips_user_code_check` | Custom target: skips user_code-in-name check (uses job ownership) |
| `test_delete_custom_target_validates_job_owner` | Custom target deletion validates job.owner_user_id matches |
| `test_orphan_cleanup_checks_pulldb_table` | Orphan detection queries pullDB metadata for ownership |
| `test_orphan_cleanup_blocks_external_db` | Orphan cleanup refuses DB without pullDB table |
| `test_orphan_cleanup_verifies_owner_user_code` | Orphan cleanup verifies owner_user_code matches |

### Admin Cleanup Tests (`tests/qa/admin/`)

| Test | Description |
|------|-------------|
| `test_find_orphaned_databases` | Correctly identifies DBs with no job record |
| `test_orphan_with_pulldb_table_shows_ownership` | Orphans with pullDB table report owner info |
| `test_orphan_without_pulldb_table_flagged_external` | Orphans without pullDB table flagged as external |
| `test_admin_cannot_drop_external_db` | Admin cleanup refuses to drop external (non-pullDB) databases |
| `test_admin_verifies_pulldb_ownership` | Admin cleanup uses pullDB table for ownership verification |

---

## Migration & Compatibility

### Backward Compatibility

- **`custom_target` is optional**: Existing behavior unchanged if not provided
- **Schema migration required**: 
  - Jobs table: Add `custom_target` column
  - pullDB metadata table: Add `owner_user_id`, `owner_user_code`, `custom_target` columns
- **Existing jobs**: Will have `custom_target=0` (default)
- **Existing pullDB tables**: MUST be migrated with ownership data from job records
- **API versioning**: No breaking changes to existing API contracts

### Schema Migration

```sql
-- Jobs table (service database)
ALTER TABLE jobs ADD COLUMN custom_target TINYINT(1) NOT NULL DEFAULT 0 
    COMMENT 'Whether custom target naming was used' AFTER options_json;

-- pullDB metadata table (each restored database)
-- New schema with ownership columns - see migration script below
```

### Active Database Migration (REQUIRED)

**Problem**: Existing restored databases have pullDB tables WITHOUT ownership columns. These MUST be migrated to enable the new ownership-based safety model.

**Migration Script** (`scripts/migrate_pulldb_ownership.py`):

```python
"""
Migrate existing pullDB metadata tables to include ownership information.

For each deployed/locked job:
1. Find the target database
2. ALTER the pullDB table to add new columns
3. UPDATE with ownership data from jobs table
"""

def migrate_pulldb_tables(
    job_repo: JobRepository,
    host_repo: HostRepository,
    dry_run: bool = True,
) -> MigrationReport:
    """Migrate all active pullDB tables with ownership data."""
    
    report = MigrationReport()
    
    # Get all deployed/locked jobs (active databases)
    active_jobs = job_repo.get_all_deployed_and_locked_jobs()
    
    for job in active_jobs:
        try:
            creds = host_repo.get_host_credentials(job.dbhost)
            
            # Check if pullDB table exists
            if not _has_pulldb_table(creds, job.target):
                report.skipped.append((job.id, job.target, "no pullDB table"))
                continue
            
            # Check if already migrated (has owner_user_code column)
            if _has_ownership_columns(creds, job.target):
                report.already_migrated.append((job.id, job.target))
                continue
            
            if dry_run:
                report.would_migrate.append((job.id, job.target, job.owner_user_code))
                continue
            
            # ALTER table to add columns
            _add_ownership_columns(creds, job.target)
            
            # UPDATE with job ownership data
            _update_ownership_data(
                creds,
                target=job.target,
                owner_user_id=job.owner_user_id,
                owner_user_code=job.owner_user_code,
                custom_target=False,  # All existing jobs are auto-generated
            )
            
            report.migrated.append((job.id, job.target, job.owner_user_code))
            
        except Exception as e:
            report.errors.append((job.id, job.target, str(e)))
    
    return report


def _has_ownership_columns(creds: MySQLCredentials, target: str) -> bool:
    """Check if pullDB table has the new ownership columns."""
    conn = mysql.connector.connect(...)
    cursor = conn.cursor()
    cursor.execute(f"SHOW COLUMNS FROM `{target}`.pullDB LIKE 'owner_user_code'")
    return cursor.fetchone() is not None


def _add_ownership_columns(creds: MySQLCredentials, target: str) -> None:
    """Add ownership columns to existing pullDB table."""
    conn = mysql.connector.connect(...)
    cursor = conn.cursor()
    
    # Add columns (nullable initially for migration)
    cursor.execute(f"""
        ALTER TABLE `{target}`.pullDB
        ADD COLUMN owner_user_id CHAR(36) NULL 
            COMMENT 'UUID of database owner' AFTER job_id,
        ADD COLUMN owner_user_code CHAR(6) NULL 
            COMMENT '6-char owner identifier' AFTER owner_user_id,
        ADD COLUMN custom_target TINYINT(1) NOT NULL DEFAULT 0 
            COMMENT 'Whether custom target was used' AFTER restore_duration_seconds,
        ADD INDEX idx_pulldb_owner (owner_user_id),
        ADD INDEX idx_pulldb_user_code (owner_user_code)
    """)
    conn.commit()


def _update_ownership_data(
    creds: MySQLCredentials,
    target: str,
    owner_user_id: str,
    owner_user_code: str,
    custom_target: bool,
) -> None:
    """Update pullDB table with ownership data from job record."""
    conn = mysql.connector.connect(...)
    cursor = conn.cursor()
    
    cursor.execute(f"""
        UPDATE `{target}`.pullDB
        SET owner_user_id = %s,
            owner_user_code = %s,
            custom_target = %s
    """, (owner_user_id, owner_user_code, 1 if custom_target else 0))
    conn.commit()
```

**Migration Execution Plan**:

1. **Pre-migration audit**:
   ```bash
   python scripts/migrate_pulldb_ownership.py --dry-run
   ```
   - Lists all databases that need migration
   - Identifies any databases without pullDB tables (shouldn't exist for deployed jobs)

2. **Run migration** (during maintenance window):
   ```bash
   python scripts/migrate_pulldb_ownership.py --execute
   ```

3. **Post-migration verification**:
   ```bash
   python scripts/migrate_pulldb_ownership.py --verify
   ```
   - Confirms all active databases have ownership columns populated

4. **Make columns NOT NULL** (after verification):
   ```sql
   -- Run on each migrated database (or via script)
   ALTER TABLE `{target}`.pullDB
       MODIFY COLUMN owner_user_id CHAR(36) NOT NULL,
       MODIFY COLUMN owner_user_code CHAR(6) NOT NULL;
   ```

**Migration Considerations**:

| Scenario | Handling |
|----------|----------|
| Deployed job with pullDB table | ✅ Migrate with job ownership data |
| Deployed job without pullDB table | ⚠️ Log warning - shouldn't happen |
| Locked job (staging exists) | ✅ Migrate staging database too |
| Orphan database (no job record) | ❌ Cannot migrate - no ownership data available |
| Database on unreachable host | ⚠️ Retry later, log for manual follow-up |

**Handling Legacy _get_pulldb_metadata()**:

After migration, cleanup scripts should still handle the case where ownership columns might be NULL (for orphans that couldn't be migrated):

```python
def _get_pulldb_metadata(creds, db_name) -> PullDBMetadata | None:
    """Get pullDB metadata, handling both old and new schemas."""
    if not _has_pulldb_table(creds, db_name):
        return None
    
    # Query all columns (ownership may be NULL for unmigrated orphans)
    result = query(f"""
        SELECT job_id, owner_user_id, owner_user_code, custom_target 
        FROM `{db_name}`.pullDB LIMIT 1
    """)
    
    if not result:
        return None
    
    return PullDBMetadata(
        job_id=result.job_id,
        owner_user_id=result.owner_user_id,  # May be NULL for orphans
        owner_user_code=result.owner_user_code,  # May be NULL for orphans
        custom_target=bool(result.custom_target) if result.custom_target else False,
    )
```

### Client Version Compatibility

| Client Version | Behavior |
|----------------|----------|
| Old client (no `target=`) | Works as before, auto-generated targets |
| New client with `target=` | Custom target supported (1-51 lowercase letters, full user control) |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Target collision with another user | Medium | High | Ownership check blocks - shows full owner username in error |
| User confusion between auto/custom | Medium | Low | Clear UI hint text, auto-fill on customer selection |
| Long target causes staging overflow | Low | High | API validates max 51 chars |
| Non-letter characters in target | Low | Medium | API + client validate lowercase letters only |
| Custom target uses customer name | Medium | Medium | API rejects customer names as custom targets |
| Admin deletes external DB by mistake | Low | Critical | pullDB table check blocks external DBs |
| Admin deletes orphan owned by another user | Low | Critical | pullDB.owner_user_code is AUTHORITATIVE |
| Custom target bypasses user_code safety check | Medium | High | Custom targets use pullDB ownership; auto-generated use both |
| Race condition: external DB created after enqueue | Low | High | Worker pre-flight check catches and fails FAST (FAILED status) |
| User removed but owns databases | Low | Medium | Orphan cleanup proceeds normally for removed users |

---

## Implementation Order

1. **Phase 1: Schema Updates**
   - [ ] Update pullDB metadata table schema (metadata.py) - add ownership columns
   - [ ] Add `custom_target` column to jobs table
   - [ ] Create migration script (`scripts/migrate_pulldb_ownership.py`)

2. **Phase 2: Migration (BEFORE deploying feature)**
   - [ ] Run migration dry-run to audit all active databases
   - [ ] Execute migration during maintenance window
   - [ ] Verify all deployed/locked databases have ownership columns populated
   - [ ] Make ownership columns NOT NULL after verification

3. **Phase 3: API Layer**
   - [ ] Add `custom_target` to `JobRequest` schema (1-51 lowercase letters)
   - [ ] Update `_construct_target()` with validation
   - [ ] Add target ownership collision check (refuse if owned by different user)
   - [ ] Add API tests

4. **Phase 4: CLI Client**
   - [ ] Add `target=` token parsing
   - [ ] Update `RestoreCLIOptions` dataclass
   - [ ] Update API payload construction
   - [ ] Add CLI tests
   - [ ] Update CLIENT-README.md

5. **Phase 5: Web UI**
   - [ ] Update restore.html template (fully editable target input)
   - [ ] Update restore.js with edit tracking
   - [ ] Update restore.css styling
   - [ ] Update routes.py to accept custom_target
   - [ ] Add E2E tests

6. **Phase 6: Cleanup Logic**
   - [ ] Update cleanup.py: auto-generated targets use user_code check
   - [ ] Update cleanup.py: custom targets use job record ownership
   - [ ] Update orphan cleanup to use pullDB metadata as AUTHORITATIVE
   - [ ] Add cleanup tests

7. **Phase 7: Admin Tools**
   - [ ] Update `find_orphaned_databases()` to query pullDB metadata
   - [ ] Update `safe_drop_orphaned_database()` with ownership verification
   - [ ] Create admin bulk cleanup tool with reporting
   - [ ] Add admin cleanup tests

8. **Phase 8: Documentation**
   - [ ] Update CLI help text
   - [ ] Update web user guide
   - [ ] Update API reference

---

## CLI Usage Examples

```bash
# Existing behavior (unchanged) - auto-generated targets
pulldb restore actionpest                    # → charleactionpest
pulldb restore actionpest suffix=dev         # → charleactionpestdev

# New: Custom target (user has FULL control - any name 1-51 lowercase letters)
pulldb restore actionpest target=tanner      # → tanner
pulldb restore actionpest target=mytest      # → mytest
pulldb restore actionpest target=prod        # → prod
pulldb restore qatemplate target=qatest      # → qatest
pulldb restore actionpest target=a           # → a (minimum 1 char)

# Error cases
pulldb restore actionpest target=tanner suffix=dev
# → Error: Cannot use suffix= with target=

pulldb restore actionpest target=MYTEST
# → Normalized to lowercase: mytest

pulldb restore actionpest target=my-test
# → Error: target must contain only lowercase letters (a-z)

pulldb restore actionpest target=<52+ chars>
# → Error: target exceeds maximum length of 51 characters

# Target collision with another user
pulldb restore actionpest target=prod
# → Error: Database 'prod' exists and is owned by user 'bob.smith'. 
#          You cannot overwrite databases owned by other users.
#          Contact the owner or choose a different target name.

# Custom target using customer name (blocked)
pulldb restore actionpest target=actionpest
# → Error: Cannot use customer name 'actionpest' as custom target.
#          Customer names are reserved for S3 backup discovery.
#          Choose a different target name.
```

---

## Open Questions

1. **~~Should we allow editing the prefix?~~** 
   - **RESOLVED**: YES. Custom target = FULL user control. No prefix requirement.
   - Auto-generated targets still use `{user_code}{customer}{suffix}` pattern.

2. **~~Should custom_target work with qatemplate?~~**
   - **RESOLVED**: Yes, `pulldb restore qatemplate target=myqa`
   - Rationale: No reason to restrict
   - `derive_backup_lookup_target()` uses `customer_id` for backup discovery, not target name.

3. **~~UX: How to indicate custom vs auto-generated in job history?~~**
   - **RESOLVED**: Store in `options_json["custom_target_used"]` + `jobs.custom_target` column.
   - Target name is displayed as normal - no special indicator needed.
   - CLI `pulldb status` shows target name as normal.

4. **~~Should custom_target be visible in job detail views?~~**
   - **RESOLVED**: The target name itself is visible (as always). No special "custom target" indicator needed.
   - Users see the target name they chose - that's sufficient.

5. **~~Target namespace collision handling?~~**
   - **RESOLVED**: If target exists and owned by different user → REFUSE with error showing **full owner username**.
   - Error message: `"Database 'prod' exists and is owned by user 'bob.smith'. You cannot overwrite databases owned by other users."`
   - Full username shown so users can contact the owner to resolve.

6. **~~Can custom target use customer names?~~**
   - **RESOLVED**: NO. Customer names are reserved for S3 backup discovery.
   - Validation rejects custom targets that match known customer names.
   - Error: `"Cannot use customer name 'actionpest' as custom target. Choose a different target name."`

7. **~~Manager "submit as user" + custom target ownership?~~**
   - **RESOLVED**: If manager submits job for user `bob` with `custom_target=prod`:
     - Job owner = bob (bob's `user_id`)
     - Database owner = bob (pullDB.owner_user_code = bob's code)
     - Manager is just submitting on behalf of bob, bob owns everything.

8. **~~What happens when customer selection changes in Web UI?~~**
   - **RESOLVED**: Any custom target edits are LOST when customer changes.
   - User must re-enter custom target if they switch customers.
   - This is intentional - prevents stale target names from previous selections.

---

## References

- [Business Logic: Target Database Naming](../.github/copilot-instructions-business-logic.md#target-database-naming)
- [MySQL Schema: jobs table](./hca/entities/mysql-schema.md#jobs)
- [Cleanup Safety: User Code Validation](../pulldb/worker/cleanup.py#L724-L730)
- [Staging Pattern: Length Constraints](./archived/staging-rename-pattern.md#length-constraints)
