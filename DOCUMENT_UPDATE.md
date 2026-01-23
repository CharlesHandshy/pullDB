# pullDB Documentation Synchronization Plan

> **Generated**: January 17, 2026  
> **Purpose**: Comprehensive audit and action plan to bring all documentation to 100% sync with code reality  
> **Execution Model**: Iterative loop through categorized work items

---

## Executive Summary

This plan is the result of a **deep codebase audit** covering all components:
- ✅ **CLI** (~7,100 lines): 11 user commands, 9 admin groups, 32+ admin subcommands
- ✅ **Web UI** (~120 routes): 30+ HTML pages, 90+ API endpoints, HTMX/LazyTable architecture
- ✅ **Worker** (~15 modules): Full restore workflow, staging lifecycle, myloader execution
- ✅ **API** (~4,500 lines): 60+ REST endpoints, dual auth (HMAC + session)
- ✅ **Database** (18 tables): Complete schema with relationships, views, stored procedures
- ✅ **Auth** (~1,200 lines): bcrypt passwords, sessions, API keys, TOTP preparation

**Documentation Gap Analysis**: Multiple areas require updates to match current code functionality.

---

## Table of Contents

1. [Audit Findings Summary](#1-audit-findings-summary)
2. [Work Item Categories](#2-work-item-categories)
3. [Detailed Work Items](#3-detailed-work-items)
4. [Execution Loop Protocol](#4-execution-loop-protocol)
5. [Verification Checklist](#5-verification-checklist)

---

## 1. Audit Findings Summary

### 1.1 CLI Component Reality

| Command Group | Commands | Documented | Gap |
|---------------|----------|------------|-----|
| **User CLI** (`pulldb`) | 11 | Partial | Missing: `profile`, `setpass` details |
| **Admin CLI** (`pulldb-admin`) | 32 subcommands | Partial | Missing: `disallow`, `cleanup` details |

**Key Undocumented CLI Features**:
- `--custom-target` option (1-51 lowercase letters)
- `--suffix` option (1-3 lowercase letters)
- `--on-behalf-of` admin option
- Job ID prefix resolution (8+ characters)
- `qatemplate` restore mode
- Full `secrets` subcommand group
- Full `settings` subcommand group (push/pull/diff)

### 1.2 Web UI Component Reality

| Area | Routes | Documented | Gap |
|------|--------|------------|-----|
| Authentication | 12 | Partial | Missing: maintenance modal, password reset flow |
| Dashboard | 1 + partials | Partial | Missing: role-specific dashboards |
| Jobs | 16 | Partial | Missing: bulk actions, lazy table filters |
| Restore | 4 | Good | Missing: custom target, QA template |
| Manager | 3 | New | Needs documentation |
| Admin | 50+ | Minimal | Major gap - many features undocumented |
| Feature Requests | 5 | None | Completely undocumented |
| Audit Logs | 2 | None | Completely undocumented |

**Key Undocumented Web Features**:
- LazyTable widget (server-side pagination, filtering, bulk actions)
- Theme system (light/dark, admin-controlled presets)
- Database lifecycle management (lock, extend, delete, expire)
- Orphan database cleanup tools
- Host provisioning wizard
- API key approval workflow
- Feature request voting system
- Disallowed users management
- Job event log pruning
- Staging database cleanup

### 1.3 Worker Component Reality

| Phase | Documented | Gap |
|-------|------------|-----|
| Service Lifecycle | Good | Minor updates |
| Poll Loop | Good | Add backoff details |
| Job Executor | Partial | Missing checkpoints, cancellation windows |
| S3 Download | Good | Add disk capacity check |
| Restore (myloader) | Good | Add progress monitoring |
| Post-SQL | Minimal | Needs full documentation |
| Metadata Injection | None | Completely undocumented |
| Atomic Rename | Partial | Add procedure versioning |
| Staging Lifecycle | Partial | Add naming scheme |
| Admin Tasks | None | Completely undocumented |

**Key Undocumented Worker Features**:
- `pullDB` metadata table injection
- Stored procedure auto-deployment with versioning
- Admin task execution (force_delete_user, retention_cleanup)
- Stale job recovery mechanism
- Zombie cleanup at startup

### 1.4 API Component Reality

| Category | Endpoints | Documented | Gap |
|----------|-----------|------------|-----|
| Health | 2 | Good | - |
| Auth | 4 | Partial | Missing register flow |
| Users | 2 | Good | - |
| Jobs | 16 | Partial | Missing bulk operations |
| Hosts | 1 | Good | - |
| Backups | 2 | Good | - |
| Dropdowns | 3 | None | Undocumented |
| Feature Requests | 7 | None | Undocumented |
| Manager | 2 | None | Undocumented |
| Admin | 14 | Minimal | Major gap |

**Key Undocumented API Features**:
- `/api/jobs/{id}/lock` and `/api/jobs/{id}/unlock`
- `/api/jobs/{id}/extend` retention extension
- `/api/jobs/{id}/user-complete` user completion
- `/api/jobs/bulk-cancel` bulk operations
- `/api/feature-requests/*` entire group
- `/api/admin/*` most endpoints
- Dropdown search endpoints pattern

### 1.5 Database Schema Reality

| Table | Documented | Gap |
|-------|------------|-----|
| `auth_users` | Good | Add `locked_at` column |
| `auth_credentials` | Partial | Missing TOTP columns |
| `sessions` | Good | - |
| `api_keys` | Partial | Missing approval workflow |
| `db_hosts` | Good | - |
| `user_hosts` | Good | - |
| `jobs` | Partial | Missing 5+ columns |
| `job_events` | Good | - |
| `locks` | None | Undocumented |
| `settings` | Good | - |
| `admin_tasks` | None | Completely undocumented |
| `audit_logs` | None | Completely undocumented |
| `procedure_deployments` | None | Completely undocumented |
| `disallowed_users` | None | Completely undocumented |
| `feature_requests` | None | Completely undocumented |
| `feature_request_votes` | None | Completely undocumented |
| `feature_request_notes` | None | Completely undocumented |
| `schema_migrations` | Good | - |

### 1.6 Help Center Reality

| Page | Status | Gap |
|------|--------|-----|
| `index.html` | Good | Minor updates |
| `getting-started.html` | Good | - |
| `api/index.html` | Outdated | Missing 40+ endpoints |
| `cli/index.html` | Outdated | Missing commands/options |
| `concepts/job-lifecycle.html` | Partial | Missing states |
| `troubleshooting/index.html` | Good | - |
| `web-ui/index.html` | Good | - |
| `web-ui/dashboard.html` | Good | - |
| `web-ui/restore.html` | Outdated | Missing custom target |
| `web-ui/jobs.html` | Outdated | Missing lifecycle mgmt |
| `web-ui/profile.html` | Good | - |
| `web-ui/admin.html` | Outdated | Missing 10+ features |
| `web-ui/manager.html` | New | Minimal |

---

## 2. Work Item Categories

### Category A: Critical Documentation Gaps (User-Facing)

These items affect users trying to use documented features.

| ID | Item | Priority | Est. Effort |
|----|------|----------|-------------|
| ✅ A1 | CLI Reference - Add all missing commands/options | P0 | 4h |
| ✅ A2 | API Reference - Document 40+ undocumented endpoints | P0 | 6h |
| ✅ A3 | Web UI Admin - Document 10+ admin features | P0 | 4h |
| ✅ A4 | Database Schema - Update mysql-schema.md | P1 | 3h |

### Category B: New Features (Completely Undocumented)

| ID | Item | Priority | Est. Effort |
|----|------|----------|-------------|
| ✅ B1 | Feature Requests system documentation | P1 | 2h |
| ✅ B2 | Database Lifecycle Management guide | P1 | 3h |
| ✅ B3 | Admin Tasks (background jobs) documentation | P1 | 2h |
| ✅ B4 | LazyTable widget documentation | P2 | 2h |
| ✅ B5 | Theme System documentation | P2 | 1h |

### Category C: Index Updates (Machine-Readable)

| ID | Item | Priority | Est. Effort |
|----|------|----------|-------------|
| ✅ C1 | WORKSPACE-INDEX.md - Sync with current codebase | P1 | 2h |
| ✅ C2 | WORKSPACE-INDEX.json - Regenerate | P1 | 1h |
| ✅ C3 | KNOWLEDGE-POOL.md - Update facts | P1 | 2h |
| ✅ C4 | KNOWLEDGE-POOL.json - Regenerate | P1 | 1h |
| ✅ C5 | Help search-index.json - Regenerate | P2 | 1h |

### Category D: Help Center Updates

| ID | Item | Priority | Est. Effort |
|----|------|----------|-------------|
| ✅ D1 | CLI help page - Full rewrite | P1 | 3h |
| ✅ D2 | API help page - Full rewrite | P1 | 4h |
| ✅ D3 | Jobs help page - Add lifecycle management | P1 | 2h |
| ✅ D4 | Restore help page - Add custom target/QA template | P1 | 1h |
| ✅ D5 | Admin help page - Full rewrite | P1 | 4h |
| ✅ D6 | Job lifecycle concepts - Add missing states | P2 | 1h |

### Category E: Screenshot Updates

| ID | Item | Priority | Est. Effort |
|----|------|----------|-------------|
| ✅ E1 | Capture new admin pages (orphans, disallowed, etc.) | P2 | 2h |
| ✅ E2 | Update existing screenshots for UI changes | P2 | 2h |
| ⏸️ E3 | Annotate new screenshots | P2 | 2h |
| ✅ E4 | Regenerate screenshot inventory | P2 | 1h |

> **Status (2026-01-17):** E1 and E2 completed via Playwright browser automation against production server (port 8000). Screenshots captured:
> - `feature-requests-light.png` / `feature-requests-dark.png` - Feature Requests page with real data
> - `admin-task-status-light.png` / `admin-task-status-dark.png` - Admin Task (force_delete_user) results page
>
> **E3 Note:** Annotation requires manual work with image editing tools. Existing admin screenshots already have annotations.
>
> **Screenshot Transfer:** Captured screenshots are in Playwright MCP output directory. Copy to:
> - `pulldb/web/static/help/screenshots/light/requests/` 
> - `pulldb/web/static/help/screenshots/dark/requests/`
> - `pulldb/web/static/help/screenshots/annotated/light/admin/`
> - `pulldb/web/static/help/screenshots/annotated/dark/admin/`

### Category F: README and Entry Points

| ID | Item | Priority | Est. Effort |
|----|------|----------|-------------|
| ✅ F1 | README.md - Update command examples | P1 | 1h |
| ✅ F2 | docs/START-HERE.md - Update navigation | P1 | 1h |
| ✅ F3 | docs/HELP-PAGE-INDEX.md - Update inventory | P2 | 1h |

---

## 3. Detailed Work Items

### A1: CLI Reference - Complete Documentation

**File**: `docs/hca/pages/cli-reference.md`  
**Help Page**: `pulldb/web/help/pages/cli/index.html`

**Tasks**:
1. Document `pulldb restore` full options:
   - `--custom-target` (pattern: 1-51 lowercase letters)
   - `--suffix` (pattern: 1-3 lowercase letters)
   - `--on-behalf-of` (admin only)
   - `qatemplate` positional argument
   - `--backup-path` for specific backup selection
   
2. Document `pulldb profile <job_id>`:
   - Output format (phase breakdown)
   - Performance metrics (bytes/sec, duration)
   
3. Document `pulldb setpass`:
   - Required after admin password reset
   - Password requirements (8+ chars, complexity)
   
4. Document `pulldb-admin` subcommands:
   - `settings` group: list, get, set, reset, export, diff, pull, push
   - `secrets` group: list, get, set, delete, test, rotate-host
   - `jobs` group: list, cancel (all user jobs)
   - `backups` group: list, search with aggregated stats
   - `cleanup`: --dry-run, --execute, --older-than
   - `run-retention-cleanup`: scheduled retention
   - `hosts` group: list, add, provision, test, enable, disable, remove, cred
   - `users` group: list, show, enable, disable
   - `keys` group: pending, approve, revoke, list
   - `disallow` group: list, add, remove

5. Update environment variables section:
   - `PULLDB_API_TIMEOUT` (default: 30.0)
   - `PULLDB_S3ENV_DEFAULT` (default: prod)

---

### A2: API Reference - Complete Documentation

**File**: `docs/hca/pages/api-reference.md`  
**Help Page**: `pulldb/web/help/pages/api/index.html`

**Tasks**:
1. Document missing job endpoints:
   ```
   POST /api/jobs/{id}/lock
   POST /api/jobs/{id}/unlock
   POST /api/jobs/{id}/extend
   POST /api/jobs/{id}/user-complete
   POST /api/jobs/{id}/delete
   POST /api/jobs/bulk-cancel
   POST /api/jobs/mark-expired
   ```

2. Document dropdown search endpoints:
   ```
   GET /api/dropdown/customers?q=&limit=
   GET /api/dropdown/backups?q=&customer=&env=
   GET /api/dropdown/hosts?q=
   ```

3. Document feature request endpoints:
   ```
   GET /api/feature-requests
   GET /api/feature-requests/status-options
   GET /api/feature-requests/mine
   POST /api/feature-requests
   PATCH /api/feature-requests/{id}
   POST /api/feature-requests/{id}/vote
   DELETE /api/feature-requests/{id}
   ```

4. Document manager endpoints:
   ```
   GET /api/manager/team
   GET /api/manager/team/{user_id}/jobs
   ```

5. Document admin endpoints:
   ```
   POST /api/admin/prune-logs
   POST /api/admin/cleanup-staging
   POST /api/admin/delete-orphans
   GET /api/admin/retention-candidates
   GET /api/admin/orphan-databases
   GET /api/admin/user-orphan-databases
   POST /api/admin/approve-key
   POST /api/admin/revoke-key
   POST /api/admin/reactivate-key
   GET /api/admin/pending-keys
   POST /api/admin/rotate-host-secret/{hostname}
   ```

6. Document request/response schemas with examples

---

### A3: Web UI Admin Documentation

**File**: `docs/hca/pages/admin-guide.md`  
**Help Page**: `pulldb/web/help/pages/web-ui/admin.html`

**Tasks**:
1. Document Admin Dashboard page:
   - System statistics cards
   - Host health monitoring
   - Active jobs overview

2. Document Users Management:
   - User list with LazyTable
   - Enable/disable users
   - Force password reset
   - Assign hosts to users
   - View user job statistics

3. Document Hosts Management:
   - Host list with status
   - Add host (simple)
   - Provision host (full wizard)
   - Test connection
   - Enable/disable host
   - View host detail page
   - Credential rotation

4. Document API Keys Management:
   - Pending approval queue
   - Approve/revoke workflow
   - Key reactivation

5. Document Settings page:
   - All configurable settings
   - Setting categories
   - Default values

6. Document Cleanup Tools:
   - Job event log pruning
   - Staging database cleanup
   - Orphan database detection
   - User orphan databases
   - Retention cleanup

7. Document Disallowed Users:
   - Hardcoded list
   - Database additions

8. Document Locked Databases:
   - View locked DBs
   - Unlock capability

9. Document Audit Logs:
   - Log browsing
   - Filtering

---

### A4: Database Schema Documentation

**File**: `docs/hca/entities/mysql-schema.md`

**Tasks**:
1. Add missing tables:
   - `locks` (advisory locks)
   - `admin_tasks` (background tasks)
   - `audit_logs` (action audit trail)
   - `procedure_deployments` (stored procedure tracking)
   - `disallowed_users` (username blacklist)
   - `feature_requests` (feature voting)
   - `feature_request_votes` (vote tracking)
   - `feature_request_notes` (discussion)

2. Update existing tables:
   - `auth_users`: Add `locked_at`, update `role` enum
   - `auth_credentials`: Add `totp_secret`, `totp_enabled`
   - `api_keys`: Add approval workflow columns
   - `jobs`: Add `expires_at`, `locked_at`, `locked_by`, `db_dropped_at`, `superseded_at`, `superseded_by_job_id`, `active_target_key`

3. Document stored procedures:
   - `pulldb_atomic_rename` (v1.0.1)

4. Document views:
   - `active_jobs`

5. Add relationship diagram (Mermaid)

---

### B1: Feature Requests System

**New File**: `docs/hca/features/feature-requests.md`

**Tasks**:
1. Overview and purpose
2. User workflow (submit, vote)
3. Admin workflow (review, respond, close)
4. Status lifecycle (open → in_progress → complete/declined)
5. API endpoints reference
6. Web UI screenshots

---

### B2: Database Lifecycle Management

**New File**: `docs/hca/features/database-lifecycle.md`

**Tasks**:
1. Job status state machine (diagram)
2. Retention system:
   - Default retention period
   - Extension capability (1-12 months)
   - Expiration warnings
   - Cleanup grace period
3. Locking mechanism:
   - User locks
   - Lock reasons
   - Unlock flow
4. Deletion workflow:
   - User-initiated delete
   - Bulk delete
   - Force complete + delete
5. Supersession (new restore replaces old)
6. Web UI guide for each action
7. CLI commands for lifecycle management

---

### B3: Admin Tasks Documentation

**New File**: `docs/hca/features/admin-tasks.md`

**Tasks**:
1. Task types:
   - `force_delete_user`: Delete user + optionally drop databases
   - `scan_user_orphans`: Find databases for deleted users
   - `bulk_delete_jobs`: Mass deletion
   - `retention_cleanup`: Scheduled expiration processing
2. Task lifecycle (pending → running → complete/failed)
3. Single-task enforcement
4. Web UI task status page
5. Worker execution details

---

### B4: LazyTable Widget Documentation

**New File**: `docs/hca/widgets/lazy-table.md`

**Tasks**:
1. Purpose and architecture
2. Server-side pagination
3. Column sorting
4. Column filtering (text, checkbox)
5. Bulk selection
6. Custom action buttons
7. API contract for data endpoints
8. JavaScript API reference
9. Example implementation

---

### C1-C4: Index Updates

**WORKSPACE-INDEX.md Tasks**:
1. Update file counts
2. Add new packages (simulation, features)
3. Update HCA layer summary
4. Add missing key elements

**KNOWLEDGE-POOL.md Tasks**:
1. Update package version (currently shows v0.3.0, verify current)
2. Add new settings keys
3. Update entry points
4. Add admin task types
5. Add job status states
6. Update CLI HMAC authentication section

---

### D1-D6: Help Center Updates

**Each help page needs**:
1. Content accuracy review against code
2. Add missing features/options
3. Update screenshots where UI changed
4. Update search index entries

---

## 4. Execution Loop Protocol

### Pre-Loop Setup

```
1. Read this plan (DOCUMENT_UPDATE.md)
2. Load relevant Copilot instructions:
   - .github/copilot-instructions.md
   - .github/copilot-instructions-behavior.md
```

### Loop Iteration Format

For each work item, execute:

```markdown
## Iteration: [ITEM_ID]

### 1. Context Gathering
- Read current state of target file(s)
- Read relevant source code for accuracy
- Note specific line numbers requiring updates

### 2. Changes Required
- List specific changes with before/after

### 3. Implementation
- Execute edits
- Verify no syntax errors

### 4. Verification
- Confirm changes match source code
- Check cross-references still valid

### 5. Mark Complete
- Update this plan (mark item done)
- Log to SESSION-LOG.md
```

### Execution Order (Suggested)

**Phase 1: Foundation** (Items that others depend on)
1. A4 - Database Schema (other docs reference this)
2. C1/C2 - Workspace Index (navigation)
3. C3/C4 - Knowledge Pool (facts)

**Phase 2: Core Documentation** (Most user-facing impact)
4. A1 - CLI Reference
5. A2 - API Reference
6. A3 - Admin Guide

**Phase 3: New Features**
7. B2 - Database Lifecycle
8. B1 - Feature Requests
9. B3 - Admin Tasks

**Phase 4: Help Center**
10. D1 - CLI help page
11. D2 - API help page
12. D3-D6 - Other help pages

**Phase 5: Supporting**
13. B4/B5 - Widgets documentation
14. E1-E4 - Screenshots
15. F1-F3 - README and entry points
16. C5 - Help search index

---

## 5. Verification Checklist

After all work items complete:

### Documentation Accuracy

- [ ] Every CLI command has accurate documentation
- [ ] Every API endpoint has accurate documentation
- [ ] Every Web UI page/feature is documented
- [ ] Database schema matches actual migrations
- [ ] Help pages match current functionality

### Index Synchronization

- [ ] WORKSPACE-INDEX.md file counts are accurate
- [ ] WORKSPACE-INDEX.json regenerated
- [ ] KNOWLEDGE-POOL.md facts verified
- [ ] KNOWLEDGE-POOL.json regenerated
- [ ] Help search-index.json regenerated

### Cross-Reference Integrity

- [ ] All links in documentation resolve
- [ ] HCA layer assignments are correct
- [ ] README quick links work
- [ ] START-HERE navigation is complete

### Screenshot Currency

- [ ] All screenshots show current UI
- [ ] Annotations match current features
- [ ] Both light/dark themes captured
- [ ] Screenshot inventory is accurate

---

## Appendix: Code Reality Reference

### A. Job Status States (Complete List)

```python
class JobStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELING = "canceling"
    DEPLOYED = "deployed"
    EXPIRED = "expired"
    FAILED = "failed"
    COMPLETE = "complete"
    CANCELED = "canceled"
    DELETING = "deleting"
    DELETED = "deleted"
    SUPERSEDED = "superseded"
```

### B. User Roles (Complete List)

```python
class UserRole(Enum):
    USER = "user"
    MANAGER = "manager"
    ADMIN = "admin"
    SERVICE = "service"
```

### C. Admin Task Types

```python
class AdminTaskType(Enum):
    FORCE_DELETE_USER = "force_delete_user"
    SCAN_USER_ORPHANS = "scan_user_orphans"
    BULK_DELETE_JOBS = "bulk_delete_jobs"
    RETENTION_CLEANUP = "retention_cleanup"
```

### D. Settings Keys (from settings.py)

| Key | Type | Category |
|-----|------|----------|
| `default_dbhost` | string | hosts |
| `s3_bucket_path` | string | storage |
| `work_directory` | path | storage |
| `max_active_jobs_per_user` | integer | limits |
| `max_active_jobs_global` | integer | limits |
| `staging_retention_days` | integer | retention |
| `job_log_retention_days` | integer | retention |
| `default_retention_days` | integer | retention |
| `max_retention_days` | integer | retention |
| `expiring_warning_days` | integer | retention |
| `cleanup_grace_days` | integer | retention |

### E. Protected Databases (Never Dropped)

```python
PROTECTED_DATABASES = frozenset({
    "mysql", "information_schema", "performance_schema",
    "sys", "pulldb", "pulldb_service",
})
```

---

## Execution Prompt Template

Use this prompt for each iteration:

```
Execute work item [ITEM_ID] from DOCUMENT_UPDATE.md:

1. Read the target file(s) specified in the work item
2. Read relevant source code to verify accuracy
3. Make the documented changes
4. Verify the changes are correct
5. Mark the item complete in DOCUMENT_UPDATE.md

Follow HCA principles. Reference source code line numbers for accuracy.
Do not proceed to the next item - wait for confirmation.
```

---

## 6. Detailed Delta Analysis (Code vs Documentation)

### 6.1 CLI Reference Delta (`docs/hca/pages/cli-reference.md`)

**Current State**: 760 lines, covers basic commands  
**Reality**: ~7,100 lines of CLI code with many undocumented features

| Feature | In Docs | In Code | Gap |
|---------|---------|---------|-----|
| `--custom-target` | ❌ No | ✅ `main.py:L180-220` | Full option undocumented |
| `--suffix` | ✅ Partial | ✅ `main.py:L165` | Missing pattern validation |
| `--on-behalf-of` | ❌ No | ✅ `main.py:L225` | Admin-only feature |
| `pulldb profile` | ✅ Listed | ✅ `main.py:L1800+` | Missing output format |
| `pulldb setpass` | ✅ Listed | ✅ `main.py:L2400+` | Missing requirements |
| `pulldb-admin settings push/pull/diff` | ❌ No | ✅ `settings.py` | New subcommands |
| `pulldb-admin secrets *` | ❌ No | ✅ `secrets_commands.py` | Entire group missing |
| `pulldb-admin backups *` | ❌ No | ✅ `backup_commands.py` | Entire group missing |
| `pulldb-admin disallow *` | ❌ No | ✅ `admin_commands.py` | Entire group missing |
| `pulldb-admin hosts provision` | ❌ No | ✅ `admin_commands.py:L400+` | Full wizard |
| Job ID prefix resolution | ❌ No | ✅ `main.py:L150+` | 8+ char prefix support |
| HMAC authentication | ✅ Partial | ✅ `auth.py` | Missing signature details |
| Environment variables | ✅ Partial | ✅ Multiple | Missing 5+ variables |

**Specific Changes Required**:

```markdown
## ADD to cli-reference.md after "restore" section:

### restore (Advanced Options)

| Option | Description |
|--------|-------------|
| `--custom-target=NAME` | Override target database name (1-51 lowercase letters, a-z only) |
| `--suffix=ABC` | Append 1-3 letter suffix to target name |
| `--on-behalf-of=USER` | (Admin only) Submit job for another user |
| `--backup-path=S3_KEY` | Use specific backup (from `pulldb list` output) |

**Custom Target Rules:**
- Must be 1-51 lowercase letters only (a-z)
- Cannot be used with `--suffix`
- Cannot match existing customer names in S3
```

---

### 6.2 API Reference Delta (`docs/hca/pages/api-reference.md`)

**Current State**: 843 lines, basic CRUD operations  
**Reality**: ~60 endpoints in `pulldb/api/main.py` (4,477 lines)

**Missing Endpoints** (must add):

```markdown
## Job Lifecycle Endpoints (NEW SECTION)

### POST /api/jobs/{job_id}/lock
Lock a deployed database to prevent expiration.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reason` | string | ❌ | Lock reason (default: "Locked via API") |

**Response:** `{"success": true, "locked_at": "2026-01-17T..."}`

---

### POST /api/jobs/{job_id}/unlock
Remove lock from a database.

**Response:** `{"success": true, "unlocked_at": "2026-01-17T..."}`

---

### POST /api/jobs/{job_id}/extend
Extend database retention period.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `months` | integer | ❌ | Extension period 1-12 (default: 1) |

**Response:** `{"success": true, "new_expires_at": "2026-07-17T..."}`

---

### POST /api/jobs/{job_id}/user-complete
Mark a deployed database as complete (ready for cleanup).

**Response:** `{"success": true, "status": "complete"}`

---

### POST /api/jobs/{job_id}/delete
Request database deletion (async via admin_tasks queue).

**Response:** `{"success": true, "status": "deleting"}`

---

### POST /api/jobs/bulk-cancel
Cancel multiple jobs matching filters.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `view` | string | ❌ | "active" (default) |
| `filter_status` | string | ❌ | Status filter |
| `filter_dbhost` | string | ❌ | Host filter |
| `filter_user_code` | string | ❌ | User filter |
| `confirmation` | string | ✅ | Must be "CANCEL ALL" |

---

## Dropdown Search Endpoints (NEW SECTION)

### GET /api/dropdown/customers
Search customers for restore form autocomplete.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `q` | string | Search query |
| `limit` | integer | Max results (default: 20) |
| `env` | string | S3 environment (staging/prod) |

---

### GET /api/dropdown/backups
Search backups for a customer.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `customer` | string | Customer name |
| `q` | string | Date filter |
| `env` | string | S3 environment |
| `limit` | integer | Max results |

---

### GET /api/dropdown/hosts
Search available hosts for user.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `q` | string | Search query |

---

## Feature Requests Endpoints (NEW SECTION)

### GET /api/feature-requests
List all feature requests with pagination.

### POST /api/feature-requests
Submit a new feature request.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | ✅ | 5-200 characters |
| `description` | string | ❌ | Up to 2000 characters |

### POST /api/feature-requests/{id}/vote
Vote on a feature request.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `vote_value` | integer | ✅ | 0 (remove) or 1 (upvote) |

### PATCH /api/feature-requests/{id}
(Admin) Update request status.

### DELETE /api/feature-requests/{id}
(Admin) Delete a request.

---

## Admin Endpoints (EXPANDED)

### POST /api/admin/prune-logs
Prune old job event logs.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `days` | integer | ❌ | Keep logs newer than N days (default: 90) |
| `dry_run` | boolean | ❌ | Preview only (default: false) |

---

### POST /api/admin/cleanup-staging
Clean orphaned staging databases.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `days` | integer | ❌ | Older than N days (default: 7) |
| `dbhost` | string | ❌ | Specific host (default: all) |
| `dry_run` | boolean | ❌ | Preview only |

---

### POST /api/admin/approve-key
Approve a pending API key.

**Request Body:** `{"key_id": "key_xxx..."}`

---

### POST /api/admin/revoke-key
Revoke an active API key.

**Request Body:** `{"key_id": "key_xxx...", "reason": "optional"}`

---

### POST /api/admin/rotate-host-secret/{hostname}
Rotate MySQL credentials for a host.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `new_password` | string | ❌ | Specific password (or auto-generate) |
| `password_length` | integer | ❌ | Length if auto-generating (16-64) |
```

---

### 6.3 MySQL Schema Delta (`docs/hca/entities/mysql-schema.md`)

**Current State**: 472 lines, core tables only  
**Reality**: 18 tables, 1 view, stored procedures

**Missing Tables** (must document):

```markdown
## Admin & Audit Tables (NEW SECTION)

### admin_tasks

Background task queue for long-running admin operations.

```sql
CREATE TABLE admin_tasks (
    task_id CHAR(36) PRIMARY KEY,
    task_type ENUM('force_delete_user','scan_user_orphans',
                   'bulk_delete_jobs','retention_cleanup') NOT NULL,
    status ENUM('pending','running','complete','failed') DEFAULT 'pending',
    requested_by CHAR(36) NOT NULL,
    target_user_id CHAR(36) NULL,
    parameters_json JSON NULL,
    result_json JSON NULL,
    created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
    started_at TIMESTAMP(6) NULL,
    completed_at TIMESTAMP(6) NULL,
    error_detail TEXT NULL,
    worker_id VARCHAR(255) NULL,
    running_task_type VARCHAR(50) GENERATED ALWAYS AS (
        CASE WHEN status = 'running' THEN task_type ELSE NULL END
    ) STORED,
    UNIQUE KEY idx_admin_tasks_single_running (running_task_type)
);
```

**Virtual Column**: `running_task_type` enforces only one task of each type can run simultaneously.

---

### audit_logs

Audit trail for administrative actions.

```sql
CREATE TABLE audit_logs (
    audit_id CHAR(36) PRIMARY KEY,
    actor_user_id CHAR(36) NOT NULL,
    target_user_id CHAR(36) NULL,
    action VARCHAR(50) NOT NULL,
    detail TEXT NULL,
    context_json JSON NULL,
    created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
    INDEX idx_audit_logs_actor (actor_user_id),
    INDEX idx_audit_logs_action (action),
    INDEX idx_audit_logs_created (created_at)
);
```

**Action Types**: `submit_for_user`, `cancel_job`, `approve_key`, `revoke_key`, `enable_user`, `disable_user`, `force_password_reset`, etc.

---

### disallowed_users

Username blacklist for registration.

```sql
CREATE TABLE disallowed_users (
    username VARCHAR(100) PRIMARY KEY,
    reason VARCHAR(500) NULL,
    is_hardcoded BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
    created_by CHAR(36) NULL
);
```

**Note**: Hardcoded entries from `domain/validation.py` are mirrored here with `is_hardcoded=TRUE`.

---

### feature_requests

User feature request tracking.

```sql
CREATE TABLE feature_requests (
    request_id CHAR(36) PRIMARY KEY,
    submitted_by_user_id CHAR(36) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT NULL,
    status ENUM('open','in_progress','complete','declined') DEFAULT 'open',
    vote_score INT DEFAULT 0,
    upvote_count INT UNSIGNED DEFAULT 0,
    created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    admin_response TEXT NULL,
    FOREIGN KEY (submitted_by_user_id) REFERENCES auth_users(user_id)
);
```

---

### feature_request_votes

Vote tracking per user per request.

```sql
CREATE TABLE feature_request_votes (
    vote_id CHAR(36) PRIMARY KEY,
    request_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    vote_value TINYINT NOT NULL,  -- 1 = upvote
    created_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uk_user_request (user_id, request_id),
    FOREIGN KEY (request_id) REFERENCES feature_requests(request_id) ON DELETE CASCADE
);
```

---

### procedure_deployments

Track stored procedure deployments per host.

```sql
CREATE TABLE procedure_deployments (
    id CHAR(36) PRIMARY KEY,
    host VARCHAR(255) NOT NULL,
    procedure_name VARCHAR(64) NOT NULL,
    version_deployed VARCHAR(20) NOT NULL,
    deployed_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
    deployed_by VARCHAR(50),
    deployment_reason ENUM('initial','version_mismatch','missing'),
    job_id CHAR(36) NULL,
    UNIQUE KEY uk_host_procedure (host, procedure_name)
);
```

---

## Updated Table: jobs

**New Columns** (add to existing documentation):

```sql
-- Retention & lifecycle
expires_at TIMESTAMP(6) NULL,        -- When database expires
locked_at TIMESTAMP(6) NULL,         -- User lock timestamp
locked_by VARCHAR(255) NULL,         -- Who locked it
db_dropped_at TIMESTAMP(6) NULL,     -- When database was dropped

-- Supersession
superseded_at TIMESTAMP(6) NULL,
superseded_by_job_id CHAR(36) NULL,

-- Target exclusivity (virtual column)
active_target_key VARCHAR(520) GENERATED ALWAYS AS (
    CASE WHEN status IN ('queued','running','canceling') 
         THEN CONCAT(target,'@@',dbhost) 
         ELSE NULL 
    END
) VIRTUAL,
UNIQUE KEY idx_jobs_active_target (active_target_key)
```

---

## Updated Table: auth_users

**New Columns**:

```sql
role ENUM('user','manager','admin','service') DEFAULT 'user',
manager_id CHAR(36) NULL,           -- FK to manager user
max_active_jobs INT NULL,           -- Per-user limit override
last_maintenance_ack DATE NULL,     -- Maintenance modal tracking
locked_at TIMESTAMP(6) NULL,        -- System account protection
```

---

## Stored Procedures

### pulldb_atomic_rename

Zero-downtime database rename procedure.

**Version**: 1.0.1  
**Location**: Auto-deployed by worker to each target host  
**Tracking**: `procedure_deployments` table

```sql
-- Signature
CALL pulldb_atomic_rename(
    @staging_db VARCHAR(64),  -- Source staging database
    @target_db VARCHAR(64),   -- Final database name
    @result VARCHAR(255) OUTPUT
);
```

**Deployment Logic** (in `pulldb/worker/atomic_rename.py`):
1. Check `procedure_deployments` for current version
2. If missing or version < 1.0.1, deploy fresh
3. Uses advisory lock to prevent concurrent deployments
```

---

## 7. Execution Loop Master Prompt

Copy this prompt to execute work items iteratively:

```markdown
# Execute Documentation Update Item

**Reference**: /home/charleshandshy/Projects/pullDB/DOCUMENT_UPDATE.md
**Item ID**: [INSERT_ITEM_ID e.g., A1, B2, etc.]

## Instructions

1. **Read the work item** from DOCUMENT_UPDATE.md section 3 (Detailed Work Items)
2. **Read the target documentation file(s)** specified in the work item
3. **Read the relevant source code** to verify accuracy:
   - CLI: `pulldb/cli/*.py`
   - API: `pulldb/api/main.py`
   - Worker: `pulldb/worker/*.py`
   - Domain: `pulldb/domain/*.py`
   - Schema: `schema/pulldb_service/*.sql`
   
4. **Make the changes** following HCA layer principles
5. **Verify accuracy** against source code
6. **Update DOCUMENT_UPDATE.md** to mark item complete:
   - Change `| ID |` row status from ` ` to `✅`

## Validation Checklist

Before completing:
- [ ] All code references verified against actual source
- [ ] No placeholder text remains
- [ ] Links resolve correctly
- [ ] Format consistent with existing documentation
- [ ] HCA layer assignment correct (if applicable)

## Context Files to Load

Based on item category:
- **A (CLI/API docs)**: Load copilot-instructions-python.md
- **B (New features)**: Load copilot-instructions-business-logic.md  
- **C (Indexes)**: Load WORKSPACE-INDEX.md current state
- **D (Help pages)**: Load docs/HELP-PAGE-INDEX.md
- **E (Screenshots)**: Load docs/help-screenshot-annotations.yaml
- **F (README)**: Load constitution.md for project facts

---

**DO NOT proceed to next item without user confirmation.**
```

---

## 8. Complete Web UI Route & Template Inventory

### 8.1 Template Files (45 Active Templates)

| Template Path | Purpose | Documented |
|---------------|---------|------------|
| `base.html` | Main layout with sidebar | ✅ |
| `base_auth.html` | Auth pages layout (no sidebar) | ✅ |
| **Authentication** | | |
| `features/auth/login.html` | Login form | ✅ |
| `features/auth/change_password.html` | Password change | Partial |
| `features/auth/profile.html` | User profile + API keys | Partial |
| `features/auth/maintenance.html` | Maintenance acknowledgment modal | ❌ |
| **Dashboard** | | |
| `features/dashboard/dashboard.html` | Main dashboard container | ✅ |
| `features/dashboard/_admin_dashboard.html` | Admin stats partial | ❌ |
| `features/dashboard/_manager_dashboard.html` | Manager stats partial | ❌ |
| `features/dashboard/_user_dashboard.html` | User stats partial | ❌ |
| **Jobs** | | |
| `features/jobs/jobs.html` | Jobs list with LazyTable | Partial |
| `features/jobs/details.html` | Job detail with phases | Partial |
| **Restore** | | |
| `features/restore/restore.html` | Restore wizard | Partial |
| `features/restore/partials/backup_results.html` | HTMX backup search | ❌ |
| `features/restore/partials/customer_results.html` | HTMX customer search | ❌ |
| **Manager** | | |
| `features/manager/manager.html` | Team management | ❌ NEW |
| **Admin** | | |
| `features/admin/admin.html` | Admin dashboard | Minimal |
| `features/admin/users.html` | User management | ❌ |
| `features/admin/hosts.html` | Host list | ❌ |
| `features/admin/host_detail.html` | Host configuration | ❌ |
| `features/admin/settings.html` | System settings | ❌ |
| `features/admin/api_keys.html` | API key approval | ❌ |
| `features/admin/styleguide.html` | Component reference | ❌ |
| `features/admin/prune_preview.html` | Job log pruning | ❌ |
| `features/admin/cleanup_preview.html` | Staging cleanup | ❌ |
| `features/admin/orphan_preview.html` | Orphan databases | ❌ |
| `features/admin/user_orphans.html` | Per-user orphans | ❌ |
| `features/admin/disallowed_users.html` | Username blacklist | ❌ |
| `features/admin/locked_databases.html` | Locked DB management | ❌ |
| `features/admin/admin_task_status.html` | Background task progress | ❌ |
| `features/admin/partials/_appearance.html` | Theme settings partial | ❌ |
| `features/admin/partials/orphans.html` | Orphan list partial | ❌ |
| **Feature Requests** | | |
| `features/requests/index.html` | Feature request list | ❌ NEW |
| **Audit** | | |
| `features/audit/index.html` | Audit log browser | ❌ NEW |
| **Errors** | | |
| `features/errors/404.html` | Not found page | ✅ |
| `features/errors/error.html` | Generic error page | ✅ |
| **Widgets/Partials** | | |
| `widgets/stats_bar.html` | Statistics bar | ❌ |
| `partials/breadcrumbs.html` | Breadcrumb navigation | ❌ |
| `partials/searchable_dropdown.html` | Autocomplete widget | ❌ |
| `partials/icons/_index.html` | Icon macros | ❌ |

### 8.2 Web Routes by Feature Area

#### Authentication Routes (`pulldb/web/features/auth/routes.py`)

| Method | Path | Handler | Template | Doc Status |
|--------|------|---------|----------|------------|
| GET | `/web/login` | `login_page` | `auth/login.html` | ✅ |
| POST | `/web/login` | `login_submit` | Redirect | ✅ |
| GET | `/web/logout` | `logout` | Redirect | ✅ |
| GET | `/web/profile` | `profile_page` | `auth/profile.html` | Partial |
| POST | `/web/profile/change-password` | `change_password` | JSON | ❌ |
| GET | `/web/change-password` | `change_password_page` | `auth/change_password.html` | ❌ |
| POST | `/web/change-password` | `change_password_submit` | Redirect | ❌ |
| GET | `/web/api-key/download` | `download_api_key` | File download | ❌ |
| POST | `/web/api-key/delete` | `delete_api_key` | JSON | ❌ |
| GET | `/web/maintenance` | `maintenance_page` | `auth/maintenance.html` | ❌ |
| POST | `/web/maintenance/acknowledge` | `acknowledge_maintenance` | Redirect | ❌ |

#### Dashboard Routes (`pulldb/web/features/dashboard/routes.py`)

| Method | Path | Handler | Template | Doc Status |
|--------|------|---------|----------|------------|
| GET | `/web/dashboard` | `dashboard` | `dashboard/dashboard.html` | Partial |

#### Jobs Routes (`pulldb/web/features/jobs/routes.py`)

| Method | Path | Handler | Template | Doc Status |
|--------|------|---------|----------|------------|
| GET | `/web/jobs` | `jobs_page` | `jobs/jobs.html` | ✅ |
| GET | `/web/jobs/{job_id}` | `job_details` | `jobs/details.html` | ✅ |
| POST | `/web/jobs/{job_id}/cancel` | `cancel_job` | JSON | ✅ |
| POST | `/web/jobs/{job_id}/delete` | `delete_database` | JSON | ❌ |
| POST | `/web/jobs/{job_id}/lock` | `lock_job` | JSON | ❌ |
| POST | `/web/jobs/{job_id}/unlock` | `unlock_job` | JSON | ❌ |
| POST | `/web/jobs/{job_id}/extend` | `extend_retention` | JSON | ❌ |
| POST | `/web/jobs/{job_id}/user-complete` | `user_complete` | JSON | ❌ |
| POST | `/web/jobs/bulk-delete` | `bulk_delete` | JSON | ❌ |
| GET | `/web/jobs/{job_id}/events` | `get_events` | JSON | ❌ |
| GET | `/web/api/jobs` | `api_paginated` | JSON (LazyTable) | ❌ |
| GET | `/web/api/jobs/distinct` | `api_distinct` | JSON | ❌ |
| POST | `/web/jobs/bulk-cancel` | `bulk_cancel` | JSON | ❌ |
| POST | `/web/jobs/mark-superseded` | `mark_superseded` | JSON | ❌ |
| POST | `/web/jobs/mark-expired` | `mark_expired` | JSON | ❌ |

#### Restore Routes (`pulldb/web/features/restore/routes.py`)

| Method | Path | Handler | Template | Doc Status |
|--------|------|---------|----------|------------|
| GET | `/web/restore` | `restore_page` | `restore/restore.html` | Partial |
| POST | `/web/restore` | `submit_restore` | Redirect | Partial |
| GET | `/web/api/backups/search` | `search_backups` | JSON | ❌ |
| GET | `/web/restore/backup-results` | `backup_results_htmx` | HTMX partial | ❌ |

#### Manager Routes (`pulldb/web/features/manager/routes.py`)

| Method | Path | Handler | Template | Doc Status |
|--------|------|---------|----------|------------|
| GET | `/web/manager` | `manager_page` | `manager/manager.html` | ❌ NEW |
| GET | `/web/api/manager/team` | `api_team` | JSON (LazyTable) | ❌ |
| POST | `/web/manager/reset-password/{user_id}` | `reset_team_member_password` | JSON | ❌ |

#### Admin Routes (`pulldb/web/features/admin/routes.py`) - 50+ Routes

| Method | Path | Handler | Doc Status |
|--------|------|---------|------------|
| GET | `/web/admin` | `admin_page` | Minimal |
| GET | `/web/admin/styleguide` | `styleguide_page` | ❌ |
| GET | `/web/admin/users` | `list_users` | ❌ |
| POST | `/web/admin/users/{id}/enable` | `enable_user` | ❌ |
| POST | `/web/admin/users/{id}/disable` | `disable_user` | ❌ |
| DELETE | `/web/admin/users/{id}` | `delete_user` | ❌ |
| GET | `/web/admin/users/{id}/force-delete-preview` | `force_delete_preview` | ❌ |
| POST | `/web/admin/users/{id}/force-delete` | `force_delete_user` | ❌ |
| GET | `/web/admin/admin-tasks/{id}` | `get_admin_task_page` | ❌ |
| GET | `/web/admin/admin-tasks/{id}/json` | `get_admin_task_json` | ❌ |
| POST | `/web/admin/users/{id}/role` | `update_user_role` | ❌ |
| POST | `/web/admin/users/add` | `add_user` | ❌ |
| POST | `/web/admin/users/{id}/manager` | `update_user_manager` | ❌ |
| POST | `/web/admin/users/{id}/force-password-reset` | `force_password_reset` | ❌ |
| POST | `/web/admin/users/{id}/clear-password-reset` | `clear_password_reset` | ❌ |
| POST | `/web/admin/users/{id}/assign-temp-password` | `assign_temp_password` | ❌ |
| GET | `/web/admin/users/{id}/hosts` | `get_user_hosts` | ❌ |
| POST | `/web/admin/users/{id}/hosts` | `update_user_hosts` | ❌ |
| GET | `/web/admin/hosts` | `hosts_page` | ❌ |
| POST | `/web/admin/hosts/add` | `add_host` | ❌ |
| POST | `/web/admin/hosts/check-alias` | `check_alias` | ❌ |
| POST | `/web/admin/hosts/{id}/enable` | `enable_host` | ❌ |
| POST | `/web/admin/hosts/{id}/disable` | `disable_host` | ❌ |
| POST | `/web/admin/hosts/{id}/test` | `test_host` | ❌ |
| GET | `/web/admin/hosts/{id}` | `host_detail_page` | ❌ |
| POST | `/web/admin/hosts/{id}/settings` | `update_host_settings` | ❌ |
| POST | `/web/admin/hosts/{id}/provision` | `provision_host` | ❌ |
| GET | `/web/admin/hosts/{id}/delete-preview` | `delete_host_preview` | ❌ |
| POST | `/web/admin/hosts/{id}/delete` | `delete_host` | ❌ |
| POST | `/web/admin/hosts/{id}/rotate-credentials` | `rotate_host_credentials` | ❌ |
| GET | `/web/admin/settings` | `settings_page` | ❌ |
| POST | `/web/admin/settings/{key}` | `update_setting` | ❌ |
| DELETE | `/web/admin/settings/{key}` | `delete_setting` | ❌ |
| POST | `/web/admin/settings/theme` | `update_theme` | ❌ |
| POST | `/web/admin/settings/work-directory` | `create_directory` | ❌ |
| GET | `/web/admin/prune` | `prune_preview_page` | ❌ |
| POST | `/web/admin/prune/execute` | `prune_execute` | ❌ |
| POST | `/web/admin/prune` | `prune_redirect` | ❌ |
| GET | `/web/admin/cleanup` | `cleanup_preview_page` | ❌ |
| POST | `/web/admin/cleanup/execute` | `cleanup_execute` | ❌ |
| POST | `/web/admin/cleanup` | `cleanup_redirect` | ❌ |
| GET | `/web/admin/orphan-preview` | `orphan_preview_page` | ❌ |
| POST | `/web/admin/orphans/execute` | `orphan_execute` | ❌ |
| GET | `/web/admin/orphans` | `orphans_page` | ❌ |
| POST | `/web/admin/orphans/delete` | `orphan_delete` | ❌ |
| GET | `/web/admin/user-orphans` | `user_orphans_page` | ❌ |
| POST | `/web/admin/user-orphans/scan` | `user_orphans_scan` | ❌ |
| POST | `/web/admin/user-orphans/delete` | `user_orphans_delete` | ❌ |
| POST | `/web/admin/user-orphans/execute` | `user_orphans_execute` | ❌ |
| POST | `/web/admin/jobs/{id}/force-complete-delete` | `force_complete_delete` | ❌ |
| GET | `/web/admin/api-keys` | `api_keys_page` | ❌ |
| GET | `/web/admin/disallowed` | `disallowed_page` | ❌ |
| POST | `/web/admin/locked/{id}/unlock` | `unlock_locked_database` | ❌ |
| GET | `/web/admin/locked` | `locked_databases_page` | ❌ |
| POST | `/web/admin/api-keys/approve` | `approve_key` | ❌ |
| POST | `/web/admin/api-keys/revoke` | `revoke_key` | ❌ |
| DELETE | `/web/admin/api-keys/{id}` | `delete_key` | ❌ |
| GET | `/web/admin/users/{id}/api-keys` | `get_user_api_keys` | ❌ |
| GET | `/web/admin/api/hosts` | `api_hosts` | ❌ |
| GET | `/web/admin/api/hosts/{id}` | `api_host_detail` | ❌ |
| POST | `/web/admin/api/hosts/{id}/rotate` | `api_rotate_secret` | ❌ |
| GET | `/web/admin/api/users` | `api_users` | ❌ |
| GET | `/web/admin/api/users/distinct` | `api_users_distinct` | ❌ |
| GET | `/web/admin/api/theme/css` | `theme_css` | ❌ |
| GET | `/web/admin/api/theme/settings` | `theme_settings` | ❌ |
| GET | `/web/admin/api/theme/presets` | `list_color_presets` | ❌ |
| GET | `/web/admin/api/theme/schemas` | `list_theme_schemas` | ❌ |
| POST | `/web/admin/api/theme/save` | `save_theme` | ❌ |
| GET | `/web/admin/api/theme/version` | `theme_version` | ❌ |
| GET | `/web/admin/api/prune/candidates` | `api_prune_candidates` | ❌ |
| GET | `/web/admin/api/prune/distinct` | `api_prune_distinct` | ❌ |
| GET | `/web/admin/api/cleanup/candidates` | `api_cleanup_candidates` | ❌ |
| GET | `/web/admin/api/cleanup/distinct` | `api_cleanup_distinct` | ❌ |
| GET | `/web/admin/api/orphans` | `api_orphans` | ❌ |
| GET | `/web/admin/api/orphans/distinct` | `api_orphan_distinct` | ❌ |
| GET | `/web/admin/api/user-orphans` | `api_user_orphans` | ❌ |
| GET | `/web/admin/api/user-orphans/distinct` | `api_user_orphan_distinct` | ❌ |
| GET/POST/DELETE | `/web/admin/disallowed/*` | Disallowed CRUD | ❌ |

#### Feature Requests Routes (`pulldb/web/features/requests/routes.py`)

| Method | Path | Handler | Template | Doc Status |
|--------|------|---------|----------|------------|
| GET | `/web/requests` | `requests_page` | `requests/index.html` | ❌ NEW |
| GET | `/web/api/requests` | `api_requests` | JSON (LazyTable) | ❌ |
| POST | `/web/requests/create` | `create_request` | JSON | ❌ |
| POST | `/web/requests/{id}/vote` | `vote_request` | JSON | ❌ |

#### Audit Routes (`pulldb/web/features/audit/routes.py`)

| Method | Path | Handler | Template | Doc Status |
|--------|------|---------|----------|------------|
| GET | `/web/audit` | `audit_page` | `audit/index.html` | ❌ NEW |
| GET | `/web/api/audit` | `get_audit_logs_api` | JSON (LazyTable) | ❌ |

---

## 9. Help Center Content Inventory

### 9.1 Current Help Pages (13 Total)

| Path | Title | Last Updated | Accuracy |
|------|-------|--------------|----------|
| `/web/help/index.html` | Help Center | Unknown | ⚠️ Check |
| `/web/help/pages/getting-started.html` | Getting Started | Unknown | ⚠️ Check |
| `/web/help/pages/api/index.html` | API Reference | Unknown | ❌ Outdated |
| `/web/help/pages/cli/index.html` | CLI Reference | Unknown | ❌ Outdated |
| `/web/help/pages/concepts/job-lifecycle.html` | Job Lifecycle | Unknown | ⚠️ Missing states |
| `/web/help/pages/troubleshooting/index.html` | Troubleshooting | Unknown | ⚠️ Check |
| `/web/help/pages/web-ui/index.html` | Web UI Overview | Unknown | ✅ Recent |
| `/web/help/pages/web-ui/dashboard.html` | Dashboard Guide | Unknown | ⚠️ Missing roles |
| `/web/help/pages/web-ui/restore.html` | Restore Wizard | Unknown | ❌ Missing features |
| `/web/help/pages/web-ui/jobs.html` | Jobs & History | Unknown | ❌ Missing lifecycle |
| `/web/help/pages/web-ui/profile.html` | Profile & Settings | Unknown | ✅ Recent |
| `/web/help/pages/web-ui/admin.html` | Administration | Unknown | ❌ Major gaps |
| `/web/help/pages/web-ui/manager.html` | Team Management | Unknown | ⚠️ New/minimal |

### 9.2 Help Pages Needed

| Proposed Page | Content |
|---------------|---------|
| `concepts/database-lifecycle.html` | Lock, extend, expire, delete workflow |
| `concepts/authentication.html` | HMAC, sessions, API keys |
| `web-ui/feature-requests.html` | Voting system |
| `admin/cleanup-tools.html` | Prune, cleanup, orphans |
| `admin/host-provisioning.html` | Full wizard documentation |

---

## 10. Screenshot Update Requirements

### 10.1 Current Screenshot Status

| Category | Light | Dark | Annotated | Needs Update |
|----------|-------|------|-----------|--------------|
| Login/Auth | 5 | 5 | 10 | ❌ |
| Dashboard | 5 | 5 | 10 | ⚠️ Role partials |
| Restore | 6 | 6 | 12 | ⚠️ Custom target |
| Jobs | 10 | 10 | 20 | ⚠️ Lifecycle actions |
| Profile | 4 | 4 | 8 | ❌ |
| Admin | 20 | 20 | 40 | ⚠️ Many new pages |
| Manager | 0 | 0 | 0 | 🆕 Needed |
| Feature Requests | 0 | 0 | 0 | 🆕 Needed |
| Audit | 0 | 0 | 0 | 🆕 Needed |

### 10.2 New Screenshots Needed

```yaml
# Add to docs/help-screenshot-annotations.yaml

manager:
  - id: manager-team-list
    description: Team member list with LazyTable
    theme: both
    annotations:
      - label: "Team member table"
        position: center
      - label: "Reset password action"
        position: right

feature-requests:
  - id: requests-list
    description: Feature request list with voting
    theme: both
    annotations:
      - label: "Vote button"
        position: right
      - label: "Status badges"
        position: left

  - id: requests-submit
    description: Submit new feature request modal
    theme: both

admin-orphans:
  - id: orphan-preview
    description: Orphan database detection preview
    theme: both
    annotations:
      - label: "Scan results"
        position: center
      - label: "Delete action"
        position: right

audit-logs:
  - id: audit-list
    description: Audit log browser with filters
    theme: both
    annotations:
      - label: "Action filter"
        position: top
      - label: "Actor column"
        position: left
```

---

## 11. Prioritized Execution Batches

### Batch 1: Foundation (Hours 1-8)
**Goal**: Update core reference docs that others depend on

| Item | File | Est. |
|------|------|------|
| A4 | `docs/hca/entities/mysql-schema.md` | 3h |
| C1 | `docs/WORKSPACE-INDEX.md` | 2h |
| C3 | `docs/KNOWLEDGE-POOL.md` | 2h |
| F1 | `README.md` | 1h |

### Batch 2: CLI & API Reference (Hours 9-20)
**Goal**: Complete user-facing command/endpoint documentation

| Item | File | Est. |
|------|------|------|
| A1 | `docs/hca/pages/cli-reference.md` | 4h |
| A2 | `docs/hca/pages/api-reference.md` | 6h |
| D1 | `pulldb/web/help/pages/cli/index.html` | 2h |

### Batch 3: Web UI Admin (Hours 21-32)
**Goal**: Document admin features

| Item | File | Est. |
|------|------|------|
| A3 | `docs/hca/pages/admin-guide.md` | 4h |
| D5 | `pulldb/web/help/pages/web-ui/admin.html` | 4h |
| B3 | New: `docs/hca/features/admin-tasks.md` | 2h |
| E1 | Capture admin screenshots | 2h |

### Batch 4: New Features (Hours 33-44)
**Goal**: Document completely new features

| Item | File | Est. |
|------|------|------|
| B1 | New: `docs/hca/features/feature-requests.md` | 2h |
| B2 | New: `docs/hca/features/database-lifecycle.md` | 3h |
| B4 | New: `docs/hca/widgets/lazy-table.md` | 2h |
| D3 | `pulldb/web/help/pages/web-ui/jobs.html` | 2h |
| D4 | `pulldb/web/help/pages/web-ui/restore.html` | 1h |
| E2-E4 | New screenshots | 4h |

### Batch 5: Help Center & Indexes (Hours 45-55)
**Goal**: Finalize help system and regenerate indexes

| Item | File | Est. |
|------|------|------|
| D2 | `pulldb/web/help/pages/api/index.html` | 4h |
| D6 | `pulldb/web/help/pages/concepts/job-lifecycle.html` | 1h |
| C2 | Regenerate `WORKSPACE-INDEX.json` | 1h |
| C4 | Regenerate `KNOWLEDGE-POOL.json` | 1h |
| C5 | Regenerate `search-index.json` | 1h |
| F2-F3 | Entry points | 2h |

---

*Plan generated: January 17, 2026*  
*Enhanced: January 17, 2026 with delta analysis, route inventory, template mapping*  
*Total work items: 35*
*Estimated total effort: 55 hours*  
*Recommended execution: 1 batch per session (8-12 hours)*
