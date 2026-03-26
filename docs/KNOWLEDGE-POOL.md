# pullDB Knowledge Pool (condensed facts)

[← Back to Documentation Index](START-HERE.md)

Purpose: a single-source, trimmed knowledge base used by agents and maintainers. This file contains only the facts required for current operations. It is intentionally concise and indexed for fast lookup.

**Related:** [Deployment](hca/widgets/deployment.md) · [policies/](hca/plugins/policies/) · [terraform/](hca/plugins/terraform/)

Last updated: 2026-03-26
Current version: v1.3.0
Phases complete: 0-6

---

## Package Contents Summary (v1.3.0)

| Component | Path in Package | Size |
|-----------|-----------------|------|
| Python wheel | `/opt/pulldb.service/dist/pulldb-1.3.0-py3-none-any.whl` | ~16MB |
| myloader binary | `/opt/pulldb.service/bin/myloader-0.21.1-1` | 7.7MB |
| Schema files | `/opt/pulldb.service/schema/pulldb_service/` | 28 SQL files |
| Systemd units | `/opt/pulldb.service/systemd/` | 6 files |
| Config templates | `/opt/pulldb.service/env.example`, `aws.config.example` | - |
| After-SQL templates | `/opt/pulldb.service/template_after_sql/` | 12 customer scripts |
| Install scripts | `/opt/pulldb.service/scripts/` | 7 scripts |

### Entry Points

| Command | Module | Purpose |
|---------|--------|---------|
| `pulldb` | `pulldb.cli.main:main` | User CLI (own jobs) |
| `pulldb-admin` | `pulldb.cli.admin:main` | Admin CLI (system ops) |
| `pulldb-api` | `pulldb.api.main:main` | REST API (port 8080) |
| `pulldb-web` | `pulldb.api.main:main_web` | Web UI (port 8000) |
| `pulldb-worker` | `pulldb.worker.service:main` | Background job processor |

### Default Accounts (Fresh Install)

| Account | UUID | Role | Password | Notes |
|---------|------|------|----------|-------|
| `admin` | `00000000-...0002` | admin | Random 16-char, bcrypt | Force reset on first login |
| `pulldb_service` | `00000000-...0001` | service | NULL | System account, locked |

---

## API Reference (v1.3.0)

Complete API documentation: [docs/api/README.md](api/README.md)

### REST API (port 8080) - 63 endpoints

| Category | Count | Key Endpoints |
|----------|-------|---------------|
| Health/Status | 2 | `/api/health`, `/api/status` |
| Auth | 4 | `/api/auth/register`, `/api/auth/change-password`, `/api/auth/request-host-key`, `/api/auth/user-exists/{username}` |
| Users | 2 | `/api/users/{username}`, `/api/users/{user_code}/last-job` |
| Hosts | 1 | `/api/hosts` |
| Jobs | 14 | `/api/jobs`, `/api/jobs/{id}`, `/api/jobs/paginated`, `/api/jobs/search`, `/api/jobs/history` |
| Job Actions | 4 | `/api/jobs/{id}/cancel`, `/api/jobs/{id}/extend`, `/api/jobs/{id}/lock`, `/api/jobs/{id}/unlock` |
| Manager | 2 | `/api/manager/team`, `/api/manager/team/distinct` |
| Admin Keys | 5 | `/api/admin/keys/pending`, `/api/admin/keys/approve`, `/api/admin/keys/revoke` |
| Admin Maintenance | 8 | `/api/admin/prune-logs`, `/api/admin/cleanup-staging`, `/api/admin/orphan-databases`, `/api/admin/delete-orphans`, `/api/admin/hosts/{id}/rotate-secret` |
| Dropdowns | 3 | `/api/dropdown/customers`, `/api/dropdown/users`, `/api/dropdown/hosts` |
| Backups | 2 | `/api/customers/search`, `/api/backups/search` |
| Features | 6 | `/api/feature-requests`, `/api/feature-requests/{id}`, `/api/feature-requests/{id}/vote` |
| Overlord | 7 | `/api/overlord/{job_id}`, `/api/overlord/{job_id}/claim`, `/api/overlord/{job_id}/sync`, `/api/overlord/{job_id}/release` |

### Web UI API (port 8000) - 166 routes

| Module | Prefix | Route Count | Key Routes |
|--------|--------|-------------|------------|
| auth | `/web` | 12 | `/login`, `/logout`, `/change-password`, `/auth/profile` |
| dashboard | `/web/dashboard` | 1 | `/` (role-specific) |
| jobs | `/web/jobs` | 21 | `/`, `/{job_id}`, `/{job_id}/cancel`, `/api/paginated` |
| restore | `/web/restore` | 4 | `/`, `/search-customers`, `/search-backups` |
| admin | `/web/admin` | 107 | `/users`, `/hosts`, `/settings`, `/api-keys`, `/job-history`, `/locked-databases`, `/overlord` |
| manager | `/web/manager` | 7 | `/`, `/my-team/{user_id}/*`, `/api/team` |
| audit | `/web/audit` | 3 | `/`, `/api/logs`, `/api/logs/distinct` |
| requests | `/web/requests` | 10 | `/`, `/api/list`, `/api/vote/{id}`, `/api/notes/{id}` |
| mockup | `/web/mockup` | 1 | `/job-details` (development only) |

**Full reference**: [REST-API.md](api/REST-API.md) | [WEB-API.md](api/WEB-API.md) | [API-DOCUMENTATION-STANDARD.md](api/API-DOCUMENTATION-STANDARD.md)

### API Package Files

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/api/__init__.py` | pages | Package exports |
| `pulldb/api/main.py` | pages | FastAPI application, API key validation |
| `pulldb/api/auth.py` | pages | Authentication middleware, `get_authenticated_user()` |
| `pulldb/api/schemas.py` | entities | Pydantic models: `JobRequest`, `JobResponse`, `JobSummary`, `JobHistoryItem` |
| `pulldb/api/routes/*.py` | pages | Individual route modules (jobs, hosts, auth, admin) |

### Domain Layer Files (v1.3.0)

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/domain/__init__.py` | entities | Package exports |
| `pulldb/domain/models.py` | entities | Core data models: `Job`, `User`, `Host`, `Backup` |
| `pulldb/domain/errors.py` | entities | Domain-specific exception classes |
| `pulldb/domain/config.py` | entities | Configuration dataclasses |
| `pulldb/domain/schemas.py` | entities | Preset schema definitions |
| `pulldb/domain/interfaces.py` | entities | Abstract repository interfaces |
| `pulldb/domain/permissions.py` | entities | RBAC permission checks |
| `pulldb/domain/validation.py` | entities | Input validation utilities |
| `pulldb/domain/settings.py` | entities | System settings definitions |
| `pulldb/domain/naming.py` | entities | Database naming conventions |
| `pulldb/domain/color_schemas.py` | entities | Color schema definitions for UI theming |
| `pulldb/domain/restore_models.py` | entities | Restore-specific data models |
| `pulldb/domain/feature_request.py` | entities | Feature request data model |
| `pulldb/domain/overlord.py` | entities | Overlord domain models |
| `pulldb/domain/services/__init__.py` | features | Service package |
| `pulldb/domain/services/provisioning.py` | features | Host provisioning service |
| `pulldb/domain/services/secret_rotation.py` | features | Secret rotation service |
| `pulldb/domain/services/discovery.py` | features | Service discovery |
| `pulldb/domain/services/enqueue.py` | features | Job enqueue service |
| `pulldb/domain/services/overlord_provisioning.py` | features | Overlord company provisioning |

---

## Index (categories)
- **Architecture Diagrams** - [docs/diagrams/pulldb-flowchart.md](diagrams/pulldb-flowchart.md) (Mermaid)
- **API Reference** (v1.3.0)
- **Package Contents Summary** (Updated - v0.3.0)
- **Default Accounts & Provisioning** (v0.2.0)
- **CLI HMAC Authentication** (Phase 6) - includes multi-host API key management
- **Security Rules & Patterns** (v1.3.0) - SQL injection prevention, cross-DB safety, ownership verification
- **Host Provisioning Service** (Phase 6)
- **Secret Rotation** (Phase 6)
- **Database Retention** (Phase 6)
- **Stale Running Job Recovery** (Phase 6)
- **Web UI Help System** (Phase 6)
- **Authentication & Sessions** (Phase 4)
- **RBAC Permission Matrix** (Phase 4)
- **Simulation Framework** (Phase 4)
- CLI Architecture & Scope
- Web UI Layout Architecture
- Web UI Style Guide
- Web UI HCA Architecture
- S3 Multi-Location Configuration (v0.0.7)
- **Schema Structure (Consolidated)**
- Accounts & ARNs
- S3 buckets & paths
- IAM roles & policies
- Secrets Manager (secrets + policies)
- EC2 / instance profile
- Restore workflow facts
- System Paths & Service Locations
- Lessons Learned & Troubleshooting
  - **Packaging & Installation Lessons (Jan 2026)**
  - Phase 2 Lessons (Nov 2025)
  - **Myloader Thread Architecture & Progress Tracking (Jan 2026)**
- Quick commands & verification
- Purge candidates (files/docs to archive)
- Machine-readable index (JSON)
- IAM policy snippets (examples)
- Terraform examples (optional, small snippets)

---

## Authentication & Sessions (Phase 4)

pullDB implements a dual-mode authentication system supporting both development (trusted headers) and production (session-based) flows.

### Auth Modes

| Mode | Environment | How It Works |
|------|-------------|--------------|
| `trusted` | Development | `X-Pulldb-User` header trusted directly |
| `session` | Production | bcrypt password + session token cookie |
| `both` | Transition | Tries trusted header first, falls back to session |

**Configuration**: `PULLDB_AUTH_MODE` environment variable (default: `both`)

### Password Hashing

- **Algorithm**: bcrypt with work factor 12
- **Functions**: `hash_password()`, `verify_password()` in `pulldb/auth/password.py`
- **Storage**: `auth_credentials` table (user_id → hashed password)

### Session Management

- **Token**: 32-byte random hex string
- **Cookie**: `pulldb_session` (HttpOnly, Secure in prod, SameSite=Lax)
- **TTL**: 24 hours (configurable via `PULLDB_SESSION_TTL_HOURS`)
- **Storage**: `sessions` table with expiry timestamp

### Key Components

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/auth/password.py` | shared | bcrypt hash/verify utilities |
| `pulldb/auth/repository.py` | shared | AuthRepository for credential storage |
| `pulldb/api/auth.py` | pages | FastAPI auth middleware |
| `pulldb/web/features/auth/` | features | Login/logout routes |

### Quick Reference

```python
# Verify password
from pulldb.auth.password import verify_password
is_valid = verify_password(plain_text, hashed)

# Get current user (in route)
from pulldb.api.auth import get_authenticated_user
user = await get_authenticated_user(request, auth_repo)
```

---

## RBAC Permission Matrix (Phase 4)

Role-Based Access Control with four roles: `USER`, `MANAGER`, `ADMIN`, `SERVICE` (system account).

### Permission Matrix

| Action | USER | MANAGER | ADMIN |
|--------|------|---------|-------|
| View own jobs | ✅ | ✅ | ✅ |
| Submit own jobs | ✅ | ✅ | ✅ |
| Cancel own jobs | ✅ | ✅ | ✅ |
| Delete own job databases | ✅ | ✅ | ✅ |
| View managed users' jobs | ❌ | ✅ | ✅ |
| Cancel managed users' jobs | ❌ | ✅ | ✅ |
| Delete managed users' jobs | ❌ | ✅ | ✅ |
| View all jobs | ❌ | ❌ | ✅ |
| Cancel any job | ❌ | ❌ | ✅ |
| Delete any job | ❌ | ❌ | ✅ |
| Manage users | ❌ | ❌ | ✅ |
| Orphan cleanup | ❌ | ❌ | ✅ |
| System settings | ❌ | ❌ | ✅ |

### Manager Relationships

- Stored as `manager_id` column in `auth_users` table (FK to self)
- One manager can manage multiple users
- Each user has at most one manager
- Query: `SELECT user_id FROM auth_users WHERE manager_id = ?`

### Key Components

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/domain/permissions.py` | entities | `can_cancel_job()`, `can_delete_job_database()`, `can_view_job()`, `UserRole` enum |
| `pulldb/domain/models.py` | entities | `User.role`, `User.manager_id` fields |
| `pulldb/infra/mysql_users.py` | shared | `UserRepository` (via facade `mysql.py`) |

### Usage Pattern

```python
from pulldb.domain.permissions import can_cancel_job, can_delete_job_database

# Check if user can cancel a job (needs job owner's manager_id for manager permission check)
if not can_cancel_job(current_user, job.owner_user_id, job_owner_manager_id):
    raise PermissionError("Cannot cancel this job")

# Check if user can delete a job's databases
if not can_delete_job_database(current_user, job.owner_user_id, job_owner_manager_id):
    raise PermissionError("Cannot delete this job's databases")
```

---

## Security Rules & Patterns (v1.3.0)

Generalized security rules derived from audit findings. These rules apply to ALL pullDB code.

### Rule 1: SQL Column Name Validation

**Problem:** Dynamic SQL built from dictionary keys can allow SQL injection even when values are parameterized.

**Rule:** ALWAYS validate column names against an allowlist before building SQL.

```python
# ❌ DANGEROUS - column names from dict keys
columns = list(data.keys())
column_names = ", ".join([f"`{c}`" for c in columns])
cursor.execute(f"INSERT INTO {table} ({column_names}) VALUES ...")

# ✅ SAFE - validate against allowlist first
ALLOWED_COLUMNS = {"database", "dbHost", "dbHostRead", "company", "subdomain"}

def _validate_columns(columns: list[str], allowed: set[str]) -> None:
    invalid = set(columns) - allowed
    if invalid:
        raise ValueError(f"Invalid column names: {invalid}")

_validate_columns(data.keys(), ALLOWED_COLUMNS)
# Now safe to build SQL
```

**Applies to:** Any code that builds SQL from user-provided or dict-derived column names.

### Rule 2: Table Name Validation

**Problem:** Table names passed as parameters can be exploited in SQL injection.

**Rule:** ALWAYS validate table names against an allowlist.

```python
# ❌ DANGEROUS - table name from parameter
def __init__(self, table: str = "companies"):
    self._table = table  # Used in f"SELECT * FROM {self._table}"

# ✅ SAFE - validate against allowlist
VALID_TABLES = {"companies"}

def __init__(self, table: str = "companies"):
    if table not in VALID_TABLES:
        raise ValueError(f"Invalid table: {table}")
    self._table = table
```

### Rule 3: Cross-Database Operation Safety

**Problem:** Operations spanning multiple databases (e.g., coordination DB + external DB) cannot be atomic. Partial failures leave inconsistent state.

**Rule:** Use a state machine with compensation on failure.

```python
# ❌ DANGEROUS - non-atomic cross-database update
def sync(self):
    external_db.update(data)      # Step 1: External update
    tracking_db.mark_synced()     # Step 2: Local update (what if this fails?)

# ✅ SAFE - state machine with compensation
def sync(self):
    tracking_db.mark_syncing()    # Record intent
    try:
        external_db.update(data)
        tracking_db.mark_synced()
    except Exception:
        tracking_db.mark_sync_failed()  # Compensation
        raise
```

### Rule 4: External Database Boundaries

**Problem:** pullDB manages external databases it doesn't own. Accidental modification of unowned data is catastrophic.

**Rule:** NEVER modify external data without verifying ownership first.

```python
# Ownership verification MUST happen before ANY external modification:
# 1. Job exists
# 2. Job target matches the database being modified  
# 3. Job status is "deployed" (still active)
# 4. Tracking record shows we claimed this database

def verify_ownership(database_name: str, job_id: str) -> bool:
    job = job_repo.get_job_by_id(job_id)
    if not job:
        raise OwnershipError("Job not found")
    if job.target != database_name:
        raise OwnershipError(f"Job target mismatch")
    if job.status.value != "deployed":
        raise OwnershipError(f"Job not deployed")
    return True
```

### Rule 5: API Job Status Verification

**Problem:** API endpoints that operate on jobs may not verify the job is still in a valid state.

**Rule:** ALWAYS verify job status before performing operations that depend on job state.

```python
# ❌ INCOMPLETE - only checks job exists
job = job_repo.get_job_by_id(job_id)
if not job:
    raise HTTPException(404, "Job not found")
# Proceeds with operation on potentially deleted/archived job

# ✅ COMPLETE - verifies job is in valid state
job = job_repo.get_job_by_id(job_id)
if not job:
    raise HTTPException(404, "Job not found")
if job.status.value not in ("deployed", "expiring"):
    raise HTTPException(400, f"Job is {job.status.value}, not deployed")
```

### Rule 6: Error Type Differentiation

**Problem:** Generic error messages prevent users from self-diagnosing issues.

**Rule:** Return specific error types and messages for different failure modes.

```python
# ❌ POOR - generic error for all failures
except Exception as e:
    return {"error": "Failed to load data"}

# ✅ GOOD - specific errors for specific cases
except ConnectionError as e:
    raise HTTPException(503, "Database connection failed. Try again later.")
except PermissionError as e:
    raise HTTPException(403, "Access denied to external database.")
except RecordNotFoundError:
    return {"status": "not_found", "can_create": True}  # Not an error!
```

### Rule 7: Orphan Record Cleanup

**Problem:** When parent records are deleted, child/tracking records can become orphaned.

**Rule:** Implement cleanup hooks or periodic cleanup jobs.

```python
# When deleting a job, also clean up associated records:
def delete_job(job_id: str):
    # 1. Release any overlord claims
    overlord_manager.release(job.target, job_id, ReleaseAction.RESTORE)
    
    # 2. Clean up tracking records
    tracking_repo.delete_for_job(job_id)
    
    # 3. Delete job
    job_repo.delete(job_id)
```

### Quick Reference Table

| Rule | Applies When | Key Check |
|------|--------------|-----------|
| Column validation | Building INSERT/UPDATE SQL | `columns ⊆ ALLOWED_COLUMNS` |
| Table validation | Parameterized table name | `table ∈ VALID_TABLES` |
| Cross-DB safety | Multi-database operation | Use state machine + compensation |
| Ownership check | External DB modification | Verify job owns the resource |
| Job status check | API operations on jobs | `status in valid_states` |
| Error differentiation | All API error handling | Specific types, actionable messages |
| Orphan cleanup | Parent record deletion | Clean up child records |

---

## Job Delete Feature (Phase 5)

User-initiated deletion of completed job databases with full audit trail.

### Job Status Lifecycle

```
                    ┌──────────────────────────────────────────┐
                    │                                          │
QUEUED → RUNNING → DEPLOYED → EXPIRED → DELETED               │
           │           │                                       │
           ├→ FAILED   ├→ SUPERSEDED (replaced by new restore)│
           │           │                                       │
           └→ CANCELING → CANCELED ────────────────────────────┘
                                                               │
DEPLOYED → DELETING → DELETED (user-initiated) ───────────────┘
```

| Status | Terminal? | Active? | Deletable? | Notes |
|--------|-----------|---------|------------|-------|
| `queued` | ❌ | ✅ | ❌ | Waiting for worker |
| `running` | ❌ | ✅ | ❌ | Worker processing |
| `canceling` | ❌ | ✅ | ❌ | Cancel requested, stopping at checkpoint |
| `deployed` | ❌ | ✅ | ✅ | Database live, user working |
| `expired` | ✅ | ❌ | ✅ | Retention passed, awaiting cleanup |
| `failed` | ✅ | ❌ | ✅ | Execution failed |
| `complete` | ✅ | ❌ | ✅ | User marked complete |
| `canceled` | ✅ | ❌ | ✅ | Canceled by user |
| `superseded` | ✅ | ❌ | ✅ | Replaced by newer restore |
| `deleting` | ❌ | ❌ | ❌ | Bulk delete in progress |
| `deleted` | ✅ | ❌ | ❌ | Already deleted |

### Delete Modes

| Mode | Behavior | Audit Trail |
|------|----------|-------------|
| **Soft Delete** (default) | Drop databases, set status=`deleted` | Job record preserved |
| **Hard Delete** | Drop databases, remove job record | Audit log preserved |

### What Gets Deleted

Both database types are dropped regardless of job status:
- **Staging database**: `{target}_{job_id_first_12_chars}` (temporary)
- **Target database**: `{user_code}{target}` (user's named database)

### Target Database Protection (v0.2.0+)

Target databases are protected from accidental deletion:

| Protection | Function | Description |
|------------|----------|-------------|
| Protected DBs | `PROTECTED_DATABASES` | mysql, sys, information_schema, etc. |
| Active Deployment | `has_any_deployed_job_for_target()` | Any user has deployed job |
| Locked Database | `has_any_locked_job_for_target()` | Any user has locked the target |

**Single source of truth**: `is_target_database_protected()` in `pulldb/worker/cleanup.py`

```python
# Check before any target deletion
protection = is_target_database_protected(target, dbhost, job_repo)
if not protection.can_drop:
    # protection.reason explains why (deployed, locked, protected)
    # protection.blocking_job_id shows which job blocks deletion
```

### Key Components

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/domain/permissions.py` | entities | `can_delete_job_database()` |
| `pulldb/worker/cleanup.py` | features | `delete_job_databases()`, `is_target_database_protected()`, `JobDeleteResult`, `TargetProtectionResult` |
| `pulldb/infra/mysql_jobs.py` | shared | `JobRepository.mark_job_deleted()`, `hard_delete_job()`, `has_any_deployed_job_for_target()`, `has_any_locked_job_for_target()` |
| `pulldb/worker/admin_tasks.py` | features | `_execute_bulk_delete_jobs()` handler |
| `pulldb/web/features/jobs/routes.py` | pages | Delete routes (single + bulk) |

### API Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/web/jobs/api/{job_id}/resubmit` | POST | Resubmit failed job (preflight or execute) |
| `/web/jobs/{job_id}/delete-database` | POST | Single job delete |
| `/web/jobs/bulk-delete` | POST | Create bulk delete task |
| `/web/jobs/bulk-delete/{task_id}/status` | GET | Poll bulk delete progress |

### Audit Actions

| Action | Event |
|--------|-------|
| `delete_job_database` | Single job delete (soft or hard) |
| `bulk_delete_jobs_requested` | Bulk delete task created |
| `bulk_delete_started` | Bulk delete task began processing |
| `bulk_delete_progress` | Individual job in bulk delete processed |
| `bulk_delete_completed` | Bulk delete task finished |

### UI Components

- **Single Delete**: Trash icon button in history table row → "Are you sure?" modal
- **Bulk Delete**: Checkbox selection → "Delete Selected" → type "I am sure." modal
- **Progress**: Modal with progress bar, 2-second polling

### Schema Support

Job delete support is now integrated into the consolidated schema:

```sql
-- Included in schema/pulldb_service/00_tables/020_jobs.sql
-- Job status enum includes: 'canceling', 'deleting', 'deleted', 'superseded'
-- Index: idx_jobs_deletable ON jobs(status, owner_user_id)

-- Included in schema/pulldb_service/00_tables/040_admin_tasks.sql
-- Task type enum includes: 'bulk_delete_jobs', 'retention_cleanup'
```

---

## Resubmit Failed Jobs (v1.3.0+)

Allows users to resubmit failed jobs using the same backup and settings. Available in the History view.

### Permission Model

| Role | Own Jobs | Managed User's Jobs | Other User's Jobs |
|------|----------|---------------------|-------------------|
| User | ✅ | ❌ | ❌ |
| Manager | ✅ | ✅ | ❌ |
| Admin | ✅ | ✅ | ✅ |

**Key behavior**: Managers/Admins resubmit jobs *as the original owner*, preserving ownership.

### Validation Rules

| Condition | Result |
|-----------|--------|
| Job status ≠ `failed` | ❌ Blocked |
| Missing `backup_path` in options | ❌ Blocked |
| Original owner deleted | ❌ Blocked |
| Active job for same target+host | ❌ Blocked (wait or cancel) |
| Deployed job by different owner | ❌ Blocked (admin can override) |
| Deployed job by same owner | ⚠️ Warning (will overwrite) |
| Host is disabled | ⚠️ Warning (will queue but not run) |

### Key Components

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/web/features/jobs/routes.py` | pages | `api_resubmit_job()`, `_validate_resubmit()` |
| `pulldb/infra/mysql_jobs.py` | shared | `JobRepository.get_in_progress_job_for_target()`, `update_job_options()` |
| `pulldb/web/templates/features/jobs/jobs.html` | pages | Resubmit button + modal in History view |

### API Endpoint

| Route | Method | Purpose |
|-------|--------|---------|
| `/web/jobs/api/{job_id}/resubmit` | POST | Resubmit failed job |

**Request body:**
- `{ "preflight": true }` — Validate only, return warnings
- `{ "confirm": true }` — Execute resubmit after reviewing warnings

**Response (preflight):**
```json
{
  "can_resubmit": true,
  "warnings": ["Target has deployed database that will be overwritten"],
  "job_info": { "original_job_id": 123, "owner_username": "bob", "target": "acme_staging" }
}
```

**Response (execute):**
```json
{
  "success": true,
  "new_job_id": 456,
  "target": "acme_staging",
  "message": "Job resubmitted successfully as bob"
}
```

### Audit Trail

New jobs created via resubmit include `resubmit_of_job_id` in their `options_json`:

```json
{
  "backup_path": "s3://...",
  "resubmit_of_job_id": 123
}
```

---

## CLI HMAC Authentication (Phase 6)

Secure API key authentication for CLI operations using HMAC-SHA256 signatures.

### Key Files

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/cli/auth.py` | pages | HMAC signature generation, credential storage |
| `pulldb/api/main.py` | pages | API key validation endpoints |
| `schema/pulldb_service/00_tables/004_api_keys.sql` | schema | API key storage |

### Credential Flow

```
~/.pulldb/credentials  →  load_credentials()  →  get_api_headers()  →  HMAC signed request
                                                    ↓
                                        X-Api-Key-Id, X-Timestamp, X-Signature
```

### Configuration

- **Credential file**: `~/.pulldb/credentials`
- **Format**: INI with `api_key` and `api_secret`
- **Env override**: `PULLDB_API_KEY`, `PULLDB_API_SECRET`

---

## Host Provisioning Service (Phase 6)

Unified service for CLI and Web-based host setup orchestration.

### Key Files

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/domain/services/provisioning.py` | features | HostProvisioningService orchestration |
| `pulldb/infra/mysql_provisioning.py` | shared | Low-level MySQL provisioning |

### Provisioning Steps

1. Test admin connection to target MySQL
2. Create `pulldb_loader` user with privileges (includes CREATE ROUTINE, ALTER ROUTINE, EXECUTE, PROCESS)
3. Create `pulldb_service` database
4. Deploy `pulldb_atomic_rename` stored procedure (v1.0.0, auto-versioned via `procedure_deployments` table)
5. Store credentials in AWS Secrets Manager
6. Register host in coordination database

**Aurora MySQL Note**: Procedure version tracking uses `procedure_deployments` table because Aurora strips comments from procedure bodies. See [aurora-mysql-compatibility.md](hca/features/aurora-mysql-compatibility.md).

### Result Handling

All operations return `ProvisioningResult` with:
- `success`: Boolean status
- `message`: Human-readable result
- `error`: Detailed error if failed
- `suggestions`: Actionable fix recommendations

---

## Secret Rotation (Phase 6)

Atomic credential rotation with verification and rollback.

### Key File

`pulldb/domain/services/secret_rotation.py` - `RotationResult` dataclass, `rotate_host_secret()` function

### Rotation Workflow

```
VALIDATION → GENERATION → MYSQL UPDATE → VERIFICATION → AWS UPDATE → FINAL VERIFY
```

### Failure Handling

- **Pre-AWS failure**: Automatic rollback to old password
- **Post-AWS failure**: Manual fix instructions provided
- **All phases**: Timed and logged for diagnostics

---

## Database Retention (Phase 6)

Lifecycle management for restored databases.

### Key File

`pulldb/worker/retention.py` - `RetentionService`

### Features

- **Expiration**: Auto-expire based on grace days
- **Locking**: User-requested lock to prevent deletion
- **Extension**: Extend retention by 1, 3, 6 months
- **Maintenance modal**: Acknowledges about-to-expire databases

### Schema Integration

Retention is integrated into existing tables (not separate tables):
- **`jobs` table**: `locked_at`, `expires_at`, `locked_by`, `db_dropped_at` columns (in 020_jobs.sql)
- **`admin_tasks` table**: `retention_cleanup` task type (in 040_admin_tasks.sql)
- **`settings` table**: Retention-related settings include `staging_retention_days`, `default_retention_days`, `max_retention_days`, `expiring_warning_days`, `cleanup_grace_days` (23 total settings defined in `pulldb/domain/settings.py`)

---

## Stale Running Job Recovery (Phase 6)

Recovery mechanism for jobs stuck in 'running' status when workers die mid-restore.

### Key Files

- `pulldb/worker/cleanup.py` - `execute_stale_running_cleanup()`, `StaleRunningCleanupResult`
- `tests/qa/worker/test_stale_running_recovery.py` - Comprehensive test suite

### Algorithm

1. **Detection**: Find jobs in 'running' status older than timeout (15 min default)
2. **Verification**: Check MySQL `SHOW PROCESSLIST` for activity on staging database
3. **Multiple checks**: 3 checks with 2s delay to avoid false positives
4. **Cleanup**: Drop staging database if no activity detected
5. **Marking**: Atomically mark job as 'failed' with recovery message

### Safety Guards

- Skip jobs with newer submission to same target (superseded)
- Verify no active MySQL processes before cleanup
- Return error on check failure (don't mark failed if uncertain)

---

## Web UI Help System (Phase 6)

Self-contained HTML documentation system served at `/web/help/`.

### Structure

```
pulldb/web/help/
├── index.html                    # Help Center landing
├── css/help.css                  # Glassmorphism styling (1,923 lines)
├── js/
│   ├── help.js                   # Alpine.js app: theme, search, accordion (320 lines)
│   ├── search.js                 # Fuzzy search engine with relevance scoring (217 lines)
│   └── terminal.js               # Animated terminal demos with typing effects (227 lines)
├── search-index.json             # Full-text search index (14 pages)
└── pages/
    ├── getting-started.html
    ├── api/index.html            # API Reference
    ├── cli/index.html            # CLI Reference
    ├── concepts/job-lifecycle.html
    ├── troubleshooting/index.html
    └── web-ui/                   # Web UI documentation
        ├── index.html            # Overview
        ├── dashboard.html        # Dashboard guide
        ├── restore.html          # Restore wizard
        ├── jobs.html             # Jobs management
        ├── profile.html          # Profile & API keys
        ├── admin.html            # Admin panel
        ├── manager.html          # Manager features
        └── requests.html         # Feature requests
```

### Features

- **14 help pages** with consistent navigation
- **Dark/light theme** toggle (respects OS preference)
- **Search** (/) with keyboard shortcuts and fuzzy matching
- **Role-based content** (Admin, Manager, User sections)
- **Animated terminal demos** on index and getting-started pages
- **256 screenshots** (66 light + 66 dark raw, 62 + 62 annotated) across 8 categories
- **Screenshot annotations** defined in `docs/help-screenshot-annotations.yaml` (62 entries)

### Index Document

`docs/HELP-PAGE-INDEX.md` - Page inventory, endpoint catalog, screenshot inventory, visual audit log

---

## Simulation Framework (Phase 4)

In-memory mock system for testing without external dependencies.

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│              pulldb/simulation/                          │
├──────────────────────────────────────────────────────────┤
│ api/__init__.py   │ Exports router (HCA: pages)          │
│ api/router.py     │ FastAPI routes for scenario control  │
├───────────────────┼──────────────────────────────────────┤
│ core/engine.py    │ SimulationEngine orchestration       │
│ core/bus.py       │ EventBus for component communication │
│ core/state.py     │ Global state management              │
│ core/queue_runner │ MockQueueRunner job processing       │
│ core/seeding.py   │ Test data generation                 │
│ core/scenarios.py │ Chaos testing scenarios              │
├───────────────────┼──────────────────────────────────────┤
│ adapters/         │ Mock implementations                 │
│   mock_mysql.py   │ In-memory Job/User/Host repos        │
│   mock_s3.py      │ Mock S3 client                       │
│   mock_exec.py    │ Mock command executor                │
└───────────────────┴──────────────────────────────────────┘
```

### Mock Adapters

| Adapter | Replaces | Key Class |
|---------|----------|-----------|
| `mock_mysql.py` | `pulldb/infra/mysql.py` (facade) | `SimulatedJobRepository`, `SimulatedUserRepository` |
| `mock_s3.py` | `pulldb/infra/s3.py` | `MockS3Client` |
| `mock_exec.py` | `pulldb/infra/exec.py` | `MockProcessExecutor` |

### Usage

```python
# Import through package root (HCA compliant)
from pulldb.simulation import (
    SimulatedJobRepository,
    SimulatedUserRepository,
    ScenarioManager,
    get_scenario_manager,
    get_simulation_state,
)

# Set up simulation
state = get_simulation_state()
scenario_mgr = get_scenario_manager()
job_repo = SimulatedJobRepository()
```

### Chaos Scenarios

Available via `core/scenarios.py` (ScenarioType enum):

**Happy Path:**
- `HAPPY_PATH` - Default success scenario
- `SINGLE_JOB_SUCCESS` - Single job completes successfully
- `MULTIPLE_JOBS_SUCCESS` - Multiple jobs complete

**Failure Scenarios:**
- `S3_NOT_FOUND` - S3 object not found
- `S3_PERMISSION_DENIED` - S3 access denied
- `MYLOADER_FAILURE` - myloader execution fails
- `MYLOADER_TIMEOUT` - myloader times out
- `POST_SQL_FAILURE` - Post-SQL script fails

**Chaos Scenarios:**
- `RANDOM_FAILURES` - Random operation failures
- `SLOW_OPERATIONS` - Delayed operations
- `INTERMITTENT_FAILURES` - Sporadic failures

---

## Documentation Audit Agent

Continuous documentation auditing to keep KNOWLEDGE-POOL synchronized with codebase reality.

### Package Location

`pulldb/audit/` - HCA Layer: features

### Key Files

| File | Purpose |
|------|---------|
| `agent.py` | `DocumentationAuditAgent` - main orchestrator |
| `drift.py` | `DriftDetector`, `DriftAlert`, `DriftType` - comprehensive drift detection |
| `inventory.py` | `FileInventory` - scans entire codebase |
| `analyzers.py` | Code analyzers (Python, CSS, JS, SQL) |
| `mappings.py` | `DocCodeMapping` - hardcoded doc-to-code relationships |
| `knowledge_pool.py` | `KnowledgePoolParser`, `KnowledgePoolUpdater` |
| `report.py` | `AuditReport`, `AuditFinding`, `FindingSeverity` |

### Two Modes

1. **Targeted Audit** - Uses 17 hardcoded mappings for precise verification
   ```bash
   python -m pulldb.audit --full
   ```

2. **Comprehensive Drift Detection** - Scans entire codebase
   ```bash
   python -m pulldb.audit --drift --severity high
   python -m pulldb.audit --drift --copilot  # AI-friendly context
   ```

### Drift Types Detected

| Type | Description |
|------|-------------|
| `undocumented_file` | New file not in KNOWLEDGE-POOL |
| `missing_export` | Documented export not in `__all__` |
| `extra_export` | Export exists but not documented |
| `renamed_symbol` | Class/function was renamed |
| `value_mismatch` | CSS/JS timing values changed |

### Documentation

Full documentation: `docs/AUDIT-AGENT.md`

---

## Web UI HCA Architecture (Phase 4)

The web package follows HCA internally for UI component organization.

### Layer Mapping

| HCA Layer | Web Directory | Contents |
|-----------|---------------|----------|
| **shared** | `web/shared/` | `layouts/`, `ui/`, `contracts/`, `utils/`, `css/` |
| **entities** | `web/entities/` | `css/` (domain entities - mostly empty, types in features) |
| **features** | `web/features/` | `admin/`, `audit/`, `auth/`, `css/`, `dashboard/`, `jobs/`, `manager/`, `mockup/`, `requests/`, `restore/` |
| **widgets** | `web/widgets/` | `sidebar/`, `filter_bar/`, `lazy_table/`, `virtual_table/`, `breadcrumbs/`, `bulk_actions/`, `searchable_dropdown/` |
| **pages** | `web/pages/` | Empty - pages co-located within features (`features/<name>/pages/`) |

### Feature Packages (v1.3.0)

| Package | Files | Routes | Purpose |
|---------|-------|--------|---------|
| `auth/` | 2 | 12 | Login, logout, password change, profile |
| `dashboard/` | 2 | 1 | Role-specific landing page |
| `jobs/` | 2 | 16 | Job list, details, cancel, events |
| `restore/` | 2 | 4 | New restore submission wizard |
| `admin/` | 3 | 88 | Users, hosts, settings, API keys |
| `manager/` | 2 | 7 | Team management |
| `audit/` | 2 | 3 | Audit log viewer |
| `requests/` | 2 | 10 | Feature request board |
| `mockup/` | 2 | 1 | Development mockup pages |

### Widget Packages (v1.3.0)

| Package | Files | Purpose |
|---------|-------|---------|
| `sidebar/` | 2 | Collapsible navigation sidebar |
| `virtual_table/` | 2 | Virtualized table with infinite scroll |
| `virtual_log/` | 1 | Virtualized log viewer |
| `lazy_table/` | 1 | Lazy-loading table |
| `filter_bar/` | 1 | Search/filter controls |
| `bulk_actions/` | 1 | Bulk selection controls |
| `searchable_dropdown/` | 1 | Autocomplete dropdown |

### Shared Packages

| Package | Files | Purpose |
|---------|-------|---------|
| `layouts/` | 4 | base.html, app_layout.html, _skeleton.html |
| `contracts/` | 3 | service_contracts.py, page_contracts.py |
| `ui/` | 1 | Reusable UI components |
| `utils/` | 1 | Utility functions |

### Key Files

| File | Purpose |
|------|---------|
| `dependencies.py` | FastAPI dependency injection (templates, auth) |
| `router_registry.py` | Combines all feature routers |
| `exceptions.py` | Custom web exception types |

### Template Hierarchy

```
templates/
├── base.html           # Root layout (shared)
├── base_auth.html      # Auth pages layout
├── features/           # Feature-specific templates
├── widgets/            # Widget templates
├── partials/           # Shared partials (breadcrumbs, icons)
└── mockup/             # Design mockups
```

### Web UI CSS Files (HCA-organized)

Source CSS (compiled to static/css/):

| Source File | Layer | Purpose |
|-------------|-------|---------|
| `pulldb/web/shared/css/design-tokens.css` | shared | CSS custom properties (colors, spacing, etc.) |
| `pulldb/web/shared/css/fonts.css` | shared | Font definitions and loading |
| `pulldb/web/entities/css/avatar.css` | entities | Avatar styling |
| `pulldb/web/features/css/alerts.css` | features | Alert/notification component styles |
| `pulldb/web/features/css/buttons.css` | features | Button component styles |
| `pulldb/web/features/css/modals.css` | features | Modal dialog styles |
| `pulldb/web/widgets/css/stats-bar.css` | widgets | Stats bar widget styles |
| `pulldb/web/pages/css/admin-hosts.css` | pages | Admin hosts page styles |
| `pulldb/web/pages/css/styleguide.css` | pages | Style guide page styles |

Compiled static CSS:

| Static File | Source |
|-------------|--------|
| `pulldb/web/static/css/shared/design-tokens.css` | shared layer tokens |
| `pulldb/web/static/css/shared/fonts.css` | shared fonts |
| `pulldb/web/static/css/entities/avatar.css` | entity avatar |
| `pulldb/web/static/css/features/alerts.css` | feature alerts |
| `pulldb/web/static/css/features/buttons.css` | feature buttons |
| `pulldb/web/static/css/features/modals.css` | feature modals |
| `pulldb/web/static/css/widgets/stats-bar.css` | widget stats bar |
| `pulldb/web/static/css/pages/admin-hosts.css` | page admin hosts |
| `pulldb/web/static/css/pages/styleguide.css` | page styleguide |
| `pulldb/web/static/css/generated/manifest-dark.css` | Generated dark theme manifest |
| `pulldb/web/static/css/generated/manifest-light.css` | Generated light theme manifest |

### Web UI JavaScript Files

| File | Purpose |
|------|---------|
| `pulldb/web/static/js/theme-toggle.js` | Dark/light theme switcher |
| `pulldb/web/static/js/local-datetime.js` | UTC to local datetime conversion |
| `pulldb/web/static/js/pages/admin-hosts.js` | Admin hosts page interactivity |
| `pulldb/web/static/js/pages/admin-settings.js` | Admin settings page logic |
| `pulldb/web/static/js/pages/admin-overlord-companies.js` | Overlord companies management |
| `pulldb/web/static/js/pages/admin-overlord-company-detail.js` | Overlord company detail page |
| `pulldb/web/static/js/pages/manager-dashboard.js` | Manager dashboard interactivity |
| `pulldb/web/static/js/vendor/htmx.min.js` | HTMX library (vendored) |

### Web UI Template Files (v1.3.0)

Admin templates:

| Template | Purpose |
|----------|---------|
| `templates/features/admin/admin_task_status.html` | Background task status |
| `templates/features/admin/cleanup_preview.html` | Cleanup operation preview |
| `templates/features/admin/host_detail.html` | Host detail view |
| `templates/features/admin/locked_databases.html` | Locked databases management |
| `templates/features/admin/orphan_preview.html` | Orphan record preview |
| `templates/features/admin/prune_preview.html` | Prune operation preview |
| `templates/features/admin/styleguide.html` | Visual style guide page |
| `templates/features/admin/overlord_companies.html` | Overlord companies list |
| `templates/features/admin/overlord_company_detail.html` | Overlord company detail |
| `templates/features/admin/partials/_appearance.html` | Appearance settings partial |
| `templates/features/admin/partials/_overlord_setup.html` | Overlord setup partial |

Auth & dashboard templates:

| Template | Purpose |
|----------|---------|
| `templates/features/auth/change_password.html` | Password change form |
| `templates/features/dashboard/_admin_dashboard.html` | Admin role dashboard |
| `templates/features/dashboard/_manager_dashboard.html` | Manager role dashboard |
| `templates/features/dashboard/_user_dashboard.html` | User role dashboard |

Restore & widget templates:

| Template | Purpose |
|----------|---------|
| `templates/features/restore/partials/backup_results.html` | Backup search results |
| `templates/features/restore/partials/customer_results.html` | Customer search results |
| `templates/partials/job_header.html` | Job detail header partial |
| `templates/partials/job_progress_bars.html` | Job progress bar partial |
| `templates/partials/overlord_modal.html` | Overlord action modal |
| `templates/widgets/stats_bar.html` | Stats bar widget template |
| `templates/mockup/job-details-mockup.html` | Job details mockup page |

### Web Feature Python Files

| File | Purpose |
|------|---------|
| `pulldb/web/features/admin/theme_generator.py` | CSS theme manifest generator |

---

## Schema Structure (Consolidated)

The schema uses a consolidated structure under `schema/pulldb_service/`. Legacy migration files (007xx series) have been merged into base table definitions.

### Directory Layout

```
schema/
├── migrations/              # Schema migration scripts (3 files)
│   ├── 009_overlord_tracking.sql        # Overlord tracking tables
│   ├── 010_overlord_tracking_subdomain.sql  # Subdomain tracking
│   └── 011_fix_settings_keys.sql        # Settings key fixes
└── pulldb_service/
    ├── 00_tables/           # Core table definitions (18 files)
    │   ├── 001_auth_users.sql       # Users + role + manager_id
    │   ├── 002_auth_credentials.sql # Passwords + TOTP + reset
    │   ├── 003_sessions.sql         # Session tokens
    │   ├── 004_api_keys.sql         # CLI API keys
    │   ├── 010_db_hosts.sql         # Database hosts
    │   ├── 011_user_hosts.sql       # User-host assignments
    │   ├── 020_jobs.sql             # Job queue + retention
    │   ├── 021_job_events.sql       # Job event log
    │   ├── 022_job_history_summary.sql  # Aggregated job metrics
    │   ├── 030_locks.sql            # Distributed locks
    │   ├── 031_settings.sql         # System settings
    │   ├── 040_admin_tasks.sql      # Background tasks
    │   ├── 041_audit_logs.sql       # Security audit trail
    │   ├── 042_procedure_deployments.sql  # Stored proc versioning
    │   ├── 050_disallowed_users.sql # Blocked usernames
    │   ├── 060_feature_requests.sql # Feature request tracking
    │   └── 099_schema_migrations.sql # Migration history
    ├── 01_views/            # Database views (1 file)
    │   └── 001_active_jobs_view.sql # Active jobs view
    ├── 02_seed/             # Seed data (5 files)
    │   ├── 001_seed_db_hosts.sql    # Default database hosts
    │   ├── 002_seed_admin_account.sql   # Admin user seed
    │   ├── 003_seed_service_account.sql # Service account seed
    │   ├── 004_seed_settings.sql    # Default settings
    │   └── 005_seed_disallowed_users.sql # Blocked username defaults
    ├── 03_users/            # MySQL user grants (1 file)
    │   └── 001_mysql_users.sql      # MySQL user creation
    └── archived/            # Archived migrations (1 file)
        └── 022_job_events_offset_index.sql  # Superseded index
```

Total: 28 SQL files (18 tables + 3 migrations + 1 view + 5 seeds + 1 users)

### Table: auth_users (includes RBAC + manager)

```sql
CREATE TABLE auth_users (
    user_id CHAR(36) PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    user_code CHAR(6) NOT NULL UNIQUE,
    role ENUM('user', 'manager', 'admin', 'service') NOT NULL DEFAULT 'user',
    manager_id CHAR(36) NULL,  -- FK to self for manager relationship
    max_active_jobs INT NULL,
    locked_at TIMESTAMP(6) NULL,
    CONSTRAINT fk_auth_users_manager FOREIGN KEY (manager_id) REFERENCES auth_users(user_id)
);
```

### Table: auth_credentials (includes password reset)

```sql
CREATE TABLE auth_credentials (
    user_id CHAR(36) PRIMARY KEY,
    password_hash VARCHAR(255) NULL,  -- bcrypt, NULL = no password set
    totp_secret VARCHAR(64) NULL,     -- TOTP for 2FA
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    password_reset_at TIMESTAMP(6) NULL,  -- Forces password reset when set
    CONSTRAINT fk_credentials_user FOREIGN KEY (user_id) REFERENCES auth_users(user_id)
);
```

### Table: sessions

```sql
CREATE TABLE sessions (
    session_id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    token_hash CHAR(64) NOT NULL,  -- SHA-256 of session token
    expires_at TIMESTAMP(6) NOT NULL,
    last_activity TIMESTAMP(6) NOT NULL,
    ip_address VARCHAR(45) NULL,
    user_agent VARCHAR(255) NULL,
    CONSTRAINT fk_session_user FOREIGN KEY (user_id) REFERENCES auth_users(user_id)
);
```

---

## CLI Architecture & Scope

**Core Principle**: CLIs are thin interface clients to the server applications. All work is performed by the Worker service.

**Documentation**: [docs/hca/pages/cli-reference.md](hca/pages/cli-reference.md)

### pulldb CLI (User-Facing)
- **Scope**: Limited to operations from the user's own point of view
- **Target users**: Developers restoring databases for their own work
- **Commands** (11 total):
  - `restore` - Submit restore jobs
  - `status` - View status of jobs (supports `--rt` for realtime streaming)
  - `search` - Search for customers by pattern
  - `list` - List available backups for a customer
  - `cancel` - Cancel own jobs
  - `history` - View job history
  - `events` - View job events/logs
  - `profile` - Show performance profile for completed jobs
  - `hosts` - Show available database hosts
  - `register` - Register new account or request access from new machine
  - `setpass` - Set a new password
- **NOT allowed** (affects other users' work):
  - ❌ Orphan database reports
  - ❌ Deleting unaligned databases
  - ❌ Global cleanup operations
  - ❌ System-wide administration

### pulldb-admin CLI (Admin-Facing)
- **Scope**: Administrative operations affecting the system as a whole
- **Target users**: System administrators and operators
- **Command Groups** (10 groups, 39 subcommands total):
  - `settings` - Manage configuration (list, get, set, reset, export, diff, pull, push) - 8 subcommands
  - `secrets` - Manage AWS Secrets Manager (list, get, set, delete, test, rotate-host) - 6 subcommands
  - `jobs` - View and manage jobs (list, cancel) - 2 subcommands
  - `backups` - Analyze S3 backup inventory (list, search) - 2 subcommands
  - `cleanup` - Cleanup orphaned staging databases - 1 command
  - `run-retention-cleanup` - Run database retention cleanup - 1 command
  - `hosts` - Manage database hosts (list, add, provision, test, enable, disable, remove, cred) - 8 subcommands
  - `users` - View and manage users (list, show, enable, disable) - 4 subcommands
  - `keys` - Manage API keys (pending, approve, revoke, list) - 4 subcommands
  - `disallow` - Manage disallowed usernames (list, add, remove) - 3 subcommands

### Architectural Flow
```
User CLI (pulldb)     → API Service → Worker Service
Admin CLI (pulldb-admin) → API Service → Worker Service
```

Both CLIs are thin clients that:
1. Accept user input
2. Send commands to the API
3. Display results

The Worker performs all actual operations (database drops, S3 downloads, restores, etc.).

### CLI Package Files

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/cli/__init__.py` | pages | Package exports |
| `pulldb/cli/__main__.py` | pages | CLI entrypoint (`python -m pulldb.cli`) |
| `pulldb/cli/main.py` | pages | User CLI commands (11 commands) |
| `pulldb/cli/admin.py` | pages | Admin CLI entry point |
| `pulldb/cli/admin_commands.py` | pages | Admin CLI command groups (jobs, hosts, users, keys, disallow, cleanup) |
| `pulldb/cli/settings.py` | pages | Settings management commands (8 subcommands) |
| `pulldb/cli/secrets_commands.py` | pages | Secrets Manager CLI (6 subcommands) |
| `pulldb/cli/backup_commands.py` | pages | Backup analysis commands (2 subcommands) |
| `pulldb/cli/parse.py` | pages | `RestoreCLIOptions`, `parse_restore_args()` - CLI argument parsing |
| `pulldb/cli/auth.py` | pages | HMAC signature generation, credential storage |

---

## Web UI Layout Architecture

**Full documentation**: [hca/pages/web-layout.md](hca/pages/web-layout.md)

### Layout Structure
```
┌───────────────────────────────────────────────────────────────────┐
│3│               │          PAGE HEADER BAR                        │
│p│  [Video Logo] │ Page Title    │ Subtitle │          [Login Info]│
│x├─────┐───────────────────────────────────────────────────────────┤
│ │SIDE │                    WORK AREA                              │
│ │BAR  │                  (content-body)                           │
│ │HOVER│               Scrolls independently                       │
│ │     ├───────────────────────────────────────────────────────────┤
│ │     │ © 2026 pullDB • v1.3.0    │    Service Titan/Field Routes │
└───────┴───────────────────────────────────────────────────────────┘
```

### Key Components
- **3px Strip**: Fixed left edge, gradient accent, full viewport height
- **Header**: Full width, video logo + title/subtitle + login info
- **Sidebar**: 12px invisible trigger zone, expands to 220px on hover, overlays content
- **Work Area**: Scrollable content area, flex child of app-body
- **Footer**: Two rows - copyright/version + branding

### Template Blocks
```jinja
{% block header_title %}Page Title{% endblock %}
{% block header_subtitle %}<p class="page-subtitle">Description</p>{% endblock %}
{% block header_actions %}<!-- Buttons/controls -->{% endblock %}
{% block content %}<!-- Main page content -->{% endblock %}
```

### Static Assets
- Logo video: `pulldb/images/pullDB_logo.mp4` → `/static/images/pullDB_logo.mp4`
- Brand logos: `servicetitan-logo.svg`, `fieldroutes-logo.svg`

---

## Web UI Style Guide (NEW)

**Full documentation**: [STYLE-GUIDE.md](STYLE-GUIDE.md)

### Design Philosophy
pullDB is an **internal operations tool**. UI priorities:
1. **Clarity over Cleverness** - Fast, accurate information
2. **Efficiency over Aesthetics** - Minimal clicks for power users
3. **Consistency over Creativity** - Same patterns everywhere

### UX Laws Applied
- **Doherty Threshold**: All transitions < 400ms
- **Hick's Law**: Max 4 stat cards, 7±2 nav items per section
- **Fitts's Law**: Minimum 32px button targets
- **Von Restorff Effect**: Status badges use distinct colors

### Color Quick Reference
| Status | Background | Text |
|--------|------------|------|
| Queued | `gray-100` | `gray-700` |
| Running | `primary-100` | `primary-700` |
| Complete | `success-100` | `success-700` |
| Failed | `danger-100` | `danger-700` |
| Canceled | `warning-100` | `warning-700` |

### Key CSS Tokens
```css
/* Primary brand */
--primary-500: #3b82f6;
--primary-600: #2563eb;

/* Spacing (4px scale) */
--space-4: 1rem;     /* Standard padding */
--space-6: 1.5rem;   /* Card padding */

/* Border radius */
--radius-md: 0.5rem; /* Buttons */
--radius-xl: 1rem;   /* Cards */
```

### Canonical Component Patterns
1. **Stat Card**: Icon (48px) + value + label
2. **Form Card**: Gradient header + icon + form body
3. **Status Badge**: Dot (animated for running) + label
4. **Table**: Uppercase headers, hover rows
5. **Empty State**: Icon + title + description + action

### File Locations
- Base styles: `pulldb/web/templates/base.html` (~160 lines)
- Component styles: Distributed in feature CSS files (`web/*/css/`)
- Static assets: `pulldb/images/` → `/static/images/`

---

## S3 Multi-Location Configuration (v0.0.7)

As of v0.0.7, pullDB supports multiple S3 backup locations configured via environment variable.

**Configuration Format**:
```bash
PULLDB_S3_BACKUP_LOCATIONS='[
  {"name": "staging", "bucket_path": "s3://pestroutesrdsdbs/daily/stg/", "profile": "pr-staging"},
  {"name": "prod", "bucket_path": "s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/", "profile": "pr-prod"}
]'
```

**Location Fields**:
- `name`: Human-readable identifier (used for filtering via `s3env=` option)
- `bucket_path`: Full S3 path including bucket and prefix
- `profile`: AWS profile name for cross-account access

**Usage**:
- `pulldb restore customer=acme` - Searches all configured locations
- `pulldb restore customer=acme s3env=prod` - Searches only locations with "prod" in name
- `pulldb search customer=acme` - Lists backups from all locations
- `pulldb search customer=acme s3env=staging` - Lists backups from staging only

**Worker Behavior**:
The worker filters locations based on job options:
```python
if env and env.lower() not in location.name.lower():
    continue  # Skip non-matching locations
```

---

## Database Terminology (CRITICAL)

**⚠️ Common Confusion Point**: The terms "coordination database" and "coordination-db" have different meanings:

| Term | Type | Meaning |
|------|------|---------|
| **"coordination database"** | Concept | The database that coordinates pullDB operations |
| **`pulldb_service`** | Database Name | The **actual MySQL database name** |
| **`coordination-db`** | Secret Name | AWS Secrets Manager secret path component |
| **`PULLDB_COORDINATION_SECRET`** | Environment Variable | Points to the AWS secret (e.g., `aws-secretsmanager:/pulldb/mysql/coordination-db`) |
| **`PULLDB_MYSQL_DATABASE`** | Environment Variable | The actual database name (default: `pulldb_service`) |

**Examples**:
```bash
# CORRECT ✓
PULLDB_MYSQL_DATABASE=pulldb_service
PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db

# WRONG ✗ - pulldb_coordination does NOT exist!
PULLDB_MYSQL_DATABASE=pulldb_coordination
```

**Python Code Pattern**:
```python
# Resolve credentials from Secrets Manager
from pulldb.infra.secrets import CredentialResolver
resolver = CredentialResolver()
creds = resolver.resolve('aws-secretsmanager:/pulldb/mysql/coordination-db')

# Username comes from environment, NOT from secret
mysql_user = os.getenv('PULLDB_API_MYSQL_USER', 'pulldb_api')
mysql_database = os.getenv('PULLDB_MYSQL_DATABASE', 'pulldb_service')

# Connect to the database
conn = mysql.connector.connect(
    host=creds.host,
    user=mysql_user,           # From environment
    password=creds.password,   # From secret
    database=mysql_database    # From environment
)
```

**Key Attributes**:
- `MySQLCredentials.username` (NOT `.user`)
- `MySQLCredentials.password`
- `MySQLCredentials.host`
- `MySQLCredentials.port`

---

## Accounts & ARNs
- Development account ID: 345321506926
- Staging account ID: 333204494849
- Production account ID: 448509429610

## S3 buckets & paths
- Staging backups bucket: `arn:aws:s3:::pestroutesrdsdbs`
  - Staging path: `s3://pestroutesrdsdbs/daily/stg/`
  - Contains both newer and older mydumper formats
- Production backups bucket: `arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3`
  - Production path: `s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/`

## IAM roles & policies (canonical)
- Dev EC2 role: `arn:aws:iam::345321506926:role/pulldb-ec2-service-role`
  - Expected attached policies (minimum runtime):
    - `pulldb-secrets-manager-access` (GetSecretValue, DescribeSecret, kms:Decrypt)
    - `pulldb-staging-s3-read` (s3:ListBucket, s3:GetObject, s3:HeadObject) — staging access
    - `pulldb-cross-account-assume-role` (sts:AssumeRole for production/staging cross-account roles) — optional
- Staging cross-account role (optional): `arn:aws:iam::333204494849:role/pulldb-cross-account-readonly`
- Production cross-account role (recommended for prod): `arn:aws:iam::448509429610:role/pulldb-cross-account-readonly`

## Secrets Manager (canonical secrets)

**MySQL User Separation (December 2025)**:
- pullDB now uses service-specific MySQL users with least-privilege access:
  - `pulldb_api` - API service (job queue read/write)
  - `pulldb_worker` - Worker service (job processing)
  - `pulldb_loader` - myloader restore operations (target database access)

- **Secrets** (one per user):
  - `/pulldb/mysql/api` - API service credentials
  - `/pulldb/mysql/worker` - Worker service credentials
  - `/pulldb/mysql/loader` - Loader credentials for target hosts
  - `/pulldb/mysql/coordination-db` - Coordination database credentials
  - `/pulldb/mysql/localhost-test` - Local testing credentials

- Secrets live in development account (345321506926) only

- **Required Tags** (applied automatically during host provisioning):
  - All `/pulldb/*` secrets are tagged with `Service=pulldb`
  - Tags are applied automatically when secrets are created via the web UI provisioning flow

- **Secret Structure** (host + password only):
  - `username` comes from service-specific environment variables:
    - `PULLDB_API_MYSQL_USER` (required for API service)
    - `PULLDB_WORKER_MYSQL_USER` (required for Worker service)
  - `PULLDB_MYSQL_PORT` (optional, default 3306)
  - `PULLDB_MYSQL_DATABASE` (default: `pulldb_service`)

- **Database**: `pulldb_service` (renamed from `pulldb`)
- **Schema path**: `schema/pulldb_service/`

- Runtime policy (`pulldb-secrets-manager-access`) should grant:
  - Full CRUD on secrets: `GetSecretValue`, `DescribeSecret`, `CreateSecret`, `DeleteSecret`, `PutSecretValue`, `UpdateSecret` on `arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/mysql/*`
  - Tagging: `TagResource`, `UntagResource` (required for CreateSecret with tags)
  - Utility: `GetRandomPassword` (for password generation)
  - `secretsmanager:ListSecrets` with `Resource: "*"` (no condition - AWS does not support condition keys for ListSecrets per service authorization reference)
  - `kms:Decrypt`, `kms:DescribeKey` (conditioned to Secrets Manager usage)
  - **Note**: ResourceTag conditions do NOT work for `ListSecrets` - AWS ignores them. Use `--filters` client-side instead.

## Local MySQL Root Credentials (Development Host)

The development MySQL instance uses dual root authentication:

| User | Host | Plugin | Auth Method |
|------|------|--------|-------------|
| `root` | `localhost` | `auth_socket` | `sudo mysql` (no password) |
| `root` | `%` | `caching_sha2_password` | Network with password |

**root@localhost (Socket Auth)**:
- Purpose: Local admin via unix socket
- Access: `sudo mysql` (must be root/sudo)
- No password required - authenticates via OS user

**root@% (Network Auth)**:
- Purpose: Remote/network admin access
- Password: `WddfAUBoHXOZrYkUT6JWv7lE`
- Access: `mysql -h <ip> -u root -p` or from remote hosts
- Test: `MYSQL_PWD='WddfAUBoHXOZrYkUT6JWv7lE' mysql -h 10.40.10.117 -u root`

**Important**: Never modify `root@localhost` authentication - it should always use `auth_socket`.

## Machine-readable index (JSON)
The following JSON block is a compact, program-friendly index of the core artifacts referenced in this file. Use it as a single-source map for automation or verification scripts.

```json
{
  "accounts": {
    "development": "345321506926",
    "staging": "333204494849",
    "production": "448509429610"
  },
  "s3": {
    "staging_bucket": "pestroutesrdsdbs",
    "staging_prefix": "daily/stg/",
    "production_bucket": "pestroutes-rds-backup-prod-vpc-us-east-1-s3",
    "production_prefix": "daily/prod/"
  },
  "iam": {
    "dev_ec2_role": "arn:aws:iam::345321506926:role/pulldb-ec2-service-role",
    "staging_cross_account_role": "arn:aws:iam::333204494849:role/pulldb-cross-account-readonly",
    "production_cross_account_role": "arn:aws:iam::448509429610:role/pulldb-cross-account-readonly",
    "instance_profile": "pulldb-instance-profile"
  },
  "secrets": {
    "api": "/pulldb/mysql/api",
    "worker": "/pulldb/mysql/worker",
    "loader": "/pulldb/mysql/loader"
  },
  "schema": {
    "canonical_doc": "docs/hca/entities/mysql-schema.md",
    "database": "pulldb_service",
    "schema_dir": "schema/pulldb_service/",
    "hosts_table": "db_hosts"
  },
  "mysql_users": {
    "api": "pulldb_api",
    "worker": "pulldb_worker",
    "loader": "pulldb_loader"
  }
}
```

This JSON is intentionally compact. The full machine-readable index is in `docs/KNOWLEDGE-POOL.json`.

## EC2 / Instance Profile
- Instance profile name: `pulldb-instance-profile`
- Instance profile must contain the role `pulldb-ec2-service-role` and be attached to the EC2 instance running API + Worker
- IMDSv2 is used for token-based metadata retrieval in verification steps

### Quick IAM policy snippets (safe examples)
These are minimal, least-privilege examples suitable for transforming into full policies or templates.

- staging S3 read policy (attach to role used by dev instances for staging bucket):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::pestroutesrdsdbs"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:HeadObject"],
      "Resource": "arn:aws:s3:::pestroutesrdsdbs/daily/stg/*"
    }
  ]
}
```

- production cross-account assume-role trust (to be created in production account):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::345321506926:role/pulldb-ec2-service-role"},
      "Action": "sts:AssumeRole",
      "Condition": {"StringEquals": {"sts:ExternalId": "<EXTERNAL_ID_HERE>"}}
    }
  ]
}
```

Replace `<EXTERNAL_ID_HERE>` with a strong, unique external ID provided by the dev account when creating the trust relationship.

### Terraform hint (small snippet)
If you use Terraform for IAM, this minimal snippet demonstrates creating an assume-role in the production account:

```hcl
resource "aws_iam_role" "pulldb_cross_account" {
  name = "pulldb-cross-account-readonly"
  assume_role_policy = file("./pulldb-cross-account-trust.json")
}
```

This file should be created and applied in the production account only. Keep secrets/keys out of Terraform state.

## Restore workflow facts (operational)
- Staging database naming: `{target}_{job_id_first_12_chars}` (max lengths enforced)
- S3 preflight: require `*-schema-create.sql.{gz,zst}` exists and `free_space >= tar_size * 1.8` before extraction
- Post-restore SQL: executed from `customers_after_sql_dir` setting (default: `/opt/pulldb.service/customers_after_sql/` installed, `template_after_sql/customer/` in dev) in lexicographic order
- Atomic rename via stored procedure: `pulldb_atomic_rename` / `pulldb_atomic_rename_preview` exists and is versioned
- **Progress deduplication** (v0.2.0): ProcesslistMonitor polls every 2s but events only emit when overall percent OR any table's percent changes by 1%+. Dedup key: `(int(percent), active_threads, tuple(sorted(table_progress)))`. CLI uses TTY detection for in-place line updates (`\r`). Web UI has `_deduplicate_logs()`.

### Worker Process Features (v1.3.0)

| Feature | Description | Source |
|---------|-------------|--------|
| **Phase Weighting** | Progress split: 85% data load, 15% index rebuild | `pulldb/worker/restore_progress.py` |
| **Heartbeat Suppression** | Skip heartbeat if meaningful event emitted within 30s | `pulldb/worker/heartbeat.py`, `pulldb/worker/executor.py` |
| **Early Analyze** | Background ANALYZE TABLE during restore for statistics | `pulldb/worker/early_analyze.py` |
| **Strike-based Completion** | 3-5 poll cycles (2s each) without activity = table complete | `pulldb/worker/restore_progress.py` |
| **Processlist Monitor** | MySQL SHOW PROCESSLIST polling for progress tracking | `pulldb/worker/processlist_monitor.py` |
| **Metadata Synthesis** | Generate myloader 0.19-compatible metadata for legacy backups | `pulldb/worker/backup_metadata.py` |

#### Phase Weighting Details

```python
# Progress calculation in restore_progress.py
DATA_PHASE_WEIGHT = 0.85   # Data loading = 85% of total
INDEX_PHASE_WEIGHT = 0.15  # Index rebuild = 15% of total

# Overall progress = (data_progress * 0.85) + (index_progress * 0.15)
```

#### Heartbeat Suppression

Prevents excessive heartbeat events when meaningful progress is being emitted:

```python
HEARTBEAT_SUPPRESSION_WINDOW_SECONDS = 30.0

# In executor.py:
# - Track last meaningful event timestamp
# - Skip heartbeat if meaningful event emitted within window
# - Meaningful events: table_progress, download_progress, etc.
```

### Worker Module Files (v1.3.0)

| File | Purpose |
|------|---------|
| `pulldb/worker/service.py` | Main worker service entry point |
| `pulldb/worker/loop.py` | Worker main loop and job dispatch |
| `pulldb/worker/executor.py` | Job execution orchestrator |
| `pulldb/worker/downloader.py` | S3 backup download management |
| `pulldb/worker/restore.py` | Restore orchestration |
| `pulldb/worker/restore_progress.py` | Phase-weighted progress calculation |
| `pulldb/worker/restore_state_tracker.py` | Tracks restore state across phases |
| `pulldb/worker/processlist_monitor.py` | MySQL SHOW PROCESSLIST poller |
| `pulldb/worker/staging.py` | Staging database lifecycle |
| `pulldb/worker/post_sql.py` | Post-restore SQL script executor |
| `pulldb/worker/backup_metadata.py` | Metadata synthesis for legacy backups |
| `pulldb/worker/metadata.py` | Backup metadata parsing |
| `pulldb/worker/heartbeat.py` | Worker heartbeat management |
| `pulldb/worker/early_analyze.py` | Background ANALYZE TABLE |
| `pulldb/worker/atomic_rename.py` | Atomic database rename procedures |
| `pulldb/worker/cleanup.py` | Post-job cleanup operations |
| `pulldb/worker/retention.py` | Database retention enforcement |
| `pulldb/worker/admin_tasks.py` | Background admin task runner |
| `pulldb/worker/overlord_manager.py` | Overlord company management |
| `pulldb/worker/profiling.py` | Worker performance profiling |
| `pulldb/worker/log_normalizer.py` | Log output normalization |
| `pulldb/worker/myloader_log_parser.py` | Myloader log parsing and analysis |
| `pulldb/worker/table_analyzer.py` | Table structure analysis |
| `pulldb/worker/history_backfill.py` | Job history backfill operations |
| `pulldb/worker/feature_request_service.py` | Feature request processing |

---

## Database Schema (Quick Reference)
- **Canonical Source**: `docs/hca/entities/mysql-schema.md` (Read this for full column definitions)
- **Hosts Table**: `db_hosts` (NOT `hosts`) - contains registered database servers
- **Jobs Table**: `jobs` - tracks restore requests and status
- **Users Table**: `auth_users` - tracks authorized users
- **Settings Table**: `settings` - dynamic configuration (key/value)

## Test Configuration (Local Development)
- **Test MySQL credentials**: Set environment variables to use local MySQL instead of AWS Secrets Manager:
  - `PULLDB_TEST_MYSQL_HOST=localhost`
  - `PULLDB_TEST_MYSQL_USER=pulldb_app`
  - `PULLDB_TEST_MYSQL_PASSWORD=<password>` (or empty string for auth_socket users)
- **Auto-database setup**: The test suite automatically creates the `pulldb_service` database if it doesn't exist and drops it after tests if it was created by the test suite
- **Schema location**: `schema/pulldb_service/` (subdirectories applied in order: 00_tables, 01_views, 02_seed, 03_users)
- **Empty password handling**: Empty passwords (`""`) are valid - the fixture checks `password is not None` not truthiness

## Local Environment & Binaries
- myloader binaries location: `/opt/pulldb.service/bin/` (installed)
  - Source location: `pulldb/binaries/`
  - Current version: `myloader-0.21.1-1` (unified binary for all backup formats)
  - Legacy backup support: Metadata synthesis in `pulldb/worker/backup_metadata.py`
- Development templates: `scripts/dev_templates/dev_extensions.html` (dev toolbar extensions)

## System Paths & Service Locations
- **Installation Root**: `/opt/pulldb.service`
- **Virtual Environment**: `/opt/pulldb.service/venv`
- **Logs**: `/opt/pulldb.service/logs`
- **Work Directory**: `/opt/pulldb.service/work`
- **Systemd Units**:
  - API Service: `/etc/systemd/system/pulldb-api.service`
  - Worker Service: `/etc/systemd/system/pulldb-worker.service`
  - Web Service: `/etc/systemd/system/pulldb-web.service`
  - Retention Timer: `/etc/systemd/system/pulldb-retention.timer`
- **Binaries**:
  - `pulldb` CLI: `/opt/pulldb.service/venv/bin/pulldb`
  - `myloader`: `/opt/pulldb.service/bin/myloader` (symlinked or direct)

## Lessons Learned & Troubleshooting
- **Service User Identity**: Services (`pulldb-api`, `pulldb-worker`) MUST run as the `pulldb` system user. Running as `root` or a developer user causes permission issues with logs and work directories.
- **S3 Backup Structure**: Some S3 tarballs contain a top-level directory (e.g., `customer/metadata`) while others are flat. `myloader` fails if pointed at the root of a nested backup. The worker now automatically resolves the correct path by searching for the `metadata` file within the extracted archive.
- **Progress Reporting**: `myloader` does not natively report percentage progress. We estimate progress by tracking S3 download bytes vs total size.
- **AWS Profile Scoping**: `PULLDB_AWS_PROFILE` controls the default boto3 session (Secrets Manager, SSM). `PULLDB_S3_AWS_PROFILE` controls the S3 client.
  - **Issue**: Setting `PULLDB_AWS_PROFILE=pr-prod` breaks Secrets Manager access because the production role cannot read dev secrets.
  - **Fix**: Use `PULLDB_S3_AWS_PROFILE=pr-prod` for S3 access, and leave `PULLDB_AWS_PROFILE` unset (to use instance profile) or set to `pr-dev`.
- **Logical Hostnames**: The `hostname` column in `db_hosts` is a logical alias (e.g., `dev-db-01`), NOT the FQDN. The actual connection FQDN is stored in the AWS Secret referenced by `credential_ref`. This allows CLI users to use short names while the system connects securely.
- **Testing Restriction**: Use `dev-db-01` or `localhost` for testing purposes.
- **MySQL Root Socket Auth**: On localhost, root MySQL user uses `auth_socket` plugin (no password needed when connecting via Unix socket). Scripts running as root MUST use socket auth, not TCP with password.
- **Schema Updates (Jan 2026)**: The package installer (postinst) now automatically applies new schema files from `schema/pulldb_service/` and tracks them in the `schema_migrations` table. No separate migration command is needed.

### myloader --resume Manual Recovery (Jan 2026)

**Critical Knowledge**: myloader's `--resume` flag behavior is the **opposite** of what you might expect.

- **Common Misconception**: Resume file = "files already done, skip these"
- **Actual Behavior**: Resume file = "files TO PROCESS" (only these files will be loaded)

**Scenario**: Partial restore failed, need to reload only specific tables (e.g., `changeLog`, `salesRoutesAccess`)

**Correct Resume File Setup**:
```bash
# Resume file should contain ONLY the files you want to load
cd /path/to/extracted/backup
ls -1 *.sql.gz | grep -E "^dbname\.changeLog[\.-]|^dbname\.salesRoutesAccess[\.-]" > resume

# Verify contents - should be schema + data files for target tables only
wc -l resume  # e.g., 608 files for 2 tables
```

**Resume File Format**:
- One filename per line (just the filename, not full path)
- Includes both `-schema.sql.gz` and `.00000.sql.gz` (data) files
- Example:
  ```
  foxpest.changeLog-schema.sql.gz
  foxpest.changeLog.00000.sql.gz
  foxpest.changeLog.00001.sql.gz
  ...
  foxpest.salesRoutesAccess-schema.sql.gz
  foxpest.salesRoutesAccess.00000.sql.gz
  ```

**myloader Command**:
```bash
myloader-0.19.3-3 \
  --host=$DB_HOST \
  --user=$DB_USER \
  --password="$DB_PASS" \
  --database=$STAGING_DB \
  --directory=/path/to/extracted/backup \
  --threads=4 \
  --resume \
  --optimize-keys=AFTER_IMPORT_PER_TABLE
```

**Pre-Requisites Before Resume**:
1. **Tables must be dropped first** if they already have partial data
2. **Metadata file** must be 0.19-compatible INI format (use `ensure_myloader_compatibility()`)
3. **Resume file** must contain ONLY the files to load

**Metadata File Synthesis** (if backup has old mydumper 0.9 format):
```python
from pulldb.worker.backup_metadata import ensure_myloader_compatibility
ensure_myloader_compatibility('/path/to/extracted/backup')
```

**Verification Commands**:
```bash
# Count files to load
wc -l resume

# Breakdown by table
grep -c "^dbname\.changeLog" resume
grep -c "^dbname\.salesRoutesAccess" resume

# Verify no other tables included
grep -v "changeLog" resume | grep -v "salesRoutesAccess" | head
```

**Common Mistakes**:
1. ❌ Putting "completed" files in resume (opposite of intended behavior)
2. ❌ Including metadata file references (myloader ignores non-.sql.gz entries)
3. ❌ Using `--drop-table` with existing partial data (use DROP + resume instead)
4. ❌ Forgetting to include schema files (tables won't exist to load data into)

### Packaging & Installation Lessons (Jan 2026)

- **dpkg Lock During preinst/postinst**:
  - **Problem**: Attempted to install Python 3.12 via apt-get inside preinst script.
  - **Reality**: dpkg holds exclusive lock on /var/lib/dpkg/lock during package installation phases.
  - **Fix**: preinst should only CHECK for dependencies, not install them.
  - **Pattern**: Exit with helpful message if dependency missing; document pre-installation steps.

- **deadsnakes PPA Dropped Ubuntu 20.04 (Focal)**:
  - **Discovery Date**: January 2026
  - **Problem**: `ppa:deadsnakes/ppa` no longer publishes Python 3.10+ for Ubuntu 20.04 (focal).
  - **Supported**: Only Ubuntu 22.04 (jammy) and later.
  - **Workaround**: Build Python 3.12 from source on Ubuntu 20.04 (~10 min build time).
  - **Commands**:
    ```bash
    sudo apt install -y build-essential libssl-dev zlib1g-dev \
      libbz2-dev libreadline-dev libsqlite3-dev libffi-dev liblzma-dev
    cd /tmp && wget https://www.python.org/ftp/python/3.12.8/Python-3.12.8.tgz
    tar xzf Python-3.12.8.tgz && cd Python-3.12.8
    ./configure --enable-optimizations --prefix=/usr/local
    make -j$(nproc) && sudo make altinstall
    sudo ln -sf /usr/local/bin/python3.12 /usr/bin/python3.12
    ```
  - **Recommendation**: Upgrade to Ubuntu 22.04+ where possible.

- **CAP_NET_BIND_SERVICE for Port 80**:
  - **Problem**: pulldb-web failed to bind port 80 with "Permission denied" when running as non-root.
  - **Solution**: Grant `CAP_NET_BIND_SERVICE` capability via systemd.
  - **Implementation**:
    ```bash
    sudo mkdir -p /etc/systemd/system/pulldb-web.service.d
    cat <<EOF | sudo tee /etc/systemd/system/pulldb-web.service.d/override.conf
    [Service]
    AmbientCapabilities=CAP_NET_BIND_SERVICE
    EOF
    sudo systemctl daemon-reload && sudo systemctl restart pulldb-web
    ```
  - **Alternatives**: Use reverse proxy (nginx/caddy), socket activation, or authbind.
  - **Security Note**: CAP_NET_BIND_SERVICE is least privilege; only allows binding ports <1024.

- **Environment Variable Precedence (systemd vs .env)**:
  - **Problem**: Same variable defined in both `/opt/pulldb/.env` and systemd `Environment=`.
  - **Resolution**: systemd `Environment=` wins (process environment overrides dotenv).
  - **Pattern**: Use `.env` for defaults, systemd overrides for deployment-specific values.
  - **Debugging**: `systemctl show pulldb-api --property=Environment` shows effective values.

### Phase 2 Lessons (Nov 2025)

- **AWS Region Configuration**:
  - **Problem**: boto3 failed with "You must specify a region" when running outside AWS.
  - **Root Cause**: CredentialResolver didn't pass region to boto3.Session().
  - **Fix**: Added `aws_region` parameter with fallback chain: explicit param → `PULLDB_AWS_REGION` → `AWS_DEFAULT_REGION` → `"us-east-1"`.
  - **Recommendation**: Always set `AWS_DEFAULT_REGION` in `.env` files for non-EC2 environments.

- **Settings Sync (db ↔ .env)**:
  - **Problem**: Settings changes required editing both database AND .env file manually.
  - **Solution**: Implemented `pulldb-admin settings pull/push/diff` commands.
  - **Commands**: `pull` (db→env), `push` (env→db), `diff` (compare both).
  - **File Detection**: Auto-finds `/opt/pulldb.service/.env` (installed) or repo root `.env` (dev).

- **dpkg Upgrade Auto-Applies Schema** (Jan 2026 update):
  - **Current Behavior**: `dpkg -i pulldb_*.deb` automatically applies new schema files via postinst.
  - **Tracking**: Applied files tracked in `schema_migrations` table.
  - **Verification**: `mysql -e "SELECT * FROM pulldb_service.schema_migrations ORDER BY applied_at"`

- **CLI dotenv Auto-Loading**:
  - **Problem**: CLI tools required manual `source .env` before use.
  - **Fix**: Added `load_dotenv()` at module import in `admin.py` and `main.py`.
  - **Behavior**: Auto-loads `.env` from working directory or install paths.

### Database Terminology Confusion (Jan 2026)

**Common Mistake**: Using `pulldb_coordination` as the database name.

- **Problem**: The term "coordination database" in code comments and "coordination-db" in AWS secret paths led to confusion about the actual database name.
- **Root Cause**: Multiple meanings:
  - "coordination database" = **concept** (the database that coordinates operations)
  - `coordination-db` = **secret path component** in AWS Secrets Manager
  - `pulldb_service` = **actual database name**
- **Symptoms**:
  - `ERROR 1044: Access denied to database 'pulldb_coordination'`
  - Attempting to connect to non-existent `pulldb_coordination` database
  - Looking for non-existent functions like `resolve_database_credentials()` or `get_coordination_credentials()`
- **Resolution**: Always use `pulldb_service` as the database name (from `PULLDB_MYSQL_DATABASE` env var).
- **Credential Resolution Pattern**:
  ```python
  from pulldb.infra.secrets import CredentialResolver
  resolver = CredentialResolver()
  creds = resolver.resolve('aws-secretsmanager:/pulldb/mysql/coordination-db')
  
  # Username from environment, NOT from secret
  mysql_user = os.getenv('PULLDB_API_MYSQL_USER', 'pulldb_api')
  mysql_database = os.getenv('PULLDB_MYSQL_DATABASE', 'pulldb_service')
  
  conn = mysql.connector.connect(
      host=creds.host,
      user=mysql_user,        # From environment
      password=creds.password,  # From secret
      database=mysql_database   # From environment - pulldb_service!
  )
  ```
- **Key Attributes**: `MySQLCredentials.username` (NOT `.user`), `.password`, `.host`, `.port`
- **Documentation Updates**: Added clarification sections to KNOWLEDGE-POOL.md, KNOWLEDGE-POOL.json, and code comments in `pulldb/infra/bootstrap.py` and `pulldb/infra/mysql.py` (now decomposed into 8 sub-modules + facade).

## myloader 0.19 Metadata Compatibility
- **Source**: `src/myloader/myloader_process.c` (GitHub)
- **[config] Section**: Keys here are treated as command-line arguments (prepended with `--`).
  - Useful for: `rows`, `threads`, `database`, `compress-protocol`, `local-infile`.
- **[myloader_session_variables] Section**: Sets MySQL session variables.
  - Critical for restores: `sql_log_bin=0`, `foreign_key_checks=0`, `time_zone='+00:00'`.
- **Table Sections**: `[database.table]` (quoted).
  - `real_table_name`: Allows renaming.
  - `rows`: Critical for progress bar accuracy.
  - `is_view`, `is_sequence`: Object type flags.
- **Replication**: `[source]`, `[master]`, `[replication...]` sections for GTID/binlog setup.

## Quick commands & verification
- Verify caller identity (from EC2 with instance profile):
  - `aws sts get-caller-identity`
- List staging backups (from instance with role attached):
  - `aws s3 ls s3://pestroutesrdsdbs/daily/stg/`
- Check secret: `aws secretsmanager get-secret-value --secret-id /pulldb/mysql/coordination-db`
- Verify instance profile attached to EC2:
  - IMDSv2 token + metadata: `TOKEN=$(curl -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds:21600' -s)` then `curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/ -s`

## Purge candidates (docs/files to archive)
*Criteria*: documents that are obsolete, duplicated, or superseded by `docs/AWS-SETUP.md` and `docs/KNOWLEDGE-POOL.md`.

- `docs/aws-quickstart.md` — superseded and removed
- `docs/aws-ec2-deployment-setup.md` — superseded (content consolidated)
- `docs/aws-doc-consolidation.md` — consolidation metadata (archive)
- `docs/aws-setup.md.OBSOLETE` and similar `*.OBSOLETE` files — archive or delete
- Any duplicate copies of the same topic (see file_search duplicates list)

---

## Web UI Design Patterns (December 2025)

### Hover-Reveal Sidebar Pattern
The pullDB web interface uses a **hover-reveal sidebar** pattern for maximum content area:

**Core Behavior**:
- Sidebar hidden by default using negative left position (`left: calc(-1 * var(--sidebar-width))`)
- Content area uses 100% width (`margin-left: 0`)
- Sidebar floats over content as overlay when triggered
- Opens via: left edge hover (5px trigger zone) OR menu button tap
- Closes via: mouse leave (with delay) OR backdrop click

**CSS Architecture** (actual from `sidebar.css`):
```css
.app-sidebar {
    position: fixed;
    left: calc(-1 * var(--sidebar-width-expanded, 240px));  /* Hidden */
    transition: left 0.3s ease, box-shadow 0.3s ease;
    z-index: var(--z-sticky);
}
.app-sidebar.sidebar-open {
    left: 0;
    box-shadow: var(--shadow-lg);
}
.sidebar-trigger {  /* Invisible left edge zone */
    position: fixed; left: 0; width: 5px; height: 100%; z-index: 100;
}
.sidebar-backdrop {  /* Dark overlay when open */
    position: fixed; inset: 0; background: rgba(0, 0, 0, 0.3); z-index: 150;
}
```

**JavaScript Timing**:
- Open: immediate (no delay on mouseenter)
- Close delay: 300ms (prevents flickering)
- Menu button: immediate (no delay needed)

### Device Detection (Touch vs Mouse)
Use CSS media queries to detect input capabilities:

**Media Queries**:
```css
/* Mouse/trackpad devices: hide menu button, use edge hover */
@media (hover: hover) and (pointer: fine) {
    .menu-btn { display: none; }
    .sidebar-trigger { display: block; }
}

/* Touch devices: show menu button, hide edge trigger */
@media (hover: none), (pointer: coarse) {
    .menu-btn { display: flex; }
    .sidebar-trigger { display: none; }
}
```

**Values**:
- `hover: hover` - Device supports true hover (mouse/trackpad)
- `hover: none` - No hover support (touch devices)
- `pointer: fine` - Precise pointer (mouse)
- `pointer: coarse` - Imprecise pointer (finger/touch)

**JavaScript Alternative**:
```javascript
// Check if device has hover capability
const hasHover = window.matchMedia('(hover: hover)').matches;
const hasFinePointer = window.matchMedia('(pointer: fine)').matches;
const isTouchDevice = navigator.maxTouchPoints > 0;
```

### Responsive Table Layout Pattern
For full-viewport data tables (Jobs page):

**Key Classes** (actual from `layout.css`):
- `.app-body` - `display: flex; min-height: 0; overflow: hidden`
- `.main-content` - flex column container with `min-height: 0`
- `.content-body` - flex: 1 with `overflow-y: auto`

**Critical CSS** (actual):
```css
.app-body {
    display: flex;
    min-height: 0;
    overflow: hidden;
}
.main-content {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.content-body {
    flex: 1;
    overflow-y: auto;
    min-height: 0;  /* Allow shrinking */
}
```

### VirtualScroller (3-Window Pattern)
For large datasets with smooth scrolling:

**Architecture**:
- Renders 3 "windows" of rows (before, visible, after)
- Each window = viewport height worth of rows
- Scroll position determines which rows to render
- Placeholder divs maintain scroll height

**Key Parameters**:
- `rowHeight`: Fixed height per row (required)
- `overscan`: Extra rows above/below viewport (default: 10)
- `totalRows`: Total dataset size
- `visibleRange`: Currently rendered row indices

---

---

## Myloader Thread Architecture & Progress Tracking (Jan 2026)

Understanding how myloader manages threads internally is critical for accurate progress tracking in pullDB.

### Myloader Internal Thread Types

| Thread Type | Count | Purpose | MySQL User |
|-------------|-------|---------|------------|
| **Loader Threads** (`L-Thread N`) | `--threads` (default 4) | Process data files, execute INSERTs | `pulldb_loader` |
| **Connection Pool** (`myloader_conn`) | `--threads` (N threads) | Execute queries via `connection_pool` queue | `pulldb_loader` |
| **Schema Threads** | `--max-threads-for-schema-creation` (default 4) | CREATE TABLE statements | `pulldb_loader` |
| **Index Threads** (`I-Thread N`) | `--max-threads-for-index-creation` (default 4) | ALTER TABLE ADD INDEX | `pulldb_loader` |
| **Post Threads** | `--max-threads-for-post-actions` (default 1) | Triggers, constraints | `pulldb_loader` |
| **Control Thread** (`CJT`) | 1 | Job dispatching, coordination | Internal |
| **Directory Thread** | 1 | File discovery | Internal |

**Key insight**: With `--threads=6`, you may see **more than 6 connections** in MySQL's processlist because:
1. Index threads run in parallel with final data loads
2. Schema threads may overlap with data threads
3. Connection pool reuse can show multiple "slots"

### Thread Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────┐
│ STARTUP                                                                 │
│  initialize_connection_pool()  → Creates N connection slots             │
│  start_connection_pool()       → Spawns N restore_thread() threads      │
│  initialize_loader_threads()   → Spawns N loader_thread() threads       │
│  start_worker_schema()         → Schema creation threads                │
└─────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ EXECUTION                                                               │
│  Loader thread picks job from data_job_queue                            │
│    → wait_for_available_restore_thread() gets connection from pool      │
│    → restore_data_from_mydumper_file() reads .sql file                  │
│    → restore_insert() sends batched INSERTs via connection pool         │
│    → mysql_real_query() BLOCKS until MySQL completes                    │
│    → Connection returned to pool                                        │
│  remaining_jobs atomically decremented after file completes             │
└─────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ DATA_DONE → INDEX                                                       │
│  When remaining_jobs=0 AND current_threads=0:                           │
│    → schema_state = DATA_DONE                                           │
│    → "Enqueuing index for table: db.table" printed                      │
│    → Job added to index_queue                                           │
│    → Index threads process ALTER TABLE ADD KEY                          │
└─────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ SHUTDOWN                                                                │
│  wait_schema_worker_to_finish()                                         │
│  wait_worker_loader_main()                                              │
│  wait_index_worker_to_finish()                                          │
│  wait_post_worker_to_finish()                                           │
│  wait_restore_threads_to_close()  → g_thread_join() all threads         │
│  "Restore completed" printed                                            │
└─────────────────────────────────────────────────────────────────────────┘
```

### Index Rebuild: Single vs Multiple ALTER Statements

**Normal indexes**: myloader builds ONE ALTER statement with all indexes:
```sql
ALTER TABLE `t` 
ADD KEY `idx1` (`col1`),
ADD KEY `idx2` (`col2`),
ADD UNIQUE KEY `unique_idx` (`col3`);
```

**FULLTEXT indexes**: MySQL cannot add multiple FULLTEXT indexes in one ALTER.
myloader detects this and splits into SEPARATE ALTER statements:
```sql
ALTER TABLE `t` ADD FULLTEXT KEY `ft1` (`col1`);
ALTER TABLE `t` ADD FULLTEXT KEY `ft2` (`col2`);
ALTER TABLE `t` ADD FULLTEXT KEY `ft3` (`col3`);
```

**Progress tracking implication**: For tables with multiple FULLTEXT indexes:
1. Table appears in processlist for first ALTER
2. First ALTER completes → table **briefly leaves** processlist
3. Second ALTER starts → table **reappears** in processlist
4. Repeat for each FULLTEXT index

This is why we use a **strike-based approach** instead of time-based:
- Strike = one poll where table is absent from processlist
- Table reappears (next FULLTEXT ALTER) → strikes reset to 0
- After N consecutive strikes → mark complete
- Naturally handles any number of FULLTEXT gaps

### Critical Facts About mysql_real_query()

**`mysql_real_query()` is SYNCHRONOUS (blocking)**:
- myloader sends query, waits for MySQL server response
- Thread is blocked until query completes
- myloader does NOT exit while queries are in-flight

**Implication**: If you see INSERTs in `SHOW PROCESSLIST` but myloader shows 100%, the issue is NOT async query execution. Look for:
1. Multiple concurrent myloader processes
2. Progress calculation bugs in pullDB
3. Stale processlist monitor state

### The `/* Completed: XX% */` Comment

```c
// From myloader_restore.c:
g_string_printf(new_insert,"/* Completed: %"G_GUINT64_FORMAT"%% */ ",
    dbt->rows>0?dbt->rows_inserted*100/dbt->rows:0);
```

**What it means**:
- `dbt->rows_inserted` = rows already loaded for this table BEFORE current batch
- `dbt->rows` = total row estimate from metadata file
- Shows **per-table progress** at the moment the batch is created

**Why you see 0%**:
1. **Legacy backups (0.9.0)**: metadata sets `rows=0` for all tables → formula gives 0%
2. **First batch**: `rows_inserted=0` at start → 0%
3. **Not useful for 0.9.0 backups** - use file-based progress instead

### pullDB Progress Tracking vs Myloader

| Source | What It Tracks | Reliability |
|--------|---------------|-------------|
| **ProcesslistMonitor** | Active threads in MySQL processlist | Real-time but sampling |
| **Myloader stdout** | "Progress X of Y", "Enqueuing index" | Definitive events |
| **`/* Completed: XX% */`** | Per-table row progress | **Broken for rows=0 backups** |
| **File-based progress** | files_started / file_count | Safe, cannot exceed 100% |

### How pullDB Calculates Progress

```python
# From restore_progress.py _calculate_rows_loaded():
for state in self._tables.values():
    if state.is_complete or state.data_complete:
        total += state.rows_total  # 100% of rows
    elif state.files_started > 0 and state.file_count > 0:
        # File-based: safe, cannot exceed 100%
        file_percent = state.files_started / state.file_count
        total += int(file_percent * state.rows_total)
    else:
        # Fallback to processlist percent (capped at 100%)
        total += int(state.percent_complete / 100.0 * state.rows_total)
```

**For 0.9.0 backups with rows=0**:
- `rows_total = 0` for all tables
- `total` will always be 0
- Progress falls back to file-based calculation in `_calculate_file_based_percent()`

### Debugging Checklist

When progress shows 100% but processlist shows active queries:

1. **Check if single myloader**: `ps aux | grep myloader` - ensure only one process
2. **Check staging DB match**: Ensure processlist queries target the same staging DB
3. **Check thread counts**: With `--threads=6`, you can see 6+ connections due to index threads
4. **Check `finalize()` timing**: `tracker.finalize()` marks 100% - verify myloader actually exited
5. **Check file-based progress**: For 0.9.0 backups, file counts determine progress

### Known Bug: Premature 100% Completion (Fixed Jan 2026)

**Root cause**: The original timeout logic was marking tables complete too aggressively.

**Original bug in `restore_progress.py`**:
```python
# BUG: This marked tables complete after 10s absence from processlist
# even without any evidence myloader actually finished processing them
_STALE_TABLE_TIMEOUT_SECONDS = 10.0  # Too short!

if (
    state.files_completed > 0
    or time_since_seen > _STALE_TABLE_TIMEOUT_SECONDS  # ← Problem: OR not AND
):
    self._mark_table_complete(state, now)  # ← Premature!
```

**How it manifested**:
1. myloader loads files in **random order** (not sequential per table)
2. Table A appears in processlist while loading file 1
3. myloader switches to table B (table A leaves processlist)
4. After 10s, table A marked complete (even though files 2-N not done)
5. Progress calculation counts ALL files for table A as done
6. Repeat → premature 100%

**Fix applied - Strike-based detection**:
```python
# Strike = one poll where table is absent from processlist
# Poll interval is 2s, so 3 strikes = 6s minimum absence

_INDEX_COMPLETE_STRIKES = 3     # After data_complete (indexing phase)
_FALLBACK_COMPLETE_STRIKES = 5  # No data_complete (less certain)

# Table in processlist → reset strikes to 0
if state.name in tables_in_processlist:
    state.absent_strikes = 0
    continue

# Table absent → increment strike
state.absent_strikes += 1

if state.data_complete:
    if state.absent_strikes >= _INDEX_COMPLETE_STRIKES:
        self._mark_table_complete(state, now)
else:
    if state.absent_strikes >= _FALLBACK_COMPLETE_STRIKES:
        self._mark_table_complete(state, now)  # With warning log
```

**Why strikes are better than time-based**:
- Naturally handles FULLTEXT gaps: table reappears → strikes reset → wait again
- Poll-based: directly tied to actual observations, not wall-clock time
- Self-correcting: if table comes back, we start over

**Key insight**: Do NOT use `files_started`/`files_completed` for completion detection. myloader processes files in random order, so seeing some files done doesn't mean the table won't reappear in processlist.

### Configuration Impact

| Setting | Default | Effect on Thread Count |
|---------|---------|----------------------|
| `--threads` | 4 | Data loader threads, connection pool size |
| `--max-threads-per-table` | 4 | Max parallel threads per single table |
| `--max-threads-for-schema-creation` | 4 | Schema threads (auto-scaled up to 8 on multi-core) |
| `--max-threads-for-index-creation` | 4 | Index rebuild threads (auto-scaled up to 8) |
| `--max-threads-for-post-actions` | 1 | Post-load threads |

**Total potential MySQL connections** = threads + schema_threads + index_threads (during overlap phases)

---

## How to use this file
- For quick lookups, search this file for the keyword (ARN, secret name, bucket name)
- For step-by-step actions, follow `docs/AWS-SETUP.md` (canonical), and use this KNOWLEDGE-POOL for fast facts
- When purging, move candidate files into `docs/archived/` with a short summary commit message (include `Purge:` tag)

---

If you'd like, I will:
- create `docs/archived/` and move purge candidates there (commit), or
- generate a machine-readable index (JSON) for quick programmatic lookups, or
- expand any category with deeper extracted facts (e.g., full IAM policy JSON snippets)

---

[← Back to Documentation Index](START-HERE.md) · [Deployment →](hca/widgets/deployment.md)
