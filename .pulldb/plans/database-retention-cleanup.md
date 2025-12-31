# Database Retention & Cleanup System

**Created**: 2025-12-31
**Status**: In Progress
**Branch**: feature/database-retention-cleanup

---

## Goal

Automatically manage database lifecycle to keep the system clean while protecting user data, with forced user accountability for expired databases.

---

## Core Concepts

### Database States Timeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TIMELINE                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   RESTORE         ACTIVE          EXPIRING        EXPIRED        CLEANUP   │
│   COMPLETE         ZONE            NOTICE          ZONE           RUNS     │
│      │               │               │               │              │       │
│      ▼               ▼               ▼               ▼              ▼       │
│  ────●───────────────────────────────●───────────────●──────────────●────►  │
│      │                               │               │              │       │
│   expires_at                    expires_at -    expires_at     expires_at + │
│   = now +                       notice_days                    grace_days   │
│   max_retention                    (7)                            (7)       │
│                                                                             │
│                                                                             │
│   LOCKED ─────────────────────────────────────────────────────────────────► │
│   (immune to cleanup, overwrite, user removal)                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Settings (Admin-Configurable)

| Setting | Default | Description |
|---------|---------|-------------|
| `max_retention_months` | 6 | Default expiration for new restores; cap for extensions |
| `max_retention_increment` | 3 | Step size for dropdown options (1, 3, 6...) |
| `expiring_notice_days` | 7 | Days before expiry to show in notice section |
| `cleanup_grace_days` | 7 | Days after expiry before cleanup removes DB |

---

## User Experience

### Daily Login Modal (Maintenance Acknowledgment)

**Trigger:** First login of the day if user has expired, expiring, or locked databases.

```
┌─────────────────────────────────────────────────────────────────┐
│  ⚠️  Database Maintenance                                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  EXPIRED (will be removed next cleanup):                        │
│  acme_prod (host1) - expired 3 days ago    [ -- Optional -- ▼ ] │
│  test_db (host2) - expired 1 day ago       [ -- Optional -- ▼ ] │
│                                                                 │
│  ─────────────────────────────────────────────────────────────  │
│  EXPIRING SOON:                                                 │
│  staging_copy (host1) - expires in 4 days  [ -- Optional -- ▼ ] │
│  demo_db (host2) - expires in 6 days       [ -- Optional -- ▼ ] │
│                                                                 │
│  ─────────────────────────────────────────────────────────────  │
│  LOCKED:                                                        │
│  prod_critical (host1) - expired 2mo ago   [ -- Optional -- ▼ ] │
│                                                                 │
│                                                 [ Acknowledge ] │
└─────────────────────────────────────────────────────────────────┘
```

| Section | Dropdown Options | Required? |
|---------|------------------|-----------|
| **Expired** | Now, +1mo, +3mo, +6mo... (per settings) | ❌ Optional |
| **Expiring Soon** | Now, +1mo, +3mo, +6mo... (per settings) | ❌ Optional |
| **Locked** | Unlock | ❌ Optional |

**Acknowledge button** - Always enabled. User can make selections or just acknowledge and move on.

---

### Active Jobs View

Shows all databases user currently owns (not cleaned up, not superseded):

| Target | Host | Status | Expires | Actions |
|--------|------|--------|---------|---------|
| acme_prod | host1 | 🔒 Locked | (2mo ago) | [Unlock] |
| staging_db | host2 | ⚠️ Expiring | in 3 days | [Extend ▼] [Lock] [Remove] |
| test_db | host1 | ✓ Active | in 4 months | [Extend ▼] [Lock] [Remove] |

---

### History View

Contains removed, failed, canceled, superseded jobs.

- If database still exists → can Extend or Lock (moves back to Active)
- If database was dropped → read-only, no actions

---

## Lock Behavior

**What lock protects against:**

| Threat | Protected? |
|--------|------------|
| Scheduled cleanup | ✅ Yes |
| User clicking Remove | ✅ Yes |
| New restore overwriting same target | ✅ Yes |
| Appearing in Expired action list | ✅ Yes |

**How to remove a locked database:**
1. User unlocks it first, then removes
2. OR Admin deletes the user entirely

---

## New Restore Behavior

When restore completes:
```python
expires_at = completed_at + max_retention_months
```

If target+host has a **locked** job:
- Restore blocked: "Target 'X' is locked. Unlock it first or choose a different target."

If target+host has unlocked previous job:
- Previous job marked as `superseded`
- New job becomes the active one

---

## Schema Changes

```sql
-- Jobs table additions
ALTER TABLE jobs ADD COLUMN expires_at TIMESTAMP(6) NULL;
ALTER TABLE jobs ADD COLUMN locked_at TIMESTAMP(6) NULL;
ALTER TABLE jobs ADD COLUMN locked_by VARCHAR(255) NULL;
ALTER TABLE jobs ADD COLUMN db_dropped_at TIMESTAMP(6) NULL;
ALTER TABLE jobs ADD COLUMN superseded_at TIMESTAMP(6) NULL;
ALTER TABLE jobs ADD COLUMN superseded_by_job_id CHAR(36) NULL;

-- User table addition
ALTER TABLE auth_users ADD COLUMN last_maintenance_ack DATE NULL;

-- New settings
INSERT INTO settings (setting_key, setting_value, description) VALUES
  ('max_retention_months', '6', 'Default expiration for new restores; maximum extension allowed'),
  ('max_retention_increment', '3', 'Step size for retention dropdown options'),
  ('expiring_notice_days', '7', 'Days before expiry to show warning'),
  ('cleanup_grace_days', '7', 'Days after expiry before automatic cleanup');

-- Backfill existing complete jobs
UPDATE jobs 
SET expires_at = DATE_ADD(completed_at, INTERVAL 6 MONTH)
WHERE status = 'complete' 
  AND expires_at IS NULL 
  AND completed_at IS NOT NULL;
```

---

## Implementation Phases

### Phase 1: Schema & Settings Foundation

#### Step 1.1: Add Schema Migration
**File**: `schema/pulldb_service/008_database_retention.sql` (new)

#### Step 1.2: Register Settings
**File**: `pulldb/domain/settings_registry.py`

Add to `SETTING_REGISTRY`:
- `max_retention_months`
- `max_retention_increment`
- `expiring_notice_days`
- `cleanup_grace_days`

#### Step 1.3: Add Settings Repository Methods
**File**: `pulldb/infra/settings_repo.py`

- `get_max_retention_months() -> int`
- `get_max_retention_increment() -> int`
- `get_expiring_notice_days() -> int`
- `get_cleanup_grace_days() -> int`
- `get_retention_options(include_now: bool, include_no_change: bool) -> list[tuple]`

---

### Phase 2: Domain Model Updates

#### Step 2.1: Update Job Model
**File**: `pulldb/domain/models.py`

Add fields:
- `expires_at`, `locked_at`, `locked_by`
- `db_dropped_at`, `superseded_at`, `superseded_by_job_id`

Add properties:
- `is_locked`, `is_expired`, `is_expiring()`, `maintenance_status`

#### Step 2.2: Update User Model
Add `last_maintenance_ack: date | None`

---

### Phase 3: Repository Layer

#### Step 3.1: Job Repository Extensions
**File**: `pulldb/infra/job_repo.py`

- `set_job_expiration()`
- `lock_job()` / `unlock_job()`
- `mark_db_dropped()`
- `supersede_job()`
- `get_maintenance_items()`
- `get_cleanup_candidates()`
- `get_locked_by_target()`
- `get_all_locked_databases()`

#### Step 3.2: User Repository Extensions
**File**: `pulldb/infra/user_repo.py`

- `get_last_maintenance_ack()`
- `set_last_maintenance_ack()`

---

### Phase 4: Business Logic (Features Layer)

#### Step 4.1: Retention Service
**File**: `pulldb/worker/retention.py` (new)

- `extend_job()`
- `lock_job()` / `unlock_job()`
- `mark_for_removal()`
- `check_target_locked()`
- `process_maintenance_acknowledgment()`

#### Step 4.2: Scheduled Cleanup Logic
**File**: `pulldb/worker/cleanup.py`

- `run_retention_cleanup()`

#### Step 4.3: Restore Blocking for Locked Targets
Modify job submission to reject if target is locked.

---

### Phase 5: Admin Task Integration

#### Step 5.1: Add Task Type
`AdminTaskType.RETENTION_CLEANUP`

#### Step 5.2: Task Executor Handler
In `AdminTaskExecutor.execute()`

#### Step 5.3: CLI Command
`pulldb-admin cleanup-retention`

---

### Phase 6: Web UI - Maintenance Modal

#### Step 6.1: Maintenance Exception
`MaintenanceRequiredError`

#### Step 6.2: Auth Dependency Check
Check on login if maintenance modal needed

#### Step 6.3: Exception Handler
Redirect to `/maintenance`

#### Step 6.4: Maintenance Page Template
**File**: `pulldb/web/templates/features/maintenance/maintenance.html` (new)

#### Step 6.5: Maintenance Routes
**File**: `pulldb/web/routes/maintenance.py` (new)

- `GET /maintenance`
- `POST /maintenance`

---

### Phase 7: Web UI - Active Jobs Updates

#### Step 7.1: Jobs Template Updates
- Add "Expires" column
- Add status badges
- Add action buttons

#### Step 7.2: Jobs Route Updates
- `POST /jobs/{job_id}/extend`
- `POST /jobs/{job_id}/lock`
- `POST /jobs/{job_id}/unlock`

---

### Phase 8: Admin UI Updates

#### Step 8.1: Settings Page
Add retention settings section

#### Step 8.2: Manager Report Page
**File**: `pulldb/web/templates/features/admin/locked_databases.html` (new)

- `GET /admin/locked-databases`

---

### Phase 9: Systemd Timer for Cleanup

#### Step 9.1: Timer Unit
**File**: `packaging/systemd/pulldb-cleanup.timer` (new)

#### Step 9.2: Service Unit  
**File**: `packaging/systemd/pulldb-cleanup.service` (new)

---

## Decisions Made

| Decision | Choice |
|----------|--------|
| Backfill existing jobs | ✅ Yes - set `expires_at = completed_at + max_retention_months` |
| Audit logging | ✅ Yes - all actions logged to `job_events` |
| API endpoints | ✅ Yes - extend/lock/unlock exposed for CLI integration |
| Modal required actions | ❌ No - all optional, Acknowledge always available |

---

## Files to Create

- `schema/pulldb_service/008_database_retention.sql`
- `pulldb/worker/retention.py`
- `pulldb/web/templates/features/maintenance/maintenance.html`
- `pulldb/web/routes/maintenance.py`
- `pulldb/web/templates/features/admin/locked_databases.html`
- `packaging/systemd/pulldb-cleanup.timer`
- `packaging/systemd/pulldb-cleanup.service`
- `scripts/trigger_retention_cleanup.py`

## Files to Modify

- `pulldb/domain/settings_registry.py`
- `pulldb/domain/models.py`
- `pulldb/infra/settings_repo.py`
- `pulldb/infra/job_repo.py`
- `pulldb/infra/user_repo.py`
- `pulldb/worker/cleanup.py`
- `pulldb/worker/admin_tasks.py`
- `pulldb/worker/service.py`
- `pulldb/auth/dependencies.py`
- `pulldb/web/main.py`
- `pulldb/web/routes/jobs.py`
- `pulldb/web/routes/admin.py`
- `pulldb/web/templates/features/jobs/jobs.html`
- `pulldb/web/templates/features/admin/settings.html`
- `pulldb/api/logic.py`
- `pulldb/cli/admin.py`
