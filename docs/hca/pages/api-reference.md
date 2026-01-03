# pullDB REST API Reference

> **Complete API documentation for pullDB v0.2.0**
>
> The pullDB API is a FastAPI-based REST service running on port **8000** (web) or **8080** (API-only mode).
> Interactive documentation is available at `/api/docs` (Swagger) and `/api/redoc` (ReDoc) when the service is running.

## Table of Contents

- [Authentication](#authentication)
- [Base URL](#base-url)
- [Health & Status](#health--status)
- [Jobs](#jobs)
- [Users](#users)
- [Hosts](#hosts)
- [Backups](#backups)
- [Manager Endpoints](#manager-endpoints)
- [Admin Endpoints](#admin-endpoints)
- [Error Handling](#error-handling)

---

## Authentication

pullDB supports three authentication modes configured via `PULLDB_AUTH_MODE`:

| Mode | Description | Header/Cookie |
|------|-------------|---------------|
| `trusted` | Trust `X-Pulldb-User` header from CLI | `X-Pulldb-User: username` |
| `session` | Cookie-based sessions with bcrypt passwords | `session_token` cookie |
| `both` | Accept either method (default) | Either of the above |

### Trusted Mode (CLI)

```bash
curl -H "X-Pulldb-User: jsmith" http://localhost:8000/api/jobs
```

### Session Mode (Web UI)

Login via `/web/login` to obtain a session cookie, then include it in requests:

```bash
curl -b "session_token=abc123..." http://localhost:8000/api/jobs
```

### Role-Based Access Control (RBAC)

| Role | Permissions |
|------|-------------|
| `USER` | Submit/view own jobs, cancel own jobs |
| `MANAGER` | View team jobs, manage team members |
| `ADMIN` | Full access, system configuration |

---

## Base URL

| Environment | URL |
|-------------|-----|
| Production | `http://pulldb-server:8000/api` |
| Development | `http://localhost:8000/api` |
| API-Only Mode | `http://localhost:8080/api` |

All endpoints are prefixed with `/api`.

---

## Health & Status

### GET /api/health

Health check endpoint. Returns `200 OK` if the service is running.

**Request:**
```bash
curl http://localhost:8000/api/health
```

**Response:**
```json
{
  "status": "ok"
}
```

---

### GET /api/status

System status with queue depth and active restore count.

**Request:**
```bash
curl http://localhost:8000/api/status
```

**Response:**
```json
{
  "queue_depth": 3,
  "active_restores": 2,
  "service": "api"
}
```

---

## Jobs

### POST /api/jobs

Submit a new restore job.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user` | string | ✅ | User code (e.g., `cust_12345`) |
| `customer` | string | ❌ | Customer name for backup search |
| `qatemplate` | boolean | ❌ | Use QA template instead of customer backup |
| `dbhost` | string | ❌ | Target database host (default from settings) |
| `date` | string | ❌ | Specific backup date `YYYY-MM-DD` |
| `env` | string | ❌ | S3 environment: `staging` or `prod` |
| `overwrite` | boolean | ❌ | Overwrite existing database |
| `suffix` | string | ❌ | 1-3 letter suffix for target database |
| `backup_path` | string | ❌ | Full S3 path to specific backup |

**Example - Customer Restore:**
```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -H "X-Pulldb-User: jsmith" \
  -d '{
    "user": "cust_12345",
    "customer": "acme_pest",
    "dbhost": "dev-mysql-01"
  }'
```

**Example - QA Template:**
```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -H "X-Pulldb-User: jsmith" \
  -d '{
    "user": "cust_12345",
    "qatemplate": true
  }'
```

**Response (201 Created):**
```json
{
  "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "target": "cust_12345",
  "staging_name": "pulldb_stg_8b4c4a3a",
  "status": "queued",
  "owner_username": "jsmith",
  "owner_user_code": "jsmith",
  "submitted_at": "2026-01-02T15:30:00Z"
}
```

**Error Response (409 Conflict):**
```json
{
  "detail": "Restore already in progress for target 'cust_12345'"
}
```

---

### GET /api/jobs

List jobs with optional filters.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Max results (1-1000) |
| `active` | boolean | false | Only active (queued/running) jobs |
| `history` | boolean | false | Only completed/failed/canceled jobs |
| `filter` | string | null | Filter by user code prefix |

**Example:**
```bash
curl "http://localhost:8000/api/jobs?active=true&limit=10"
```

**Response:**
```json
[
  {
    "id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
    "target": "cust_12345",
    "status": "running",
    "user_code": "cust_12345",
    "owner_user_code": "jsmith",
    "submitted_at": "2026-01-02T15:30:00Z",
    "started_at": "2026-01-02T15:30:05Z",
    "completed_at": null,
    "staging_name": "pulldb_stg_8b4c4a3a",
    "current_operation": "downloading",
    "dbhost": "dev-mysql-01",
    "source": "s3://bucket/daily/stg/acme_pest/...",
    "can_cancel": true
  }
]
```

---

### GET /api/jobs/active

Shortcut for listing only active jobs.

```bash
curl "http://localhost:8000/api/jobs/active"
```

---

### GET /api/jobs/history

Shortcut for listing completed/failed/canceled jobs.

```bash
curl "http://localhost:8000/api/jobs/history?limit=50"
```

---

### GET /api/jobs/paginated

Paginated job listing with cursor-based pagination.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `cursor` | string | Pagination cursor from previous response |
| `limit` | integer | Page size (default 25, max 100) |
| `status` | string | Filter by status |
| `user_code` | string | Filter by user code |

**Response:**
```json
{
  "items": [...],
  "next_cursor": "eyJ0cyI6IjIwMjYtMDEtMDIifQ==",
  "has_more": true,
  "total": 156
}
```

---

### GET /api/jobs/{job_id}

Get detailed information about a specific job.

```bash
curl "http://localhost:8000/api/jobs/8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f"
```

---

### GET /api/jobs/resolve/{prefix}

Resolve a short job ID prefix to full job ID.

**Example:**
```bash
curl "http://localhost:8000/api/jobs/resolve/8b4c4a3a"
```

**Response (single match):**
```json
{
  "resolved_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "matches": [...],
  "count": 1
}
```

**Response (multiple matches):**
```json
{
  "resolved_id": null,
  "matches": [
    {"id": "8b4c4a3a-85a1-...", "target": "cust_12345", "status": "completed"},
    {"id": "8b4c4a3a-92f7-...", "target": "cust_67890", "status": "running"}
  ],
  "count": 2
}
```

---

### GET /api/jobs/{job_id}/events

Get event log for a job.

```bash
curl "http://localhost:8000/api/jobs/8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f/events"
```

**Response:**
```json
[
  {
    "id": 1,
    "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
    "event_type": "job_queued",
    "detail": "Job submitted by jsmith",
    "logged_at": "2026-01-02T15:30:00Z"
  },
  {
    "id": 2,
    "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
    "event_type": "download_started",
    "detail": "Downloading from s3://...",
    "logged_at": "2026-01-02T15:30:05Z"
  }
]
```

---

### GET /api/jobs/{job_id}/profile

Get performance breakdown for a completed job.

```bash
curl "http://localhost:8000/api/jobs/8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f/profile"
```

**Response:**
```json
{
  "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "total_seconds": 245.5,
  "phases": {
    "download": 45.2,
    "extract": 12.8,
    "restore": 180.5,
    "post_sql": 7.0
  }
}
```

---

### POST /api/jobs/{job_id}/cancel

Cancel a running or queued job.

```bash
curl -X POST "http://localhost:8000/api/jobs/8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f/cancel" \
  -H "X-Pulldb-User: jsmith"
```

**Response (200 OK):**
```json
{
  "message": "Cancel requested for job 8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f"
}
```

---

### GET /api/jobs/my-last

Get the authenticated user's most recent job.

```bash
curl -H "X-Pulldb-User: jsmith" "http://localhost:8000/api/jobs/my-last"
```

---

### GET /api/jobs/search

Search jobs by target prefix.

```bash
curl "http://localhost:8000/api/jobs/search?q=cust_123"
```

---

## Users

### GET /api/users/{username}

Get user information by username.

```bash
curl "http://localhost:8000/api/users/jsmith"
```

**Response:**
```json
{
  "username": "jsmith",
  "user_code": "jsmith",
  "is_admin": false,
  "is_disabled": false,
  "has_password": true
}
```

---

### GET /api/users/{user_code}/last-job

Get a user's most recent job (by user code).

```bash
curl "http://localhost:8000/api/users/cust_12345/last-job"
```

**Response:**
```json
{
  "job_id": "8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f",
  "target": "cust_12345",
  "status": "completed",
  "submitted_at": "2026-01-02T15:30:00Z",
  "started_at": "2026-01-02T15:30:05Z",
  "completed_at": "2026-01-02T15:34:10Z",
  "found": true
}
```

---

### POST /api/auth/register

Register a new user account.

**Request Body:**
```json
{
  "username": "newuser",
  "password": "securepassword123",
  "user_code": "newuser"
}
```

**Response (201 Created):**
```json
{
  "user_id": "usr_abc123",
  "username": "newuser",
  "message": "User registered successfully"
}
```

---

### POST /api/auth/change-password

Change user password.

**Request Body:**
```json
{
  "username": "jsmith",
  "current_password": "oldpassword",
  "new_password": "newsecurepassword"
}
```

---

## Hosts

### GET /api/hosts

List available database hosts for restore targets.

```bash
curl "http://localhost:8000/api/hosts"
```

**Response:**
```json
{
  "hosts": [
    {
      "hostname": "dev-mysql-01.internal",
      "alias": "dev-mysql-01",
      "enabled": true
    },
    {
      "hostname": "staging-mysql.internal",
      "alias": "staging",
      "enabled": true
    }
  ],
  "total": 2
}
```

---

## Backups

### GET /api/backups/search

Search for available backups in S3.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `customer` | string | Customer name to search |
| `env` | string | Environment: `staging` or `prod` |
| `date` | string | Specific date `YYYY-MM-DD` |
| `limit` | integer | Max results |

**Example:**
```bash
curl "http://localhost:8000/api/backups/search?customer=acme&env=staging&limit=5"
```

**Response:**
```json
{
  "backups": [
    {
      "path": "s3://pestroutesrdsdbs/daily/stg/acme_pest/daily_mydumper_2026-01-02.tar",
      "customer": "acme_pest",
      "date": "2026-01-02",
      "size_bytes": 1234567890,
      "env": "staging"
    }
  ],
  "total": 1
}
```

---

### GET /api/customers/search

Search for customer names.

```bash
curl "http://localhost:8000/api/customers/search?q=acme"
```

---

## Manager Endpoints

These endpoints require `MANAGER` or `ADMIN` role.

### GET /api/manager/team

List team members and their jobs.

```bash
curl -H "X-Pulldb-User: manager1" "http://localhost:8000/api/manager/team"
```

---

### GET /api/manager/team/distinct

Get distinct user codes in the manager's team.

---

## Admin Endpoints

These endpoints require `ADMIN` role.

### POST /api/admin/settings

Update system settings.

### GET /api/admin/users

List all users.

### POST /api/admin/users/{user_id}/disable

Disable a user account.

### DELETE /api/admin/staging/{staging_name}

Clean up orphaned staging databases.

---

## Dropdown Endpoints

These endpoints power the web UI autocomplete dropdowns.

### GET /api/dropdown/customers

```bash
curl "http://localhost:8000/api/dropdown/customers?q=acme&limit=10"
```

### GET /api/dropdown/users

```bash
curl "http://localhost:8000/api/dropdown/users?q=jsmith&limit=10"
```

### GET /api/dropdown/hosts

```bash
curl "http://localhost:8000/api/dropdown/hosts?q=dev&limit=10"
```

---

## Error Handling

All errors return JSON with a `detail` field:

### 400 Bad Request

```json
{
  "detail": "Invalid date format. Use YYYY-MM-DD."
}
```

### 401 Unauthorized

```json
{
  "detail": "Authentication required"
}
```

### 403 Forbidden

```json
{
  "detail": "Admin role required"
}
```

### 404 Not Found

```json
{
  "detail": "Job not found: 8b4c4a3a-..."
}
```

### 409 Conflict

```json
{
  "detail": "Restore already in progress for target 'cust_12345'"
}
```

### 500 Internal Server Error

```json
{
  "detail": "Internal server error",
  "error_id": "err_abc123"
}
```

---

## Interactive Documentation

When the service is running, interactive API documentation is available:

- **Swagger UI**: `http://localhost:8000/api/docs`
- **ReDoc**: `http://localhost:8000/api/redoc`
- **OpenAPI JSON**: `http://localhost:8000/api/openapi.json`

---

## See Also

- [CLI Reference](cli-reference.md) - Command-line interface documentation
- [Getting Started](getting-started.md) - Installation and quick start
- [Architecture](../widgets/architecture.md) - System design overview
