# Admin Tasks System

> **Version**: 1.0.1 | **Last Updated**: January 2026

The Admin Tasks system provides asynchronous execution of long-running administrative operations with progress tracking and single-task enforcement.

---

## Table of Contents

1. [Overview](#overview)
2. [Task Types](#task-types)
3. [Task Lifecycle](#task-lifecycle)
4. [Single-Task Enforcement](#single-task-enforcement)
5. [Web UI Guide](#web-ui-guide)
6. [API Reference](#api-reference)
7. [Worker Execution](#worker-execution)

---

## Overview

### Purpose

Admin tasks enable operations that:
- Take too long for synchronous API responses
- Affect multiple records (bulk operations)
- Require progress tracking
- Need to be cancellable

### Key Features

- **Asynchronous execution**: Tasks run in background
- **Progress tracking**: Real-time percentage and status
- **Single-task enforcement**: Only one task at a time
- **Cancellation support**: Cancel running tasks
- **Result capture**: Store operation results

---

## Task Types

### Available Task Types

| Task Type | Purpose | Duration |
|-----------|---------|----------|
| `force_delete_user` | Delete user and all their data | Medium |
| `scan_user_orphans` | Find orphaned databases | Long |
| `bulk_delete_jobs` | Delete multiple jobs | Medium |
| `retention_cleanup` | Clean expired databases | Long |

### force_delete_user

**Purpose:** Completely remove a user from the system.

**What it deletes:**
- All user's jobs (and their databases)
- All user's feature requests
- All user's votes
- User audit log entries
- User record itself

**Parameters:**
```json
{
  "task_type": "force_delete_user",
  "params": {
    "user_id": 123
  }
}
```

**Progress:**
```
0%   - Started
20%  - Deleting jobs
50%  - Deleting feature requests
70%  - Deleting audit entries
90%  - Deleting user record
100% - Complete
```

### scan_user_orphans

**Purpose:** Find databases that exist on hosts but don't have corresponding job records.

**What it scans:**
- All registered MySQL hosts
- All databases matching pulldb pattern
- Cross-reference with jobs table

**Parameters:**
```json
{
  "task_type": "scan_user_orphans",
  "params": {
    "host_id": null  // null = scan all hosts
  }
}
```

**Result:**
```json
{
  "orphans_found": 5,
  "orphans": [
    {"host": "staging-01", "database": "pulldb_jsmith_customers_123"},
    ...
  ]
}
```

### bulk_delete_jobs

**Purpose:** Delete multiple jobs in a single operation.

**Use cases:**
- Cleanup failed jobs
- Remove all jobs for a source
- Mass deletion before host decommission

**Parameters:**
```json
{
  "task_type": "bulk_delete_jobs",
  "params": {
    "job_ids": [1, 2, 3, 4, 5]
  }
}
```

**Progress:**
Reports percentage based on jobs processed.

### retention_cleanup

**Purpose:** Process all expired databases for deletion.

**What it does:**
1. Finds all jobs where `status = 'deployed'` and `expiry_at < now()`
2. Marks each as `expired`
3. Drops the database
4. Marks as `deleted`

**Parameters:**
```json
{
  "task_type": "retention_cleanup",
  "params": {
    "dry_run": false
  }
}
```

**Result:**
```json
{
  "processed": 15,
  "deleted": 14,
  "errors": 1,
  "error_details": [
    {"job_id": 99, "error": "Database drop failed"}
  ]
}
```

---

## Task Lifecycle

### Task States

| State | Description |
|-------|-------------|
| `pending` | Queued, waiting for worker |
| `running` | Currently executing |
| `completed` | Finished successfully |
| `failed` | Finished with error |
| `cancelled` | User cancelled |

### State Transitions

```
pending ──► running ──┬──► completed
                      │
                      ├──► failed
                      │
                      └──► cancelled
```

### Progress Tracking

Tasks report progress as:
- **percentage** (0-100): Overall completion
- **message**: Current operation description
- **result**: Final output (on completion)
- **error**: Error message (on failure)

```json
{
  "id": "task_abc123",
  "task_type": "retention_cleanup",
  "state": "running",
  "progress": 45,
  "message": "Processing job 23 of 51",
  "created_at": "2026-01-15T10:00:00Z",
  "started_at": "2026-01-15T10:00:05Z"
}
```

---

## Single-Task Enforcement

### Why Single-Task?

- Prevents resource contention
- Ensures predictable execution
- Simplifies cancellation logic
- Avoids conflicting operations

### How It Works

1. **Before creating task**: Check for existing pending/running tasks
2. **If task exists**: Return 409 Conflict with existing task info
3. **If no task**: Create new task, return 201 Created
4. **Worker**: Only picks up tasks when none running

### API Response (409 Conflict)

```json
{
  "error": "Admin task already in progress",
  "existing_task": {
    "id": "task_abc123",
    "task_type": "retention_cleanup",
    "state": "running",
    "progress": 45
  }
}
```

### Workaround

To run a new task when one is running:
1. Cancel the current task
2. Wait for cancellation to complete
3. Create new task

---

## Web UI Guide

### Accessing Admin Tasks

**Navigation:** Admin → Background Tasks

### Task Status Page

Shows:
- Current task (if any) with live progress
- Task history (recent completed/failed/cancelled)
- Create new task button (disabled if task running)

### Progress Display

```
┌────────────────────────────────────────────────────┐
│ Retention Cleanup                        Running   │
│ ████████████████████░░░░░░░░░░░░░░░░░░░  45%      │
│ Processing job 23 of 51                           │
│                                                    │
│ Started: 2 minutes ago                             │
│                                          [Cancel]  │
└────────────────────────────────────────────────────┘
```

### Creating a Task

1. Click **+ New Task**
2. Select task type from dropdown
3. Fill in parameters (varies by type)
4. Click **Start Task**

### Cancelling a Task

1. Find running task
2. Click **Cancel**
3. Confirm in modal
4. Task state changes to `cancelled`

Note: Cancellation is best-effort. Some operations may complete before cancellation takes effect.

### Viewing Results

1. Click on completed task in history
2. View result JSON
3. For scan_user_orphans: clickable orphan list

---

## API Reference

### Get Current Task

```
GET /api/admin/tasks/current
```

**Response (task running):**
```json
{
  "task": {
    "id": "task_abc123",
    "task_type": "retention_cleanup",
    "state": "running",
    "progress": 45,
    "message": "Processing job 23 of 51",
    "params": {"dry_run": false},
    "created_at": "2026-01-15T10:00:00Z",
    "started_at": "2026-01-15T10:00:05Z"
  }
}
```

**Response (no task):**
```json
{
  "task": null
}
```

### Create Task

```
POST /api/admin/tasks
```

**Request:**
```json
{
  "task_type": "retention_cleanup",
  "params": {
    "dry_run": false
  }
}
```

**Response (201 Created):**
```json
{
  "task": {
    "id": "task_abc123",
    "task_type": "retention_cleanup",
    "state": "pending",
    ...
  }
}
```

**Response (409 Conflict):**
```json
{
  "error": "Admin task already in progress",
  "existing_task": {...}
}
```

### Get Task Status

```
GET /api/admin/tasks/{task_id}
```

### Cancel Task

```
POST /api/admin/tasks/{task_id}/cancel
```

### List Task History

```
GET /api/admin/tasks?page=1&page_size=20
```

---

## Worker Execution

### Task Processing Flow

```
1. Worker polls admin_tasks table
2. Claims pending task (UPDATE with worker_id)
3. Executes task type handler
4. Updates progress periodically
5. Marks completed/failed on finish
```

### Implementation Details

**Polling interval:** 10 seconds

**Progress update frequency:** Every 10 items or 5 seconds

**Cancellation check:** Before each major operation

### Error Handling

- Errors are caught and logged
- Task marked `failed` with error message
- Partial results preserved where possible
- Worker continues to process other work

### Worker Code Location

See [worker/service.py](../../pulldb/worker/service.py) for task execution logic.

---

## Database Schema

```sql
CREATE TABLE admin_tasks (
  id VARCHAR(36) PRIMARY KEY,
  task_type ENUM('force_delete_user', 'scan_user_orphans', 
                 'bulk_delete_jobs', 'retention_cleanup'),
  state ENUM('pending', 'running', 'completed', 'failed', 'cancelled'),
  progress INT DEFAULT 0,
  message TEXT,
  params JSON,
  result JSON,
  error TEXT,
  created_by_user_id INT,
  worker_id VARCHAR(36),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME,
  completed_at DATETIME,
  
  FOREIGN KEY (created_by_user_id) REFERENCES auth_users(id)
);
```

---

## See Also

- [Admin Guide](../pages/admin-guide.md) - Administrative workflows
- [Database Lifecycle](database-lifecycle.md) - Retention and deletion
- [API Reference](../pages/api-reference.md#admin-tasks) - Full API docs
