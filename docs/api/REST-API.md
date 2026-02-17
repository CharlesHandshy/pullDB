# pullDB REST API Reference

[← Back to API Index](README.md) | [Web API Reference](WEB-API.md)

> **Version**: 1.1.0  
> **Base URL**: `http://localhost:8080`  
> **Authentication**: HMAC Signature or Session Cookie  
> **Source**: [pulldb/api/main.py](../../pulldb/api/main.py)

---

## Table of Contents

1. [Authentication](#authentication)
2. [Health & Status](#health--status)
3. [Authentication Endpoints](#authentication-endpoints)
4. [Users](#users)
5. [Hosts](#hosts)
6. [Jobs](#jobs)
7. [Job Lifecycle](#job-lifecycle)
8. [Manager Endpoints](#manager-endpoints)
9. [Admin Endpoints](#admin-endpoints)
10. [Dropdown Search](#dropdown-search)
11. [Backup Discovery](#backup-discovery)
12. [Feature Requests](#feature-requests)
13. [Response Models](#response-models)
14. [Multi-Language Examples](#multi-language-examples)

---

## Authentication

pullDB uses HMAC-signed requests for CLI/programmatic access and session cookies for Web UI.

### HMAC Authentication (CLI)

Include these headers with each request:

| Header | Description |
|--------|-------------|
| `X-API-Key` | Your API key ID |
| `X-Timestamp` | ISO 8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`) |
| `X-Signature` | HMAC-SHA256 of `{method}:{path}:{timestamp}` with your API secret |

**Bash Example:**
```bash
# Generate signature
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
SIGNATURE=$(echo -n "GET:/api/status:$TIMESTAMP" | openssl dgst -sha256 -hmac "$API_SECRET" | awk '{print $2}')

curl -H "X-API-Key: $API_KEY" \
     -H "X-Timestamp: $TIMESTAMP" \
     -H "X-Signature: $SIGNATURE" \
     http://localhost:8080/api/status
```

**Python Example:**
```python
import hashlib
import hmac
from datetime import datetime, timezone

def generate_signature(method: str, path: str, timestamp: str, secret: str) -> str:
    payload = f"{method}:{path}:{timestamp}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
signature = generate_signature("GET", "/api/status", timestamp, API_SECRET)

headers = {
    "X-API-Key": API_KEY,
    "X-Timestamp": timestamp,
    "X-Signature": signature,
}
response = requests.get("http://localhost:8080/api/status", headers=headers)
```

**PHP Example:**
```php
$timestamp = gmdate('Y-m-d\TH:i:s\Z');
$payload = "GET:/api/status:{$timestamp}";
$signature = hash_hmac('sha256', $payload, $apiSecret);

$headers = [
    "X-API-Key: {$apiKey}",
    "X-Timestamp: {$timestamp}",
    "X-Signature: {$signature}",
];

$ch = curl_init('http://localhost:8080/api/status');
curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
$response = curl_exec($ch);
```

### Session Authentication (Web UI)

Use `session_token` httponly cookie from login.

---

## Health & Status

### `GET /api/health`

Health check endpoint. No authentication required.

**Response:**
```json
{"status": "ok"}
```

---

### `GET /api/status`

Get service status and queue depth.

**Authentication:** Required

**Response:**
```json
{
  "queue_depth": 3,
  "active_restores": 3,
  "service": "api"
}
```

---

## Authentication Endpoints

### `GET /api/auth/user-exists/{username}`

Check if a username is registered. **No authentication required.**

Used by CLI `pulldb register` to determine whether to create a new user or request a new host key for an existing user.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `username` | string | Username to check |

**Response Model:** `UserExistsResponse`
```json
{
  "exists": true,
  "user_code": "charly"
}
```

---

### `POST /api/auth/register`

Self-register a new user account. **No authentication required.**

Creates account in DISABLED state pending admin approval.

**Request Body:** `RegisterRequest`
```json
{
  "username": "jdoe",
  "password": "securePassword123",
  "host_name": "devbox01"
}
```

**Response Model:** `RegisterResponse` (201 Created)
```json
{
  "username": "jdoe",
  "user_code": "jdoe",
  "message": "Account created successfully. Contact an administrator to enable your account.",
  "api_key": "pk_abc123...",
  "api_secret": "sk_xyz789..."
}
```

**Errors:**
- `400 Bad Request` - Invalid username format or disallowed username
- `409 Conflict` - User already exists

---

### `POST /api/auth/change-password`

Change user password. **No authentication required** (uses password verification).

**Request Body:** `ChangePasswordRequest`
```json
{
  "username": "jdoe",
  "current_password": "oldPassword123",
  "new_password": "newSecurePassword456"
}
```

**Response:**
```json
{"message": "Password changed successfully"}
```

**Notes:**
- If user has no password set (new account), `current_password` is ignored
- If `password_reset_at` is set, any `current_password` is accepted

---

### `POST /api/auth/request-host-key`

Request an API key for a new host machine. Used when setting up CLI access from a second machine.

**Request Body:** `RequestHostKeyRequest`
```json
{
  "username": "jdoe",
  "password": "myPassword123",
  "host_name": "laptop02"
}
```

**Response Model:** `RequestHostKeyResponse`
```json
{
  "username": "jdoe",
  "user_code": "jdoe",
  "host_name": "laptop02",
  "api_key": "pk_def456...",
  "api_secret": "sk_mno012...",
  "message": "API key created successfully. Contact an administrator to approve the key before it can be used."
}
```

**Notes:**
- Key is created in PENDING state
- Admin must approve before key can be used

---

## Users

### `GET /api/users/{username}`

Get user information by username.

**Authentication:** Required

**Purpose:** Look up user details including user_code. Used by CLI to display user identity when running under sudo.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `username` | string | The username to look up |

**Response Model:** `UserInfoResponse`
```json
{
  "username": "jdoe",
  "user_code": "jdoe",
  "is_admin": false,
  "is_disabled": false,
  "has_password": true,
  "role": "user"
}
```

**Errors:**
| Code | Description |
|------|-------------|
| 404 | User not found |

---

### `GET /api/users/{user_code}/last-job`

Get the most recently submitted job for a user.

**Authentication:** Required

**Purpose:** Returns the user's last job regardless of status (queued, running, complete, failed, or canceled). Useful for CLI status checks and displaying recent activity.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `user_code` | string | The 6-character user code |

**Response Model:** `UserLastJobResponse`
```json
{
  "job_id": "8b4c4a3a-85a1-4da2-9f3c-abc123def456",
  "target": "acme_jdoe",
  "status": "complete",
  "submitted_at": "2026-01-21T10:30:00Z",
  "started_at": "2026-01-21T10:31:00Z",
  "completed_at": "2026-01-21T10:45:00Z",
  "error_detail": null,
  "found": true
}
```

If no jobs exist for the user:
```json
{
  "found": false
}
```

---

## Hosts

### `GET /api/hosts`

List available database hosts for restore targets.

**Authentication:** Required

**Response Model:** `HostsListResponse`
```json
{
  "hosts": [
    {
      "hostname": "mysql-dev.example.com",
      "alias": "dev",
      "enabled": true
    }
  ],
  "total": 1,
  "default_host": "mysql-dev.example.com",
  "default_alias": "dev"
}
```

---

## Jobs

### `POST /api/jobs`

Submit a new restore job.

**Authentication:** Required

**Request Body:** `JobRequest`
```json
{
  "user": "jdoe",
  "customer": "acme",
  "qatemplate": false,
  "dbhost": "dev",
  "date": "2026-01-15",
  "env": "prod",
  "overwrite": false,
  "suffix": "ab",
  "backup_path": null,
  "custom_target": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user` | string | Yes | Username submitting the job |
| `customer` | string | No* | Customer ID for backup lookup |
| `qatemplate` | boolean | No | Use QA template instead of customer backup |
| `dbhost` | string | No | Target database host alias |
| `date` | string | No | Specific backup date (YYYY-MM-DD) |
| `env` | string | No | S3 environment: "staging" or "prod" |
| `overwrite` | boolean | No | Overwrite existing database |
| `suffix` | string | No | 1-3 letter suffix for target name |
| `backup_path` | string | No | Full S3 path to specific backup |
| `custom_target` | string | No | Custom database name (1-51 lowercase letters) |

*Either `customer` or `qatemplate=true` is required

**Response Model:** `JobResponse` (201 Created)
```json
{
  "job_id": "8b4c4a3a-85a1-4da2-9f3c-abc123def456",
  "target": "acme_jdoe",
  "staging_name": "staging_8b4c4a3a",
  "status": "queued",
  "owner_username": "jdoe",
  "owner_user_code": "jdoe",
  "submitted_at": "2026-01-21T10:30:00Z",
  "original_customer": "acme-international-corp",
  "customer_normalized": true,
  "normalization_message": "Customer name truncated from 23 to 20 characters",
  "custom_target_used": false
}
```

---

### `GET /api/jobs`

List jobs with optional filtering.

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 100 | Max results (1-1000) |
| `active` | bool | false | Include active jobs (queued, running, deployed) |
| `history` | bool | false | Include completed/failed/canceled jobs |
| `filter` | string | null | JSON filter object |

**Response:** `list[JobSummary]`

---

### `GET /api/jobs/active`

List currently active jobs (queued, running, deployed).

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 100 | Max results (1-1000) |

**Response:** `list[JobSummary]`

---

### `GET /api/jobs/paginated`

Paginated jobs for LazyTable widget with server-side sorting/filtering.

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 0 | Page number (0-indexed) |
| `pageSize` | int | 50 | Results per page (10-200) |
| `view` | string | "active" | "active" or "history" |
| `sortColumn` | string | null | Column to sort by |
| `sortDirection` | string | null | "asc" or "desc" |
| `filter_status` | string | null | Filter by status (comma-separated) |
| `filter_dbhost` | string | null | Filter by host (comma-separated) |
| `filter_user_code` | string | null | Filter by user (comma-separated) |
| `filter_target` | string | null | Filter by target substring |
| `filter_id` | string | null | Filter by job ID (wildcards: *) |
| `filter_submitted_at` | string | null | Filter by date MM/DD/YYYY (wildcards: *) |
| `days` | int | 30 | History retention days (1-365) |

**Response Model:** `PaginatedJobsResponse`
```json
{
  "rows": [...],
  "totalCount": 150,
  "filteredCount": 45,
  "page": 0,
  "pageSize": 50
}
```

---

### `GET /api/jobs/paginated/distinct`

Get distinct values for a column (for cascading filter dropdowns).

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `column` | string | Column to get distinct values for |
| `view` | string | "active" or "history" |
| `filter_order` | string | Comma-separated filter order for cascading |

**Response:** `list[string]`

---

### `GET /api/jobs/search`

Search jobs by ID, target, username, or user code.

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | - | Search query (min 4 chars) |
| `limit` | int | 50 | Max results (1-200) |
| `exact` | bool | false | Require exact match |

**Response Model:** `JobSearchResponse`
```json
{
  "query": "acme",
  "count": 5,
  "exact_match": false,
  "jobs": [...]
}
```

---

### `GET /api/jobs/my-last`

Get the most recent job submitted by a user.

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `user_code` | string | User code to look up |

**Response Model:** `LastJobResponse`
```json
{
  "job": {...},
  "user_code": "jdoe"
}
```

---

### `GET /api/jobs/history`

Get job history with filtering and retention policy.

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 100 | Max results (1-1000) |
| `days` | int | 30 | Retention period (1-365) |
| `user_code` | string | null | Filter by user code |
| `target` | string | null | Filter by target database |
| `dbhost` | string | null | Filter by database host |
| `status` | string | null | Filter: complete, failed, canceled |

**Response:** `list[JobHistoryItem]`

---

### `GET /api/jobs/resolve/{prefix}`

Resolve a job ID prefix to full job ID.

**Authentication:** Required

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `prefix` | string | Job ID prefix (min 8 chars) |

**Response Model:** `JobResolveResponse`
```json
{
  "resolved_id": "8b4c4a3a-85a1-4da2-9f3c-abc123def456",
  "matches": [...],
  "count": 1
}
```

---

### `GET /api/jobs/{job_id}`

Get a single job by ID.

**Authentication:** Required

**Response Model:** `JobSummary`

---

### `GET /api/jobs/{job_id}/events`

Get job events for streaming progress.

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `since_id` | int | Only return events after this ID |

**Response:** `list[JobEventResponse]`

---

### `GET /api/jobs/{job_id}/profile`

Get performance profile for a completed job.

**Authentication:** Required

**Response Model:** `JobProfileResponse`
```json
{
  "job_id": "8b4c4a3a-...",
  "started_at": "2026-01-21T10:30:00Z",
  "completed_at": "2026-01-21T10:45:00Z",
  "total_duration_seconds": 900.5,
  "total_bytes": 5368709120,
  "phases": {
    "download": {...},
    "extraction": {...},
    "myloader": {...}
  },
  "phase_breakdown_percent": {
    "download": 15.2,
    "extraction": 8.3,
    "myloader": 72.1
  }
}
```

---

## Job Lifecycle

### `POST /api/jobs/{job_id}/cancel`

Request cancellation of a job.

**Authentication:** Required  
**Authorization:** Job owner, their manager, or admin

**Response Model:** `CancelResponse`
```json
{
  "job_id": "8b4c4a3a-...",
  "status": "canceled",
  "message": "Job canceled successfully (was queued)"
}
```

**Cancellation Behavior:**
- `QUEUED`: Immediate cancellation
- `RUNNING` (pre-restore): Transitions to CANCELING, worker stops at checkpoint
- `RUNNING` (restore started): Rejected - myloader cannot be interrupted

---

### `POST /api/jobs/{job_id}/extend`

Extend retention period for a job's database.

**Authentication:** Required  
**Authorization:** Job owner or admin

**Request Body:** `ExtendRetentionRequest`
```json
{
  "days": 7
}
```

**Response Model:** `RetentionActionResponse`
```json
{
  "success": true,
  "message": "Extended retention by 7 day(s)",
  "job_id": "8b4c4a3a-...",
  "expires_at": "2026-01-28T10:30:00Z",
  "locked_at": null,
  "locked_by": null
}
```

---

### `POST /api/jobs/{job_id}/lock`

Lock a job database to prevent automatic cleanup.

**Authentication:** Required  
**Authorization:** Job owner or admin

**Request Body:** `LockJobRequest`
```json
{
  "reason": "Preserving for investigation"
}
```

**Response Model:** `RetentionActionResponse`

---

### `POST /api/jobs/{job_id}/unlock`

Unlock a job database to allow cleanup.

**Authentication:** Required  
**Authorization:** Job owner or admin

**Response Model:** `RetentionActionResponse`

---

## Manager Endpoints

### `GET /api/manager/team`

Get paginated team members for a manager.

**Authentication:** Required  
**Authorization:** Manager or Admin role

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 0 | Page number |
| `pageSize` | int | 50 | Results per page |
| `sortColumn` | string | null | Column to sort by |
| `sortDirection` | string | null | "asc" or "desc" |
| `filter_username` | string | null | Filter by username |
| `filter_user_code` | string | null | Filter by user code |
| `filter_status` | string | null | "active" or "disabled" |

**Response Model:** `PaginatedTeamResponse`

---

### `GET /api/manager/team/distinct`

Get distinct values for team table columns.

**Authentication:** Required  
**Authorization:** Manager or Admin role

**Response:** `list[string]`

---

## Admin Endpoints

### `POST /api/admin/jobs/bulk-cancel`

Bulk cancel jobs matching filters.

**Authentication:** Required  
**Authorization:** Admin role

**Request Body:** `BulkCancelRequest`
```json
{
  "view": "active",
  "filter_status": "queued",
  "filter_dbhost": "dev",
  "filter_user_code": null,
  "filter_target": null,
  "confirmation": "CANCEL ALL"
}
```

**Response Model:** `BulkCancelResponse`
```json
{
  "canceled_count": 5,
  "skipped_count": 2,
  "message": "Canceled 5 job(s), skipped 2",
  "canceled_job_ids": [...]
}
```

---

### `GET /api/admin/keys/pending`

Get pending API keys awaiting approval.

**Authentication:** Required  
**Authorization:** Admin role

**Response Model:** `PendingKeysResponse`

---

### `POST /api/admin/keys/approve`

Approve a pending API key.

**Authentication:** Required  
**Authorization:** Admin role

**Response Model:** `ApproveKeyResponse`

---

### `POST /api/admin/keys/revoke`

Revoke an active API key.

**Authentication:** Required  
**Authorization:** Admin role

**Response Model:** `RevokeKeyResponse`

---

### `POST /api/admin/keys/reactivate`

Reactivate a revoked API key.

**Authentication:** Required  
**Authorization:** Admin role

**Response Model:** `ReactivateKeyResponse`

---

### `GET /api/admin/users/{user_id}/keys`

Get all API keys for a specific user.

**Authentication:** Required  
**Authorization:** Admin role

**Response Model:** `UserKeysResponse`

---

### `POST /api/admin/prune-logs`

Prune job events older than a retention period.

**Authentication:** Required  
**Authorization:** Admin role

**Purpose:** Admin maintenance operation. Only deletes events for terminal jobs (completed/failed/canceled). Events for active jobs are never pruned.

**Request Body:** `PruneLogsRequest`
```json
{
  "days": 90,
  "dry_run": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `days` | int | 90 | Retention period in days (1-365) |
| `dry_run` | bool | false | If true, return count without deleting |

**Response Model:** `PruneLogsResponse`
```json
{
  "deleted": 1523,
  "would_delete": 0,
  "retention_days": 90,
  "dry_run": false
}
```

---

### `POST /api/admin/cleanup-staging`

Clean up orphaned staging databases.

**Authentication:** Required  
**Authorization:** Admin role

**Purpose:** Admin maintenance operation. Scans database hosts for staging databases from jobs that completed/failed more than N days ago.

**Safety Checks:**
- Only removes staging DBs for terminal jobs (completed/failed/canceled)
- Skips if any active job exists for the target
- Logs all deletions to job_events

**Request Body:** `CleanupStagingRequest`
```json
{
  "days": 7,
  "dbhost": "dev",
  "dry_run": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `days` | int | 7 | Age threshold in days (1-365) |
| `dbhost` | string | null | Specific host to clean. If omitted, all enabled hosts are scanned |
| `dry_run` | bool | false | If true, return count without deleting |

**Response Model:** `CleanupStagingResponse`
```json
{
  "hosts_scanned": 3,
  "total_candidates": 12,
  "total_dropped": 12,
  "total_skipped": 0,
  "total_errors": 0,
  "retention_days": 7,
  "dry_run": false
}
```

---

### `GET /api/admin/orphan-databases`

Get report of orphan databases for admin review.

**Authentication:** Required  
**Authorization:** Admin role

**Purpose:** Orphan databases match the staging pattern but have NO corresponding job record. These are NEVER auto-deleted and require manual admin review before deletion.

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `dbhost` | string | Optional. Scan specific host only |

**Response Model:** `AllOrphansResponse`
```json
{
  "hosts_scanned": 3,
  "total_orphans": 5,
  "reports": [
    {
      "dbhost": "dev",
      "scanned_at": "2026-01-21T10:30:00Z",
      "orphans": [
        {
          "database_name": "staging_acme_8b4c4a3a",
          "target_name": "acme",
          "job_id_prefix": "8b4c4a3a",
          "dbhost": "dev",
          "size_mb": 256.5
        }
      ],
      "count": 1
    }
  ],
  "errors": []
}
```

---

### `GET /api/admin/orphan-databases/paginated`

Get paginated orphan databases for LazyTable display.

**Authentication:** Required  
**Authorization:** Admin role

**Purpose:** LazyTable-compatible endpoint for displaying orphan databases with pagination, sorting, and filtering.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 0 | Page number (0-indexed) |
| `pageSize` | int | 50 | Items per page |
| `sortColumn` | string | "database_name" | Sort column: `database_name`, `target_name`, `dbhost`, `size_mb` |
| `sortDirection` | string | "asc" | Sort direction: `asc` or `desc` |
| `filter_host` | string | null | Filter by specific host |
| `filter_target` | string | null | Filter by target name (substring match) |

**Response Model:** `PaginatedOrphansResponse`
```json
{
  "rows": [
    {
      "database_name": "staging_acme_8b4c4a3a",
      "target_name": "acme",
      "job_id_prefix": "8b4c4a3a",
      "dbhost": "dev",
      "size_mb": 256.5
    }
  ],
  "totalCount": 25,
  "filteredCount": 10,
  "page": 0,
  "pageSize": 50,
  "errors": []
}
```

---

### `GET /api/admin/orphan-databases/{dbhost}/{db_name}/meta`

Get metadata from pullDB table inside an orphan database.

**Authentication:** Required  
**Authorization:** Admin role

**Purpose:** Fetches restore information (who, when, what backup) from the pullDB table that is created during restore. Useful for understanding orphan origin before deletion.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `dbhost` | string | Database host |
| `db_name` | string | Database name |

**Response Model:** `OrphanMetadataResponse`
```json
{
  "found": true,
  "job_id": "8b4c4a3a-85a1-4da2-9f3c-abc123def456",
  "restored_by": "jdoe",
  "restored_at": "2026-01-15T10:30:00Z",
  "target_database": "acme_jdoe",
  "backup_filename": "s3://bucket/acme/2026-01-14.tar.zst",
  "restore_duration_seconds": 840.5
}
```

If metadata table doesn't exist (old restore or crash before completion):
```json
{
  "found": false
}
```

---

### `DELETE /api/admin/orphan-databases/{dbhost}/{db_name}`

Delete a single orphan database.

**Authentication:** Required  
**Authorization:** Admin role

**Purpose:** REST-style endpoint for deleting individual orphans via trash icon in UI.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `dbhost` | string | Database host |
| `db_name` | string | Database name to delete |

**Response Model:** `DeleteOrphansResponse`
```json
{
  "requested": 1,
  "succeeded": 1,
  "failed": 0,
  "results": {
    "staging_acme_8b4c4a3a": true
  }
}
```

---

### `POST /api/admin/delete-orphans`

Delete admin-approved orphan databases (bulk).

**Authentication:** Required  
**Authorization:** Admin role

**Purpose:** For databases that have been reviewed via the orphan-databases report and confirmed safe to delete. The admin_user field is logged for audit purposes.

**Request Body:** `DeleteOrphansRequest`
```json
{
  "dbhost": "dev",
  "database_names": ["staging_acme_8b4c4a3a", "staging_test_9c5d5b4b"],
  "admin_user": "admin@example.com"
}
```

**Response Model:** `DeleteOrphansResponse`
```json
{
  "requested": 2,
  "succeeded": 2,
  "failed": 0,
  "results": {
    "staging_acme_8b4c4a3a": true,
    "staging_test_9c5d5b4b": true
  }
}
```

---

### `POST /api/admin/hosts/{host_id}/rotate-secret`

Rotate credentials for a database host (admin only).

**Authentication:** Required  
**Authorization:** Admin role

**Purpose:** Performs a safe, atomic credential rotation:
1. Fetches current credentials from AWS Secrets Manager
2. Validates current credentials work on MySQL
3. Verifies user has ALTER USER privilege
4. Generates or uses provided new password
5. Updates MySQL user password (ALTER USER)
6. Verifies new password works
7. Updates AWS Secrets Manager
8. Verifies round-trip (AWS → MySQL)

**FAIL HARD:** Any failure returns detailed diagnostic information. If MySQL succeeds but AWS fails, provides manual fix instructions.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `host_id` | string | Host ID to rotate |

**Request Body:** `RotateHostSecretRequest`
```json
{
  "new_password": null,
  "password_length": 32
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `new_password` | string | null | Explicit new password. If not provided, a secure random password is generated |
| `password_length` | int | 32 | Length of generated password (16-64) |

**Response Model:** `RotateHostSecretResponse`
```json
{
  "success": true,
  "message": "Credential rotation completed successfully",
  "error": null,
  "phase": "complete",
  "suggestions": null,
  "manual_fix_required": false,
  "manual_fix_instructions": null,
  "timing": {
    "fetch_current": 0.15,
    "validate_current": 0.08,
    "check_privilege": 0.05,
    "update_mysql": 0.12,
    "verify_new": 0.08,
    "update_aws": 0.25,
    "verify_roundtrip": 0.18
  }
}
```

On failure with manual fix required:
```json
{
  "success": false,
  "message": "Credential rotation failed",
  "error": "AWS Secrets Manager update failed",
  "phase": "update_aws",
  "suggestions": ["Check AWS IAM permissions", "Verify secret exists"],
  "manual_fix_required": true,
  "manual_fix_instructions": "MySQL password was updated but AWS failed. Run: aws secretsmanager put-secret-value --secret-id ... --secret-string '{\"password\": \"...\"}'"
}
```

---

## Dropdown Search

Endpoints for autocomplete dropdowns in the UI.

### `GET /api/dropdown/customers`

Search customers for autocomplete.

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Search query (min 2 chars) |
| `limit` | int | Max results |

**Response Model:** `DropdownSearchResponse`

---

### `GET /api/dropdown/users`

Search users for autocomplete.

**Authentication:** Required

**Response Model:** `DropdownSearchResponse`

---

### `GET /api/dropdown/hosts`

Search hosts for autocomplete.

**Authentication:** Required

**Response Model:** `DropdownSearchResponse`

---

## Backup Discovery

### `GET /api/customers/search`

Search for customers with available backups.

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Customer name search query |

**Response Model:** `CustomerSearchResponse`

---

### `GET /api/backups/search`

Search for available backups.

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `customer` | string | Customer ID |
| `env` | string | S3 environment |

**Response Model:** `BackupSearchResponse`

---

## Feature Requests

### `GET /api/feature-requests/stats`

Get feature request statistics.

**Authentication:** Required

**Response Model:** `FeatureRequestStatsResponse`

---

### `GET /api/feature-requests`

List all feature requests.

**Authentication:** Required

**Response Model:** `FeatureRequestListResponse`

---

### `GET /api/feature-requests/{request_id}`

Get a specific feature request.

**Authentication:** Required

**Response Model:** `FeatureRequestResponse`

---

### `POST /api/feature-requests`

Create a new feature request.

**Authentication:** Required

**Response Model:** `FeatureRequestResponse` (201 Created)

---

### `PATCH /api/feature-requests/{request_id}`

Update a feature request.

**Authentication:** Required

**Response Model:** `FeatureRequestResponse`

---

### `POST /api/feature-requests/{request_id}/vote`

Vote on a feature request.

**Authentication:** Required

**Response Model:** `FeatureRequestResponse`

---

### `DELETE /api/feature-requests/{request_id}`

Delete a feature request.

**Authentication:** Required  
**Authorization:** Request author or admin

**Response:** 204 No Content

---

## Response Models

### JobSummary

```json
{
  "id": "8b4c4a3a-85a1-4da2-9f3c-abc123def456",
  "target": "acme_jdoe",
  "status": "running",
  "user_code": "jdoe",
  "owner_user_code": "jdoe",
  "owner_user_id": "uuid...",
  "submitted_at": "2026-01-21T10:30:00Z",
  "started_at": "2026-01-21T10:31:00Z",
  "completed_at": null,
  "staging_name": "staging_8b4c4a3a",
  "current_operation": "myloader (45/120 tables)",
  "dbhost": "dev",
  "source": "acme",
  "cancel_requested_at": null,
  "can_cancel": true,
  "custom_target": false
}
```

### JobHistoryItem

```json
{
  "id": "8b4c4a3a-...",
  "target": "acme_jdoe",
  "status": "complete",
  "user_code": "jdoe",
  "owner_username": "jdoe",
  "submitted_at": "2026-01-21T10:30:00Z",
  "started_at": "2026-01-21T10:31:00Z",
  "completed_at": "2026-01-21T10:45:00Z",
  "duration_seconds": 840.5,
  "staging_name": "staging_8b4c4a3a",
  "dbhost": "dev",
  "source": "acme",
  "error_detail": null,
  "retry_count": 0
}
```

### JobEventResponse

```json
{
  "id": 12345,
  "job_id": "8b4c4a3a-...",
  "event_type": "myloader_progress",
  "detail": "Restored 45/120 tables (37.5%)",
  "logged_at": "2026-01-21T10:40:00Z"
}
```

---

## Error Responses

All errors follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

### Common Status Codes

| Code | Description |
|------|-------------|
| 400 | Bad Request - Invalid parameters |
| 401 | Unauthorized - Missing or invalid credentials |
| 403 | Forbidden - Insufficient permissions |
| 404 | Not Found - Resource doesn't exist |
| 409 | Conflict - State conflict (e.g., job already canceled) |
| 500 | Internal Server Error |
| 503 | Service Unavailable - Backend not ready |

---

## Multi-Language Examples

Complete examples for common operations in Python, PHP, and Bash.

### Submit a Restore Job

#### Python

```python
"""Submit a database restore job and poll for completion."""

import hashlib
import hmac
import os
import time
from datetime import datetime, timezone

import requests

API_BASE = os.getenv("PULLDB_API_URL", "http://localhost:8080")
API_KEY = os.environ["PULLDB_API_KEY"]
API_SECRET = os.environ["PULLDB_API_SECRET"]


def generate_signature(method: str, path: str, timestamp: str) -> str:
    payload = f"{method}:{path}:{timestamp}"
    return hmac.new(API_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def api_request(method: str, path: str, json_data: dict | None = None) -> dict:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signature = generate_signature(method, path, timestamp)
    
    headers = {
        "X-API-Key": API_KEY,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }
    
    response = requests.request(method, f"{API_BASE}{path}", headers=headers, json=json_data)
    response.raise_for_status()
    return response.json()


def submit_and_wait(customer: str, dbhost: str, user: str) -> dict:
    # Submit job
    job = api_request("POST", "/api/jobs", {
        "user": user,
        "customer": customer,
        "dbhost": dbhost,
    })
    
    job_id = job["id"]
    print(f"Job submitted: {job_id}")
    
    # Poll until complete
    while True:
        status = api_request("GET", f"/api/jobs/{job_id}")
        print(f"Status: {status['status']} - {status.get('current_operation', '')}")
        
        if status["status"] in ("complete", "failed", "canceled"):
            return status
        
        time.sleep(5)


if __name__ == "__main__":
    result = submit_and_wait("acme", "dev", "jdoe")
    print(f"Final: {result['status']}")
```

#### PHP

```php
<?php
/**
 * Submit a database restore job and poll for completion.
 */

$apiBase = getenv('PULLDB_API_URL') ?: 'http://localhost:8080';
$apiKey = getenv('PULLDB_API_KEY');
$apiSecret = getenv('PULLDB_API_SECRET');

function generateSignature(string $method, string $path, string $timestamp, string $secret): string {
    return hash_hmac('sha256', "{$method}:{$path}:{$timestamp}", $secret);
}

function apiRequest(string $method, string $path, ?array $data = null): array {
    global $apiBase, $apiKey, $apiSecret;
    
    $timestamp = gmdate('Y-m-d\TH:i:s\Z');
    $signature = generateSignature($method, $path, $timestamp, $apiSecret);
    
    $ch = curl_init($apiBase . $path);
    curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        "X-API-Key: {$apiKey}",
        "X-Timestamp: {$timestamp}",
        "X-Signature: {$signature}",
        "Content-Type: application/json",
    ]);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    
    if ($data !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($data));
    }
    
    $response = curl_exec($ch);
    curl_close($ch);
    
    return json_decode($response, true);
}

function submitAndWait(string $customer, string $dbhost, string $user): array {
    // Submit job
    $job = apiRequest('POST', '/api/jobs', [
        'user' => $user,
        'customer' => $customer,
        'dbhost' => $dbhost,
    ]);
    
    $jobId = $job['id'];
    echo "Job submitted: {$jobId}\n";
    
    // Poll until complete
    while (true) {
        $status = apiRequest('GET', "/api/jobs/{$jobId}");
        echo "Status: {$status['status']}\n";
        
        if (in_array($status['status'], ['complete', 'failed', 'canceled'])) {
            return $status;
        }
        
        sleep(5);
    }
}

$result = submitAndWait('acme', 'dev', 'jdoe');
echo "Final: {$result['status']}\n";
```

#### Bash

```bash
#!/bin/bash
# Submit a database restore job and poll for completion.

set -euo pipefail

API_BASE="${PULLDB_API_URL:-http://localhost:8080}"
API_KEY="${PULLDB_API_KEY:?Error: PULLDB_API_KEY not set}"
API_SECRET="${PULLDB_API_SECRET:?Error: PULLDB_API_SECRET not set}"

generate_signature() {
    local method="$1" path="$2" timestamp="$3"
    echo -n "${method}:${path}:${timestamp}" | openssl dgst -sha256 -hmac "$API_SECRET" | awk '{print $2}'
}

api_request() {
    local method="$1" path="$2" data="${3:-}"
    local timestamp signature
    
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    signature=$(generate_signature "$method" "$path" "$timestamp")
    
    local args=(-s -X "$method"
        -H "X-API-Key: $API_KEY"
        -H "X-Timestamp: $timestamp"
        -H "X-Signature: $signature"
        -H "Content-Type: application/json")
    
    [[ -n "$data" ]] && args+=(-d "$data")
    
    curl "${args[@]}" "${API_BASE}${path}"
}

# Submit job
job=$(api_request "POST" "/api/jobs" '{"user":"jdoe","customer":"acme","dbhost":"dev"}')
job_id=$(echo "$job" | jq -r .id)
echo "Job submitted: $job_id"

# Poll until complete
while true; do
    status=$(api_request "GET" "/api/jobs/${job_id}")
    state=$(echo "$status" | jq -r .status)
    echo "Status: $state"
    
    case "$state" in
        complete|failed|canceled) break ;;
    esac
    
    sleep 5
done

echo "Final: $state"
```

---

### Stream Job Events

#### Python

```python
"""Stream job events in real-time."""

def stream_events(job_id: str, since_id: int = 0):
    """Stream events for a job, yielding each new event."""
    while True:
        events = api_request("GET", f"/api/jobs/{job_id}/events?since_id={since_id}")
        
        for event in events:
            yield event
            since_id = max(since_id, event["id"])
        
        # Check if job is complete
        status = api_request("GET", f"/api/jobs/{job_id}")
        if status["status"] in ("complete", "failed", "canceled"):
            break
        
        time.sleep(2)


# Usage
for event in stream_events("8b4c4a3a-85a1-4da2-9f3c-abc123def456"):
    print(f"[{event['event_type']}] {event['detail']}")
```

---

### Search for Backups

#### Python

```python
"""Search for available backups for a customer."""

# Search customers
customers = api_request("GET", "/api/customers/search?q=acme")
print(f"Found {len(customers['results'])} customers")

for customer in customers["results"]:
    print(f"  - {customer['id']}: {customer['name']}")

# Get backups for a customer
backups = api_request("GET", "/api/backups/search?customer=acme&env=production")
print(f"\nFound {len(backups['backups'])} backups")

for backup in backups["backups"][:5]:
    print(f"  - {backup['date']}: {backup['size_mb']} MB")
```

---

### Admin: Prune Old Logs (Dry Run)

#### Python

```python
"""Preview log pruning before execution."""

# Dry run first
preview = api_request("POST", "/api/admin/prune-logs", {
    "days": 90,
    "dry_run": True,
})
print(f"Would delete {preview['would_delete']} events older than {preview['retention_days']} days")

# Confirm and execute
if input("Proceed? (y/n): ").lower() == "y":
    result = api_request("POST", "/api/admin/prune-logs", {
        "days": 90,
        "dry_run": False,
    })
    print(f"Deleted {result['deleted']} events")
```

#### Bash

```bash
#!/bin/bash
# Preview and execute log pruning

# Dry run
echo "Previewing prune operation..."
preview=$(api_request "POST" "/api/admin/prune-logs" '{"days":90,"dry_run":true}')
would_delete=$(echo "$preview" | jq .would_delete)
echo "Would delete $would_delete events"

read -p "Proceed with deletion? (y/n): " confirm
if [[ "$confirm" == "y" ]]; then
    result=$(api_request "POST" "/api/admin/prune-logs" '{"days":90,"dry_run":false}')
    deleted=$(echo "$result" | jq .deleted)
    echo "Deleted $deleted events"
fi
```

---

*For complete code templates and guidelines, see [API-DOCUMENTATION-STANDARD.md](API-DOCUMENTATION-STANDARD.md)*

---

*Generated: 2026-01-21 | Source: pulldb/api/main.py*
