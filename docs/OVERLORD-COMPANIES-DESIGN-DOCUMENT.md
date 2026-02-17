# Overlord Companies Management — Design Document

> **Feature Request ID**: `54166071-1c81-4f2b-a40a-b099d006ddef`  
> **Date**: 2026-02-13  
> **Status**: Phase 1 Complete — Expansion Planning  
> **Author**: Engineering Team

---

## 1. Purpose

This document captures the full lifecycle of the Overlord Companies Integration feature — from the original feature request through implementation to current status — and serves as the foundation for planning future updates and expanded capabilities.

---

## 2. Feature Overview

### 2.1 What It Does

pullDB manages database restore jobs. When a job is deployed, its target database must be registered in an external `overlord.companies` routing table so the overlord system knows which database host serves each company's data. This feature allows pullDB users and admins to manage those `overlord.companies` rows directly from pullDB's UI.

### 2.2 Why It Matters

- **Without this feature**: DBAs manually update `overlord.companies` after every pullDB deployment — error-prone, slow, and disconnected from the deployment workflow
- **With this feature**: Routing updates are part of the deployment lifecycle — claimed, synced, and released automatically alongside the job

### 2.3 Core Safety Principle

```
┌─────────────────────────────────────────────────────────────────────┐
│  pullDB MUST NOT CAUSE DATA LOSS IN THE OVERLORD DATABASE          │
│                                                                     │
│  overlord.companies is a PRODUCTION ROUTING TABLE.                 │
│  Incorrect writes break company access across the entire system.   │
│                                                                     │
│  Principle: "Track locally → Verify ownership → Backup first       │
│              → Operate safely → Log everything"                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Architecture

### 3.1 System Context

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              pullDB System                                 │
│                                                                            │
│  ┌──────────────┐    ┌──────────────────┐    ┌─────────────────────────┐  │
│  │  Jobs Page    │───▶│  Overlord Modal  │───▶│  /api/v1/overlord/     │  │
│  │  (User)       │    │  (User Panel)    │    │  (API Routes)          │  │
│  └──────────────┘    └──────────────────┘    └───────────┬─────────────┘  │
│                                                           │                │
│  ┌──────────────┐    ┌──────────────────┐                │                │
│  │  Admin Panel  │───▶│  Companies CRUD  │───▶────────────┤                │
│  │  (Admin)      │    │  (Admin Routes)  │               │                │
│  └──────────────┘    └──────────────────┘                │                │
│                                                           ▼                │
│                                              ┌─────────────────────────┐  │
│                                              │  OverlordManager        │  │
│                                              │  (Business Logic)       │  │
│                                              └───────┬────────┬────────┘  │
│                                                      │        │           │
│                       ┌──────────────────────────────┘        │           │
│                       ▼                                       ▼           │
│          ┌──────────────────────┐              ┌────────────────────┐     │
│          │  overlord_tracking   │              │  OverlordRepo      │     │
│          │  (Local MySQL)       │              │  (External MySQL)  │     │
│          │  pulldb_service DB   │              │  overlord DB       │     │
│          └──────────────────────┘              └────────────────────┘     │
└────────────────────────────────────────────────────────────────────────────┘
                                                         │
                                                         ▼
                                              ┌────────────────────┐
                                              │ overlord.companies │
                                              │ (External RDS)     │
                                              │ Production Routing │
                                              └────────────────────┘
```

### 3.2 HCA Layer Mapping

| HCA Layer | Directory | Component | Purpose |
|-----------|-----------|-----------|---------|
| **shared** | `pulldb/infra/overlord.py` | `OverlordConnection`, `OverlordRepository`, `OverlordTrackingRepository` | External DB connection, CRUD for both overlord.companies and local tracking |
| **entities** | `pulldb/domain/overlord.py` | `OverlordTracking`, `OverlordCompany`, error hierarchy | Data models and typed exceptions |
| **entities** | `pulldb/domain/services/overlord_provisioning.py` | `OverlordProvisioningService` | Admin provisioning workflow (user creation, credential storage) |
| **features** | `pulldb/worker/overlord_manager.py` | `OverlordManager` | Central orchestrator — claim, sync, release, cleanup |
| **features** | `pulldb/worker/cleanup.py` | `cleanup_overlord_on_job_delete()` | Hook into job deletion to auto-release overlord rows |
| **pages** | `pulldb/api/overlord.py` | REST API routes | User-facing endpoints: GET state, POST claim/sync/release |
| **pages** | `pulldb/web/features/admin/overlord_routes.py` | Admin web routes | Companies list, detail, CRUD, claim/release from admin panel |
| **pages** | `pulldb/cli/admin_commands.py` | CLI commands | `pulldb-admin overlord provision/test/deprovision` |

### 3.3 Database Architecture

**Two databases, strict separation:**

| Database | Owner | Table | Purpose |
|----------|-------|-------|---------|
| `overlord` (Remote RDS) | Overlord team | `companies` | Production routing — 27-column table mapping company databases to hosts |
| `pulldb_service` (Local) | pullDB | `overlord_tracking` | Ownership tracking, state machine, backups of original values |

**Constraint**: pullDB cannot alter `overlord.companies` schema. We track all state in our own `overlord_tracking` table.

### 3.4 State Machine

```
                  claim()                    sync()
    ┌──────────┐ ──────────▶ ┌──────────┐ ──────────▶ ┌──────────┐
    │          │             │ CLAIMED  │             │  SYNCED  │
    │  (none)  │             │          │◀────────────│          │
    │          │             │ Tracking │   (re-sync) │ Overlord │
    └──────────┘             │ created  │             │ updated  │
                             └──────────┘             └────┬─────┘
                                                          │
                                                  release()
                                                          │
                                                          ▼
                                                   ┌──────────┐
                                                   │ RELEASED │
                                                   │          │
                                                   │ Restore/ │
                                                   │ Clear/   │
                                                   │ Delete   │
                                                   └──────────┘
```

**Release strategies:**
- **RESTORE**: Puts back original `dbHost`/`dbHostRead` values (for rows that existed before pullDB)
- **CLEAR**: Blanks out host fields but keeps the row
- **DELETE**: Removes the row entirely (only for rows pullDB created)

---

## 4. Current Implementation Status

### 4.1 Completed Components

| Component | Status | Files | Description |
|-----------|--------|-------|-------------|
| **Domain Models** | ✅ Complete | `pulldb/domain/overlord.py` | `OverlordTracking`, `OverlordCompany`, full error hierarchy (6 exception classes) |
| **Infrastructure** | ✅ Complete | `pulldb/infra/overlord.py` (715 lines) | `OverlordConnection` (credential refresh, connection pooling), `OverlordRepository` (full CRUD + pagination + filtering), `OverlordTrackingRepository` |
| **Business Logic** | ✅ Complete | `pulldb/worker/overlord_manager.py` (694 lines) | `OverlordManager` — claim, sync, release, external drift detection, cleanup hooks |
| **Provisioning Service** | ✅ Complete | `pulldb/domain/services/overlord_provisioning.py` (1391 lines) | MySQL user creation, AWS Secrets Manager integration, credential rotation, deprovision |
| **User Modal** | ✅ Complete | `pulldb/web/templates/partials/overlord_modal.html` (547 lines) | Per-job overlord management — sync routing data, release with 3 strategies |
| **Admin List Page** | ✅ Complete | `pulldb/web/templates/features/admin/overlord_companies.html`, `admin-overlord-companies.js` | LazyTable with server-side pagination, stats bar (Total/Managed/Unmanaged), create modal, filtering |
| **Admin Detail Page** | ✅ Complete | `pulldb/web/templates/features/admin/overlord_company_detail.html`, `admin-overlord-company-detail.js` | 4-card editable layout (Identity, Routing, Branding, Contact), sidebar with management status, claim/release actions, danger zone |
| **Settings Panel** | ✅ Complete | `pulldb/web/templates/features/admin/partials/_overlord_setup.html` (1114 lines) | Provision wizard, test connection, rotate credentials, reconfigure, cleanup modal |
| **API Routes** | ✅ Complete | `pulldb/api/overlord.py` (395 lines) | 5 REST endpoints for user-facing modal operations |
| **Admin Routes** | ✅ Complete | `pulldb/web/features/admin/overlord_routes.py` (748 lines) | Companies list, detail, CRUD, claim/release |
| **CLI** | ✅ Complete | `pulldb/cli/admin_commands.py` | `pulldb-admin overlord provision/test/deprovision` |
| **Cleanup Hook** | ✅ Complete | `pulldb/worker/cleanup.py` | Auto-releases overlord row when job is deleted |
| **Schema** | ✅ Complete | `schema/migrations/009_overlord_tracking.sql`, `010_overlord_tracking_subdomain.sql` | Tracking table with state machine columns, backup fields, subdomain support |
| **Feature Flag** | ✅ Complete | `overlord_enabled` setting | Master toggle — UI hides all overlord UI when disabled |
| **Breadcrumbs** | ✅ Complete | `pulldb/web/widgets/breadcrumbs/__init__.py` | Admin navigation: Home > Admin > Companies > Detail |

### 4.2 Security Hardening (Completed via Audit)

All critical and high-priority security issues identified in the February 2026 audit have been resolved:

| Issue | Severity | Resolution |
|-------|----------|------------|
| SQL injection via column names | P0 Critical | ✅ Added `_VALID_COLUMNS` allowlist with `_validate_column_names()` |
| Table name injection | P1 High | ✅ Added `_VALID_TABLES` allowlist with `_validate_table_name()` |
| API job status not verified | P1 High | ✅ Jobs must be `deployed` or `expiring` to claim/sync |
| Release without status re-verification | P1 High | ✅ Added optimistic locking with `expected_job_id` |
| Error type conflation in API | P2 Medium | ✅ MySQL errors mapped to specific HTTP codes (503/403/500) |

### 4.3 Test Coverage

| Test File | Type | Coverage |
|-----------|------|----------|
| `tests/unit/worker/test_overlord_manager.py` | Unit | `OverlordManager` — claim, sync, release (incl. 10+ release edge cases), ownership, external drift |
| `tests/integration/test_overlord_api.py` | Integration | API routes — GET state, sync, release (with mocked manager) |
| `tests/qa/domain/test_overlord_models.py` | QA | Domain import verification, backward compat re-exports |
| `tests/qa/web/test_overlord_companies.py` | QA | Admin route helpers — text filtering, tracking enrichment |

### 4.4 Edge Case Handling

Comprehensive external change detection is implemented (see `54166071-EDGE-CASES.md`):

| Scenario | Status |
|----------|--------|
| Row deleted externally during release | ✅ Handled — graceful degradation per release action |
| dbHost changed externally | ✅ Handled — warning logged, proceed with user's chosen action |
| Row created externally for same database | ✅ Handled — backed up as `row_existed_before=true` |
| Row locked by external transaction | ✅ Handled — MySQL lock timeout |
| Overlord DB unreachable | ✅ Handled — connection timeout with clear error |

---

## 5. User Interfaces

### 5.1 User Panel — Job-Level Overlord Modal

**Access**: 🏢 icon on deployed jobs in the Active Jobs page  
**Purpose**: Per-job management of the associated `overlord.companies` row

**Fields displayed:**
| Field | Type | Source | Notes |
|-------|------|--------|-------|
| Database Name | Read-only | `job.target` | Auto-mapped, not editable |
| Subdomain | Editable (required) | User input | DNS-safe validation `[a-z0-9-]{1,30}`, live duplicate checking |
| Company Name | Editable (optional) | User input | — |
| Primary Host (dbHost) | Editable (required) | `job.dbhost` (auto-populated) | The write endpoint |
| Read Replica (dbHostRead) | Editable (optional) | User input | Read-only endpoint |
| Release Action | Dropdown | User selection | Restore / Clear / Delete — shown with original backup values |

**Workflow**: Open modal → auto-claims if not claimed → edit fields → Sync → data written to `overlord.companies`

### 5.2 Admin Panel — Companies List

**Access**: Admin > Companies (navigation menu)  
**Purpose**: Browse all `overlord.companies` rows with management status overlay

**Capabilities:**
- Server-side paginated LazyTable with column filtering (wildcard `*`/`?` support)
- Stats bar showing Total / Managed / Unmanaged counts
- Visual distinction: managed rows have blue left accent border, unmanaged rows are dimmed
- Create modal for new company entries
- Click-through to detail page

### 5.3 Admin Panel — Company Detail

**Access**: Click any row in the companies list  
**Purpose**: Full read/write management of a single `overlord.companies` row

**Layout**: Two-column — main content (4 editable cards) + sidebar (management status, quick actions, danger zone)

**Card structure:**
1. **Identity**: Company ID (static), Database (static), Company Code, Name, Owner, Visible
2. **Routing**: Subdomain, DB Host (Write), DB Host (Read), DB Server
3. **Branding**: Branding Prefix, Branding Logo
4. **Contact & Billing**: Admin Contact, Phone, Email, Billing Name, Billing Email

**Sidebar:**
- Management status badge (Managed/Claimed/Unmanaged)
- Linked job info, claimed-by user, timestamps
- Quick actions: Claim (with job dropdown) / Release (with strategy dropdown)
- Danger zone: Delete with double confirmation

**Access control**: Fields are editable only for claimed/managed companies. Unmanaged companies display read-only with a banner explaining they must be claimed first.

### 5.4 Admin Settings — Overlord Setup Panel

**Access**: Admin > Settings (Overlord Integration section)  
**Purpose**: One-time provisioning of the overlord database connection

**Capabilities:**
- **Provision**: Setup wizard accepting admin credentials → creates `pulldb_overlord` MySQL user → stores password in AWS Secrets Manager → saves connection config
- **Test Connection**: Verify stored credentials work
- **Rotate Credentials**: Generate new password, update Secrets Manager
- **Reconfigure**: Change host/database/table settings
- **Deprovision**: Drop user, clear settings, disable feature
- **Cleanup modal**: Handles host-change scenarios (releases all tracking records before reconfiguring)

---

## 6. Outstanding Issues & Technical Debt

### 6.1 From Audit — Tracked for Future Work

| ID | Issue | Severity | Effort | Description |
|----|-------|----------|--------|-------------|
| H2 | Non-atomic cross-database operations | High | Medium | `sync()` updates two databases without distributed transaction; failure between steps leaves inconsistent state |
| M3 | UI doesn't distinguish error types | Medium | Medium | Modal shows generic errors for "not configured" vs "connection error" vs "no permission" |
| M4 | Orphaned tracking records | Medium | Medium | No mechanism to clean up tracking when jobs are deleted outside normal flow |
| M5 | No rate limiting on API endpoints | Medium | Low | External DB could be flooded by buggy/malicious clients |
| M2 | Missing OverlordRepository unit tests | Medium | Medium | SQL building methods (`insert`, `update`, `delete`) untested |
| L4 | Documentation drift — schema fields | Low | Low | Docs reference field names that differ from code (`name` vs `company_name`) |

### 6.2 From Edge Cases — Phase 2 Items

| Item | Description |
|------|-------------|
| UI warning banner for external changes | Show alert when overlord row modified by external system |
| "Refresh State" button in modal | Let user re-read current overlord state before acting |
| Schema change graceful degradation | Handle column rename/removal without crashing |

---

## 7. Expansion Opportunities

### 7.1 Near-Term Enhancements (Low Effort, High Value)

#### 7.1.1 Idempotent Sync with Saga Pattern
**Problem**: `sync()` is not atomic across two databases.  
**Solution**: Introduce a `syncing` intermediate state, implement compensation on failure.

```
claimed → syncing → synced (success)
                  → claimed (rollback on failure)
```

This eliminates the inconsistency risk identified in H2 and makes retries safe.

#### 7.1.2 Structured Error Responses in User Modal
**Problem**: Users see generic "Failed to load overlord data" for all error types.  
**Solution**: Map API error codes to distinct UI states:
- **Not configured** → Info banner with admin contact link
- **Connection error** → Warning with retry button
- **Permission denied** → Error with explanation
- **No record yet** → Show create-mode form

#### 7.1.3 Orphan Detection & Cleanup
**Problem**: Tracking records can become orphaned if jobs are deleted outside normal flow.  
**Solution**: Periodic background scan joining `overlord_tracking` against `jobs` table, plus an admin-triggerable cleanup command.

```sql
SELECT t.* FROM overlord_tracking t
LEFT JOIN jobs j ON t.job_id = j.id
WHERE t.status IN ('claimed', 'synced') AND j.id IS NULL
```

#### 7.1.4 Rate Limiting
**Problem**: No protection against API spam to the external overlord database.  
**Solution**: Per-user rate limit on sync/release endpoints (e.g., 10 calls/minute).

### 7.2 Medium-Term Capabilities (Medium Effort)

#### 7.2.1 Bulk Operations in Admin Panel
**Current**: Companies must be managed one at a time.  
**Expansion**: Add multi-select checkboxes to the LazyTable with bulk actions:
- Bulk claim (auto-match by database name against deployed jobs)
- Bulk release (with consistent release strategy)
- Bulk update host fields (useful during host migrations)

#### 7.2.2 Auto-Sync on Job Deploy
**Current**: Users must manually open the modal and sync after deployment.  
**Expansion**: Option to automatically sync overlord when a job transitions to `deployed` status. This could be:
- A per-job toggle ("Auto-update overlord on deploy")
- A global setting ("Always auto-sync overlord")
- Triggered in the worker's post-deployment hook

**Safety consideration**: Auto-sync would still require a prior claim (first-time setup is manual), and would only update `dbHost`/`dbHostRead` from the job's values.

#### 7.2.3 Auto-Release on Job Expiry
**Current**: Cleanup hook fires on explicit job deletion.  
**Expansion**: Extend to fire when jobs expire or are superseded, ensuring the overlord row lifecycle is fully tied to the job lifecycle.

#### 7.2.4 Audit Log Viewer in Admin Panel
**Current**: Changes are logged to `audit_logs` but no UI to view them.  
**Expansion**: Add an "Audit History" tab/card to the company detail page showing all overlord-related audit events (claim, sync, release, external changes detected) with timestamps and users.

#### 7.2.5 Subdomain Conflict Resolution UI
**Current**: Duplicate subdomain detection shows a warning table.  
**Expansion**: Add resolution actions directly in the warning — reassign subdomain, navigate to conflicting record, or force-claim with acknowledgment.

### 7.3 Long-Term Vision (High Effort)

#### 7.3.1 Full Overlord Schema Management
**Current**: pullDB manages a subset of `overlord.companies` columns (database, dbHost, dbHostRead, subdomain, name, visible, and a few others).  
**Expansion**: Expose all 27 columns with proper field grouping, validation, and help text. The admin detail page already has 4 card groups (Identity, Routing, Branding, Contact) — extend to cover all fields with appropriate field types (text, number, boolean, date).

#### 7.3.2 Drift Detection Dashboard
**Current**: External changes are detected reactively during release operations.  
**Expansion**: Proactive drift monitoring:
- Periodic background comparison between `overlord_tracking.current_dbhost` and `overlord.companies.dbHost`
- Dashboard widget showing companies where external changes were detected
- Alert notifications (webhook, email) when tracked companies are modified externally

#### 7.3.3 Multi-Table Support
**Current**: Only `overlord.companies` is managed.  
**Expansion**: If the overlord system has other related tables (DNS routing, feature flags per company, etc.), the infrastructure could be extended to manage those relationships.

#### 7.3.4 Read Replica Management
**Current**: `dbHostRead` is a single text field.  
**Expansion**: Support for multiple read replicas, dynamic read routing (`dbHostDynamicRead`, `enableDynamicRead`, `dbHostApiRead`), with validation that read replicas are reachable.

#### 7.3.5 Integration Testing Against Live Overlord Clone
**Current**: Tests use mocked repositories.  
**Expansion**: CI pipeline spins up a clone of the overlord schema and runs full lifecycle tests (provision → claim → sync → external change → release → deprovision) against a real MySQL instance.

---

## 8. Data Flow Reference

### 8.1 User Sync Flow (Happy Path)

```
1. User clicks 🏢 on deployed job
2. Modal opens → GET /api/v1/overlord/{job_id}
3. API checks: overlord_enabled? → connection active? → job exists & deployed?
4. Returns: tracking state (if any) + current overlord.companies row (if any)
5. Modal pre-fills fields from job + existing overlord data
6. User edits fields, clicks "Sync"
7. POST /api/v1/overlord/{job_id}/sync
8. OverlordManager:
   a. verify_ownership(database_name) — job must be deployed with matching target
   b. claim() if not already claimed — creates tracking record, backs up existing row
   c. sync() — INSERT or UPDATE overlord.companies, update tracking to SYNCED
9. Returns success → modal shows confirmation
```

### 8.2 Job Deletion Cleanup Flow

```
1. Job deletion initiated (manual or expiry)
2. cleanup.py calls cleanup_overlord_on_job_delete(job_id)
3. OverlordManager.cleanup_on_job_delete(job_id):
   a. Find tracking by job_id
   b. If tracking exists and status is claimed/synced:
      - Check release_action preference (stored in tracking)
      - Execute release (RESTORE, CLEAR, or DELETE)
      - Mark tracking as RELEASED
4. Job deletion proceeds
```

### 8.3 Admin CRUD Flow

```
1. Admin navigates to Admin > Companies
2. GET /web/admin/overlord/companies → renders LazyTable
3. LazyTable fetches /web/admin/api/overlord/companies/paginated
4. Server: queries overlord.companies → enriches with tracking data → returns paginated results
5. Admin clicks row → GET /web/admin/overlord/companies/{id} → detail view
6. Admin edits fields → POST .../update → OverlordRepository.update_by_id()
7. Admin claims/releases via sidebar actions
```

---

## 9. Credential & Connection Architecture

### 9.1 Credential Chain

```
AWS Secrets Manager
    │
    ├── Secret: pr-dev/overlord/credentials
    │   └── { "username": "pulldb_overlord", "password": "..." }
    │
    ▼
OverlordConnection.from_settings()
    │
    ├── Reads overlord_dbhost, overlord_database, overlord_table from settings
    ├── Retrieves credentials from Secrets Manager via CredentialResolver
    └── Creates MySQL connection with timeout and retry
```

### 9.2 MySQL User Privileges

```sql
-- pulldb_overlord user (created by provisioning service)
GRANT SELECT, INSERT, UPDATE, DELETE ON overlord.companies TO 'pulldb_overlord'@'%';
-- No ALTER, CREATE, DROP, TRUNCATE — data operations only
```

---

## 10. Configuration Reference

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `overlord_enabled` | `PULLDB_OVERLORD_ENABLED` | `false` | Master feature toggle |
| `overlord_dbhost` | `PULLDB_OVERLORD_DBHOST` | — | Overlord MySQL hostname |
| `overlord_database` | `PULLDB_OVERLORD_DATABASE` | `overlord` | Database name |
| `overlord_table` | `PULLDB_OVERLORD_TABLE` | `companies` | Table name |
| `overlord_credential_ref` | `PULLDB_OVERLORD_CREDENTIAL_REF` | — | AWS Secrets Manager ARN |

---

## 11. Key Files Index

| File | Lines | Purpose |
|------|-------|---------|
| `pulldb/domain/overlord.py` | — | Data models, error hierarchy |
| `pulldb/domain/services/overlord_provisioning.py` | 1391 | Admin provisioning workflow |
| `pulldb/infra/overlord.py` | 715 | Connection management, repositories |
| `pulldb/worker/overlord_manager.py` | 694 | Business logic orchestrator |
| `pulldb/api/overlord.py` | 395 | User-facing REST API |
| `pulldb/web/features/admin/overlord_routes.py` | 748 | Admin CRUD routes |
| `pulldb/web/templates/partials/overlord_modal.html` | 547 | User modal template |
| `pulldb/web/templates/features/admin/overlord_companies.html` | — | Admin list page |
| `pulldb/web/templates/features/admin/overlord_company_detail.html` | — | Admin detail page |
| `pulldb/web/templates/features/admin/partials/_overlord_setup.html` | 1114 | Settings/provisioning panel |
| `pulldb/web/static/js/pages/admin-overlord-companies.js` | — | Admin list JS |
| `pulldb/web/static/js/pages/admin-overlord-company-detail.js` | — | Admin detail JS |
| `pulldb/worker/cleanup.py` | 3200+ | Job cleanup (overlord hook at ~line 3120) |
| `pulldb/cli/admin_commands.py` | — | CLI: provision/test/deprovision |
| `schema/migrations/009_overlord_tracking.sql` | 46 | Tracking table schema |
| `schema/migrations/010_overlord_tracking_subdomain.sql` | — | Subdomain column migration |
| `tests/unit/worker/test_overlord_manager.py` | 638 | Unit tests |
| `tests/integration/test_overlord_api.py` | 297 | API integration tests |
| `tests/qa/domain/test_overlord_models.py` | — | Domain QA tests |
| `tests/qa/web/test_overlord_companies.py` | — | Admin route QA tests |

---

## 12. Related Documents

| Document | Purpose |
|----------|---------|
| [54166071-overlord-companies.md](feature-requests/54166071-overlord-companies.md) | Original feature specification |
| [54166071-IMPLEMENTATION-VISION.md](feature-requests/54166071-IMPLEMENTATION-VISION.md) | Engineering vision & safety plan |
| [54166071-EDGE-CASES.md](feature-requests/54166071-EDGE-CASES.md) | External change edge case analysis |
| [OVERLORD-AUDIT-2026-02-01.md](OVERLORD-AUDIT-2026-02-01.md) | Security audit report (fixes applied) |
| [OVERLORD-AUDIT-FINDINGS.md](OVERLORD-AUDIT-FINDINGS.md) | Detailed audit findings (684 lines) |

---

## 13. Recommended Next Steps

### Priority Order for Expansion

| Priority | Enhancement | Effort | Value | Rationale |
|----------|-------------|--------|-------|-----------|
| **1** | Idempotent sync (saga pattern) | Medium | High | Eliminates the most significant remaining technical risk (H2) |
| **2** | Structured error responses in modal | Low | High | Direct UX improvement — users can self-diagnose issues |
| **3** | Orphan detection & cleanup | Medium | High | Prevents state drift as system scales |
| **4** | Rate limiting | Low | Medium | Protects external production database |
| **5** | OverlordRepository unit tests | Medium | Medium | Fills the most significant test gap |
| **6** | Auto-sync on deploy | Medium | High | Biggest workflow improvement — eliminates manual step |
| **7** | Bulk operations in admin | Medium | Medium | Admin efficiency for large-scale operations |
| **8** | Audit log viewer | Low | Medium | Visibility into change history |
| **9** | Drift detection dashboard | High | Medium | Proactive monitoring vs. reactive detection |
| **10** | Full schema management | High | Low | Diminishing returns — most columns are rarely changed |

---

*End of Design Document*
