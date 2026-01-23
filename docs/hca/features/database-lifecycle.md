# Database Lifecycle Management

> **Version**: 1.0.1 | **Last Updated**: January 2026

Comprehensive guide to job status states, retention policies, locking mechanisms, and database cleanup workflows.

---

## Table of Contents

1. [Job Status State Machine](#job-status-state-machine)
2. [Retention System](#retention-system)
3. [Locking Mechanism](#locking-mechanism)
4. [Supersession](#supersession)
5. [Deletion Workflow](#deletion-workflow)
6. [Web UI Guide](#web-ui-guide)
7. [API Reference](#api-reference)

---

## Job Status State Machine

### All Job Statuses

| Status | Category | Description |
|--------|----------|-------------|
| `queued` | Active | Waiting to start |
| `running` | Active | Restore in progress |
| `canceling` | Active | Cancel requested, in progress |
| `deployed` | Active | Database ready for use |
| `expired` | Terminal | Retention period exceeded |
| `failed` | Terminal | Restore failed |
| `complete` | Terminal | Successfully completed (older term) |
| `canceled` | Terminal | User canceled |
| `deleting` | Transition | Database being dropped |
| `deleted` | Terminal | Database dropped |
| `superseded` | Terminal | Replaced by newer restore |

### State Transition Diagram

```
                                      ┌─────────────┐
                                      │   queued    │
                                      └──────┬──────┘
                                             │ Worker picks up
                                             ▼
                      ┌───────────────┬─────────────┬───────────────┐
                      │               │   running   │               │
                      │               └──────┬──────┘               │
                      │                      │                      │
            User cancels                     │ Success         Failure
                      │                      │                      │
                      ▼                      ▼                      ▼
               ┌───────────┐         ┌─────────────┐         ┌─────────┐
               │ canceling │         │  deployed   │         │ failed  │
               └─────┬─────┘         └──────┬──────┘         └─────────┘
                     │                      │
                     │              ┌───────┴───────┐
               Cleanup done         │               │
                     │         Retention        User locks
                     ▼         exceeded              │
               ┌──────────┐        │                ▼
               │ canceled │        ▼         ┌───────────────┐
               └──────────┘  ┌─────────┐     │  deployed     │
                             │ expired │     │  (locked)     │
                             └────┬────┘     └───────┬───────┘
                                  │                  │
                                  │           User unlocks
                                  │           or delete
                                  │                  │
                                  ▼                  ▼
                            ┌──────────┐      ┌──────────┐
                            │ deleting │◄─────┤ deleting │
                            └────┬─────┘      └──────────┘
                                 │
                                 ▼
                            ┌──────────┐
                            │ deleted  │
                            └──────────┘

   ┌─────────────────────────────────────────────────────────────────┐
   │ Supersession: When same user restores same source database,     │
   │ older deployed job → superseded                                 │
   └─────────────────────────────────────────────────────────────────┘
```

### Status Categories

```json
{
  "all": ["queued", "running", "canceling", "deployed", "expired", 
          "failed", "complete", "canceled", "deleting", "deleted", "superseded"],
  "active": ["queued", "running", "canceling", "deployed"],
  "terminal": ["expired", "failed", "complete", "canceled", "deleted", "superseded"],
  "deletable": ["deployed", "expired", "failed", "complete"]
}
```

---

## Retention System

### How Retention Works

1. **expires_at** calculated at deployment: `now() + default_retention_days`
2. Worker periodically scans for `expires_at < now()` where status = `complete`
3. After `cleanup_grace_days`, expired jobs are cleaned up

### Retention Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `default_retention_days` | 7 | Default expiration for new restores |
| `max_retention_days` | 180 | Maximum retention allowed (~6 months) |
| `expiring_warning_days` | 7 | Days before expiry to show warning |
| `cleanup_grace_days` | 7 | Days after expiry before cleanup |

### User Controls

**View remaining time:**
- Dashboard shows "Expires in X days"
- Job detail shows exact `expires_at` timestamp

**Extend retention:**
- Click **Extend** on deployed database
- Select new duration (up to max_retention_days)
- Each extension resets expires_at from current time

---

## Locking Mechanism

### Purpose

Locking prevents automatic deletion when retention expires. Use for:
- Critical databases needed beyond retention
- Databases under active investigation
- Long-running projects

### Lock States

| State | Description | Auto-Delete |
|-------|-------------|-------------|
| Unlocked | Normal state | Yes, at expiry |
| Locked | Protected | No |

### User Actions

**Lock a database:**
```bash
# CLI
pulldb lock <job_id>

# API
POST /api/jobs/{job_id}/lock
```

**Unlock a database:**
```bash
# CLI
pulldb unlock <job_id>

# API
POST /api/jobs/{job_id}/unlock
```

**Web UI:**
- Lock icon on deployed databases
- Click to toggle lock state
- Locked databases show lock badge

### Admin Override

Admins can:
- Unlock any user's database
- Force delete locked databases
- View all locked databases in admin panel

### Best Practices

1. **Don't over-lock** - Locks bypass cleanup, causing disk usage growth
2. **Set reminders** - Locked databases exist indefinitely
3. **Periodic review** - Admin should review locked databases regularly
4. **Document reason** - Note why database was locked

---

## Supersession

### What is Supersession?

When a user restores the **same source database** while they already have a `deployed` version:
1. New restore proceeds normally
2. Old deployed database marked `superseded`
3. Superseded database queued for deletion

### Supersession Rules

- Same user
- Same source host
- Same source database
- Older job status = `deployed`

### Why Supersede?

- Prevents accumulation of stale databases
- Ensures user always has latest data
- Automatic cleanup without user intervention

### Example Flow

```
1. User restores prod.customers → job_001 deployed
2. (3 days later)
3. User restores prod.customers again → job_002 starts
4. job_002 deploys → job_001 marked superseded
5. job_001 automatically deleted
```

### Opt-Out

Users can prevent supersession by:
- Using `--custom-target` with unique name
- Keeping multiple custom-named databases

---

## Deletion Workflow

### Deletion Triggers

| Trigger | Description |
|---------|-------------|
| **Retention expiry** | `expiry_at < now()` (if unlocked) |
| **Supersession** | Newer restore deployed |
| **User delete** | Explicit user action |
| **Admin delete** | Admin cleanup |
| **Cancel** | Job canceled mid-restore |

### Deletion Process

```
1. Job marked 'deleting'
2. Worker executes DROP DATABASE
3. Job marked 'deleted'
4. Database record retained for history
```

### Cleanup Operations

**Orphan Detection:**
- Databases without job records
- Jobs pointing to dropped databases
- Detected via reconciliation scan

**Admin Cleanup Tools:**
- Prune job history logs
- Cleanup staging databases
- Scan for orphan databases
- User orphan scan

---

## Web UI Guide

### Dashboard Status Indicators

| Badge | Meaning |
|-------|---------|
| 🟢 Deployed | Ready to use |
| 🟡 Queued | Waiting to start |
| 🔵 Running | In progress |
| 🔴 Failed | Restore failed |
| ⚫ Expired | Retention exceeded |
| 🔒 Locked | Protected from deletion |

### Extending Retention

1. Navigate to **My Databases**
2. Find the deployed database
3. Click **⏱ Extend**
4. Select new duration from dropdown
5. Confirm

### Locking/Unlocking

1. Navigate to **My Databases**
2. Find the deployed database
3. Click the **lock icon** (🔓 unlocked / 🔒 locked)
4. State toggles immediately

### Deleting a Database

1. Navigate to **My Databases**
2. Find the database (deployed, expired, or failed)
3. Click **🗑 Delete**
4. Confirm in modal

### Viewing History

- Toggle **Show All** to include deleted/superseded
- Filter by status to find specific states
- Sort by date to see timeline

---

## API Reference

### Get Job Status

```
GET /api/jobs/{job_id}
```

**Response includes:**
```json
{
  "status": "deployed",
  "locked": false,
  "expiry_at": "2026-01-15T10:00:00Z",
  "retention_hours": 168
}
```

### Lock Database

```
POST /api/jobs/{job_id}/lock
```

### Unlock Database

```
POST /api/jobs/{job_id}/unlock
```

### Extend Retention

```
POST /api/jobs/{job_id}/extend
```

**Request:**
```json
{
  "hours": 48
}
```

### Delete Database

```
DELETE /api/jobs/{job_id}
```

### Admin: Force Delete

```
DELETE /api/admin/jobs/{job_id}?force=true
```

### Admin: Get Orphan Databases

```
GET /api/admin/orphan-databases?page=1&page_size=50
```

---

## Database Schema

Key columns in `jobs` table:

```sql
status ENUM('queued', 'running', 'canceling', 'deployed', 
            'expired', 'failed', 'complete', 'canceled', 
            'deleting', 'deleted', 'superseded')

locked BOOLEAN DEFAULT FALSE
expiry_at DATETIME
retention_hours INT
```

---

## See Also

- [Admin Guide](../pages/admin-guide.md#database-lifecycle-management) - Admin operations
- [CLI Reference](../pages/cli-reference.md) - Command line usage
- [API Reference](../pages/api-reference.md#database-lifecycle) - Full API docs
