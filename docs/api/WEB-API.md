# pullDB Web UI API Reference

[← Back to API Index](README.md) | [REST API Reference](REST-API.md)

> **Version**: 1.0.8  
> **Base URL**: `http://localhost:8000`  
> **Authentication**: Session Cookie (`session_token`)  
> **Source**: [pulldb/web/features/](../../pulldb/web/features/)

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication Routes](#authentication-routes)
3. [Dashboard](#dashboard)
4. [Jobs](#jobs)
5. [Restore](#restore)
6. [Admin](#admin)
7. [Manager](#manager)
8. [Audit](#audit)
9. [Feature Requests](#feature-requests)
10. [Mockup (Development)](#mockup-development)
11. [LazyTable Widget API Pattern](#lazytable-widget-api-pattern)
12. [Error Handling](#error-handling)
13. [Multi-Language Examples](#multi-language-examples)

---

## Overview

The Web UI API serves HTML pages and HTMX fragments for the browser-based interface. Most endpoints return HTML responses; some return JSON for AJAX/HTMX requests.

### Authentication

All routes (except login) require session authentication via `session_token` cookie.

### Route Prefixes

| Module | Prefix | Purpose |
|--------|--------|---------|
| auth | `/web` | Login, logout, password change, profile |
| dashboard | `/web/dashboard` | Role-specific dashboards |
| jobs | `/web/jobs` | Job monitoring, actions, history |
| restore | `/web/restore` | New restore submission |
| admin | `/web/admin` | Admin management pages |
| manager | `/web/manager` | Team management |
| audit | `/web/audit` | Audit log viewer |
| requests | `/web/requests` | Feature requests |

---

## Authentication Routes

**Source**: [pulldb/web/features/auth/routes.py](../../pulldb/web/features/auth/routes.py)

### Pages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/login` | Login page |
| POST | `/web/login` | Submit login credentials |
| GET | `/web/logout` | Logout and clear session |
| GET | `/web/change-password` | Password change page |
| POST | `/web/change-password` | Submit new password |
| GET | `/web/auth/profile` | User profile page |
| GET | `/web/maintenance` | Database maintenance acknowledgment page |
| POST | `/web/maintenance` | Acknowledge maintenance items |

### API Endpoints

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| POST | `/web/auth/api-key/generate` | Generate new API key | JSON |
| POST | `/web/auth/api-key/{key_id}/revoke` | Revoke own API key | HTML redirect |
| POST | `/web/auth/change-password` | Password change (profile) | HTML redirect |
| POST | `/web/auth/set-default-host` | Set user's default host | JSON |

---

## Dashboard

**Source**: [pulldb/web/features/dashboard/routes.py](../../pulldb/web/features/dashboard/routes.py)

### Routes

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/web/dashboard/` | Role-specific dashboard | Required |

### Dashboard Types

The dashboard renders different content based on user role:

| Role | Dashboard Features |
|------|-------------------|
| USER | My active jobs, last job status, recent jobs |
| MANAGER | Team stats, team member jobs, managed users |
| ADMIN | System stats, host health, all jobs overview |

---

## Jobs

**Source**: [pulldb/web/features/jobs/routes.py](../../pulldb/web/features/jobs/routes.py)

### Pages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/jobs/` | Jobs list (Active/History views) |
| GET | `/web/jobs/{job_id}` | Job detail page with progress |

### Query Parameters for Job List

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 1 | Page number |
| `view` | string | "active" | "active" or "history" |
| `q` | string | null | Search query (min 4 chars) |
| `status` | string | null | Filter by status |
| `host` | string | null | Filter by host |
| `days` | int | 30 | History retention days |
| `user_code` | string | null | Filter by user |
| `target` | string | null | Filter by target |

### Job Actions

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/web/jobs/{job_id}/cancel` | Cancel a job | Owner/Manager/Admin |
| POST | `/web/jobs/{job_id}/delete-database` | Drop deployed database | Owner/Admin |
| POST | `/web/jobs/{job_id}/extend` | Extend retention | Owner/Admin |
| POST | `/web/jobs/{job_id}/lock` | Lock database from cleanup | Owner/Admin |
| POST | `/web/jobs/{job_id}/unlock` | Unlock database | Owner/Admin |
| POST | `/web/jobs/{job_id}/user-complete` | Mark job as user-complete | Owner |
| POST | `/web/jobs/bulk-delete` | Bulk delete databases | Admin |

### API Endpoints (JSON)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/jobs/api/paginated` | Paginated jobs for LazyTable |
| GET | `/web/jobs/api/paginated/distinct` | Distinct values for filters |
| GET | `/web/jobs/bulk-delete/{task_id}/status` | Bulk delete task status |
| POST | `/web/jobs/api/{job_id}/lock` | Lock job (JSON API) |
| POST | `/web/jobs/api/{job_id}/unlock` | Unlock job (JSON API) |
| POST | `/web/jobs/api/mark-expired` | Mark jobs as expired (system) |

---

## Restore

**Source**: [pulldb/web/features/restore/routes.py](../../pulldb/web/features/restore/routes.py)

### Pages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/restore/` | New restore form |
| POST | `/web/restore/` | Submit restore job |

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `for_user` | bool | false | Show user selector (managers/admins) |

### API Endpoints

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| GET | `/web/restore/search-customers` | Search customers | JSON |
| GET | `/web/restore/search-backups` | Search backups (HTMX) | HTML |

### Customer Search Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Search query (min 1 char, wildcards: * ?) |
| `limit` | int | Max results (default 100) |

### Backup Search Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `customer` | string | Customer name or pattern |
| `env` | string | "both", "staging", or "prod" |
| `date_from` | string | Start date YYYYMMDD |
| `limit` | int | Max results (default 10) |
| `offset` | int | Pagination offset |

---

## Admin

**Source**: [pulldb/web/features/admin/routes.py](../../pulldb/web/features/admin/routes.py)

> **Authorization**: Admin role required for all routes

### Pages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/admin/` | Admin dashboard |
| GET | `/web/admin/styleguide` | Component style guide |
| GET | `/web/admin/users` | User management |
| GET | `/web/admin/hosts` | Host management |
| GET | `/web/admin/hosts/{host_id}` | Host detail/edit |
| GET | `/web/admin/settings` | System settings |
| GET | `/web/admin/settings-sync` | Settings drift check |
| GET | `/web/admin/api-keys` | API key management |
| GET | `/web/admin/job-history` | Complete job history |
| GET | `/web/admin/disallowed-users` | Username blocklist |
| GET | `/web/admin/locked-databases` | Locked databases |
| GET | `/web/admin/prune-logs/preview` | Prune old job logs |
| GET | `/web/admin/cleanup-staging/preview` | Cleanup staging DBs |
| GET | `/web/admin/orphans` | Orphaned databases |
| GET | `/web/admin/orphans/preview` | Orphan preview |
| GET | `/web/admin/user-orphans` | User-owned orphan DBs |

### Locked Database Management

| Method | Path | Description |
|--------|------|-------------|
| POST | `/web/admin/locked-databases/{job_id}/unlock` | Unlock a locked database |

### User Management

| Method | Path | Description |
|--------|------|-------------|
| POST | `/web/admin/users/add` | Create new user |
| POST | `/web/admin/users/{user_id}/enable` | Enable user |
| POST | `/web/admin/users/{user_id}/disable` | Disable user |
| DELETE | `/web/admin/users/{user_id}` | Delete user (no jobs only) |
| POST | `/web/admin/users/{user_id}/role` | Change user role |
| POST | `/web/admin/users/{user_id}/manager` | Assign manager |
| POST | `/web/admin/users/{user_id}/force-password-reset` | Force password reset |
| POST | `/web/admin/users/{user_id}/clear-password-reset` | Clear reset flag |
| POST | `/web/admin/users/{user_id}/assign-temp-password` | Assign temp password |
| GET | `/web/admin/users/{user_id}/hosts` | Get user's allowed hosts |
| POST | `/web/admin/users/{user_id}/hosts` | Set user's allowed hosts |
| GET | `/web/admin/users/{user_id}/force-delete-preview` | Preview force delete |
| POST | `/web/admin/users/{user_id}/force-delete` | Force delete with jobs |

### Host Management

| Method | Path | Description |
|--------|------|-------------|
| POST | `/web/admin/hosts/add` | Add new host |
| POST | `/web/admin/hosts/{hostname}/enable` | Enable host |
| POST | `/web/admin/hosts/{hostname}/disable` | Disable host |
| POST | `/web/admin/hosts/{host_id}/update` | Update host settings |
| POST | `/web/admin/hosts/{host_id}/update-secret` | Update host credentials |
| POST | `/web/admin/hosts/{host_id}/delete` | Delete host |
| POST | `/web/admin/hosts/{host_id}/test-connection` | Test database connection |
| POST | `/web/admin/hosts/check-alias` | Validate host alias |
| POST | `/web/admin/hosts/provision` | Provision new host from SM |
| GET | `/web/admin/hosts/{host_id}/delete-preview` | Preview host deletion |

### Settings Management

| Method | Path | Description |
|--------|------|-------------|
| POST | `/web/admin/settings/{key}` | Update setting |
| DELETE | `/web/admin/settings/{key}` | Reset to default |
| POST | `/web/admin/settings/{key}/validate` | Validate setting value |
| POST | `/web/admin/settings/{key}/create-directory` | Create directory setting |

### API Key Management

| Method | Path | Description |
|--------|------|-------------|
| POST | `/web/admin/api-keys/{key_id}/approve` | Approve pending key |
| POST | `/web/admin/api-keys/{key_id}/revoke` | Revoke active key |
| DELETE | `/web/admin/api-keys/{key_id}` | Delete key |
| GET | `/web/admin/api-keys/user/{user_id}` | Get user's keys |

### Cleanup Operations

| Method | Path | Description |
|--------|------|-------------|
| POST | `/web/admin/prune-logs/execute` | Execute log pruning |
| POST | `/web/admin/prune-logs` | Prune job logs |
| POST | `/web/admin/cleanup-staging/execute` | Execute staging cleanup |
| POST | `/web/admin/cleanup-staging` | Cleanup staging DBs |
| POST | `/web/admin/orphans/execute` | Execute orphan cleanup |
| POST | `/web/admin/orphans/delete` | Delete orphans |
| POST | `/web/admin/user-orphans/scan` | Scan for user orphans |
| POST | `/web/admin/user-orphans/delete` | Delete user orphans |
| POST | `/web/admin/user-orphans/execute` | Execute orphan cleanup |
| POST | `/web/admin/jobs/{job_id}/force-complete-delete` | Force delete job |

### Admin API Endpoints (JSON)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/admin/api/hosts` | List all hosts |
| GET | `/web/admin/api/users` | Paginated users |
| GET | `/web/admin/api/users/distinct` | Distinct filter values |
| GET | `/web/admin/api/hosts/paginated` | Paginated hosts |
| GET | `/web/admin/api/hosts/paginated/distinct` | Host filter values |
| POST | `/web/admin/api/hosts/{host_id}/toggle` | Toggle host enabled |
| POST | `/web/admin/api/hosts/{host_id}/rotate-secret` | Rotate host secret |
| GET | `/web/admin/api/prune-candidates` | Prune preview data |
| GET | `/web/admin/api/prune-candidates/distinct` | Prune filter values |
| GET | `/web/admin/api/cleanup-candidates` | Cleanup preview data |
| GET | `/web/admin/api/cleanup-candidates/distinct` | Cleanup filter values |
| GET | `/web/admin/api/orphan-candidates` | Orphan databases |
| GET | `/web/admin/api/orphan-candidates/distinct` | Orphan filter values |
| GET | `/web/admin/api/user-orphan-candidates` | User orphan DBs |
| GET | `/web/admin/api/user-orphan-candidates/distinct` | User orphan filters |
| GET | `/web/admin/api/theme.css` | Dynamic theme CSS |
| GET | `/web/admin/api/color-preset` | Get color preset |
| GET | `/web/admin/api/color-presets` | List color presets |
| GET | `/web/admin/api/saved-theme-schemas` | Saved themes |
| POST | `/web/admin/api/generate-manifest` | Generate PWA manifest |
| GET | `/web/admin/api/theme-version` | Theme version info |
| GET | `/web/admin/api/disallowed-users` | List blocked usernames |
| POST | `/web/admin/api/disallowed-users` | Add blocked username |
| DELETE | `/web/admin/api/disallowed-users/{username}` | Remove from blocklist |
| GET | `/web/admin/api/job-history/stats` | Job history stats |
| GET | `/web/admin/api/job-history/count` | Job history count |
| POST | `/web/admin/api/job-history/prune` | Prune old history |
| GET | `/web/admin/api/job-history/records` | Paginated job history |
| GET | `/web/admin/admin-tasks/{task_id}/json` | Async task status |
| GET | `/web/admin/admin-tasks/{task_id}` | Async task page |

---

## Manager

**Source**: [pulldb/web/features/manager/routes.py](../../pulldb/web/features/manager/routes.py)

> **Authorization**: Manager or Admin role required

### Pages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/manager/` | My Team management page |

### Team Member Actions

| Method | Path | Description |
|--------|------|-------------|
| POST | `/web/manager/my-team/{user_id}/reset-password` | Force password reset |
| POST | `/web/manager/my-team/{user_id}/clear-password-reset` | Clear reset flag |
| POST | `/web/manager/my-team/{user_id}/enable` | Enable team member |
| POST | `/web/manager/my-team/{user_id}/disable` | Disable team member |
| POST | `/web/manager/my-team/{user_id}/assign-temp-password` | Assign temp password |

### API Endpoints (JSON)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/manager/api/team` | Paginated team members |

---

## Audit

**Source**: [pulldb/web/features/audit/routes.py](../../pulldb/web/features/audit/routes.py)

### Pages

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/web/audit/` | Audit log viewer | Admin |

### API Endpoints (JSON)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/audit/api/logs` | Paginated audit logs |
| GET | `/web/audit/api/logs/distinct` | Filter distinct values |

---

## Feature Requests

**Source**: [pulldb/web/features/requests/routes.py](../../pulldb/web/features/requests/routes.py)

### Pages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/requests/` | Feature requests list |

### API Endpoints (JSON)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/requests/api/list` | Paginated requests |
| GET | `/web/requests/api/list/distinct` | Filter distinct values |
| POST | `/web/requests/api/vote/{request_id}` | Vote on request |
| POST | `/web/requests/api/create` | Create new request |
| POST | `/web/requests/api/update/{request_id}` | Update request |
| DELETE | `/web/requests/api/delete/{request_id}` | Delete request |
| GET | `/web/requests/api/notes/{request_id}` | Get request notes |
| POST | `/web/requests/api/notes/{request_id}` | Add note |
| DELETE | `/web/requests/api/notes/{note_id}` | Delete note |

---

## Mockup (Development)

**Source**: [pulldb/web/features/mockup/routes.py](../../pulldb/web/features/mockup/routes.py)

> **Note**: Development-only routes for design iteration. Not for production use.

### Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/web/mockup/job-details` | Job details mockup page |

### Features

The mockup pages provide:
- Draggable elements for layout testing
- Editable text for content iteration
- Sample data preview
- Export functionality for modifications

---

## LazyTable Widget API Pattern

Many admin pages use the LazyTable widget with this standard API pattern:

### Paginated Data Endpoint

```
GET /web/{module}/api/{resource}
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | int | Page number (0-indexed) |
| `pageSize` | int | Results per page |
| `sortColumn` | string | Column to sort by |
| `sortDirection` | string | "asc" or "desc" |
| `filter_{column}` | string | Column filter (comma-separated for multi) |

**Response:**
```json
{
  "rows": [...],
  "totalCount": 100,
  "filteredCount": 45,
  "page": 0,
  "pageSize": 50
}
```

### Distinct Values Endpoint

```
GET /web/{module}/api/{resource}/distinct
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `column` | string | Column to get values for |
| `filter_order` | string | Cascading filter order |

**Response:** `list[string]`

---

## Error Handling

### HTML Error Pages

Errors are rendered as HTML pages with appropriate styling:
- 401: Redirect to `/web/login`
- 403: Forbidden page
- 404: Not found page
- 500: Internal error page

### JSON API Errors

JSON endpoints return errors as:
```json
{
  "success": false,
  "message": "Error description"
}
```

---

## Multi-Language Examples

While the Web UI is primarily accessed via browser, these examples show programmatic session authentication and API calls.

### Session Login and API Call

#### Python

```python
"""Login to Web UI and make authenticated requests."""

import requests

WEB_BASE = "http://localhost:8000"


def create_session(username: str, password: str) -> requests.Session:
    """Create authenticated session with Web UI."""
    session = requests.Session()
    
    # Login
    response = session.post(
        f"{WEB_BASE}/web/login",
        data={"username": username, "password": password},
        allow_redirects=False,
    )
    
    if response.status_code != 303:  # Redirect on success
        raise Exception(f"Login failed: {response.status_code}")
    
    return session


def get_paginated_jobs(session: requests.Session, page: int = 0) -> dict:
    """Get paginated jobs from Web API."""
    response = session.get(
        f"{WEB_BASE}/web/jobs/api/paginated",
        params={
            "page": page,
            "pageSize": 50,
            "sortColumn": "submitted_at",
            "sortDirection": "desc",
        },
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


# Usage
session = create_session("admin", "your-password")
jobs = get_paginated_jobs(session)
print(f"Total jobs: {jobs['totalCount']}")
for job in jobs["rows"][:5]:
    print(f"  {job['id'][:8]}... - {job['target']} - {job['status']}")
```

#### PHP

```php
<?php
/**
 * Login to Web UI and make authenticated requests.
 */

$webBase = 'http://localhost:8000';

function createSession(string $username, string $password): array {
    global $webBase;
    
    $ch = curl_init("{$webBase}/web/login");
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, http_build_query([
        'username' => $username,
        'password' => $password,
    ]));
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_HEADER, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, false);
    
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    if ($httpCode !== 303) {
        throw new Exception("Login failed: HTTP {$httpCode}");
    }
    
    // Extract session cookie
    preg_match('/session_token=([^;]+)/', $response, $matches);
    return ['cookie' => "session_token={$matches[1]}"];
}

function getPaginatedJobs(array $session, int $page = 0): array {
    global $webBase;
    
    $params = http_build_query([
        'page' => $page,
        'pageSize' => 50,
        'sortColumn' => 'submitted_at',
        'sortDirection' => 'desc',
    ]);
    
    $ch = curl_init("{$webBase}/web/jobs/api/paginated?{$params}");
    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        "Cookie: {$session['cookie']}",
        "Accept: application/json",
    ]);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    
    $response = curl_exec($ch);
    curl_close($ch);
    
    return json_decode($response, true);
}

// Usage
$session = createSession('admin', 'your-password');
$jobs = getPaginatedJobs($session);
echo "Total jobs: {$jobs['totalCount']}\n";
```

#### Bash

```bash
#!/bin/bash
# Login to Web UI and make authenticated requests.

WEB_BASE="http://localhost:8000"
COOKIE_FILE=$(mktemp)

# Login and save session cookie
login() {
    curl -s -c "$COOKIE_FILE" -d "username=$1&password=$2" \
        -o /dev/null -w "%{http_code}" \
        "$WEB_BASE/web/login"
}

# Get paginated jobs
get_jobs() {
    curl -s -b "$COOKIE_FILE" \
        -H "Accept: application/json" \
        "$WEB_BASE/web/jobs/api/paginated?page=0&pageSize=50"
}

# Usage
status=$(login "admin" "your-password")
if [[ "$status" == "303" ]]; then
    echo "Login successful"
    jobs=$(get_jobs)
    echo "Total jobs: $(echo "$jobs" | jq .totalCount)"
    echo "$jobs" | jq -r '.rows[:5][] | "  \(.id[:8])... - \(.target) - \(.status)"'
else
    echo "Login failed: HTTP $status"
fi

rm -f "$COOKIE_FILE"
```

---

### HTMX-Style Requests

For HTMX-compatible requests, include the `HX-Request` header:

#### Python

```python
"""Make HTMX-style requests to Web UI endpoints."""

def htmx_request(session: requests.Session, path: str, target: str = None) -> str:
    """Make HTMX request and return HTML fragment."""
    headers = {
        "HX-Request": "true",
        "Accept": "text/html",
    }
    if target:
        headers["HX-Target"] = target
    
    response = session.get(f"{WEB_BASE}{path}", headers=headers)
    response.raise_for_status()
    return response.text


# Get job table as HTML fragment
html = htmx_request(session, "/web/jobs/api/paginated?page=0", target="job-table")
print(f"Received {len(html)} bytes of HTML")
```

---

### Cancel a Job via Web API

#### Python

```python
"""Cancel a job through the Web UI."""

def cancel_job(session: requests.Session, job_id: str) -> bool:
    """Cancel a job via Web API."""
    response = session.post(
        f"{WEB_BASE}/web/jobs/{job_id}/cancel",
        headers={"HX-Request": "true"},
    )
    return response.status_code == 200


# Usage
if cancel_job(session, "8b4c4a3a-85a1-4da2-9f3c-abc123def456"):
    print("Job canceled successfully")
else:
    print("Failed to cancel job")
```

---

*For REST API examples (HMAC authentication), see [REST-API.md](REST-API.md#multi-language-examples)*

---

*Generated: 2026-01-21 | Source: pulldb/web/features/*
