# Feature: Overlord Companies Integration

> **Feature Request ID**: `54166071-1c81-4f2b-a40a-b099d006ddef`  
> **Status**: ✅ Complete  
> **Requested By**: chrisb  
> **Votes**: 1  
> **Created**: 2026-01-26

---

## Summary

Allow users to update an external `overlord.companies` table when a job is Deployed. This enables pullDB to notify an external company routing system which database host contains a specific company's data.

**User Story**: As a pullDB user, I want to update overlord.companies with the database pulled and host from the dashboard OR from the dbpull history, so that the overlord system knows where to route company data requests.

---

## Overlord Schema (CONFIRMED)

**Host**: `db-mysql-db2-clone-dbmove-test-cluster.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com`  
**Database**: `overlord`  
**Table**: `companies`  
**User**: `dba` (dev clone) - production will use `pulldb_service`

### Table Structure

```sql
CREATE TABLE `companies` (
  `companyID` int NOT NULL AUTO_INCREMENT,
  `name` varchar(50) NOT NULL DEFAULT '',
  `database` varchar(50) NOT NULL,           -- ← Maps from job.target
  `dbServer` varchar(20) NOT NULL,
  `logo` varchar(50) NOT NULL,
  `branding` varchar(15) NOT NULL,
  `legacyBranding` tinyint(1) NOT NULL DEFAULT '0',
  `exclusiveDomain` varchar(50) NOT NULL,
  `order` int NOT NULL,
  `mascot` varchar(40) NOT NULL,
  `adminContact` varchar(40) NOT NULL,
  `adminPhone` varchar(10) NOT NULL,
  `adminEmail` varchar(80) NOT NULL,
  `billingEmail` varchar(100) NOT NULL,
  `billingName` varchar(30) NOT NULL,
  `sendTRInvoice` int NOT NULL,
  `subdomain` varchar(30) NOT NULL,
  `visible` int NOT NULL DEFAULT '1',
  `dbHost` varchar(253) NOT NULL,            -- ← Maps from job.dbhost
  `dbHostRead` varchar(253) NOT NULL,        -- ← Read replica (optional)
  `canFranchise` int NOT NULL DEFAULT '0',
  `franchiseName` varchar(50) NOT NULL DEFAULT '',
  `franchiseLogo` varchar(50) DEFAULT NULL,
  `blockPrtDate` date DEFAULT NULL,
  `dbHostDynamicRead` varchar(253) NOT NULL,
  `enableDynamicRead` int NOT NULL DEFAULT '0',
  `dbHostApiRead` varchar(253) DEFAULT NULL,
  PRIMARY KEY (`companyID`),
  KEY `idxcompanies_db` (`database`),
  KEY `idxcompanies_dbhost` (`dbHost`),
  KEY `idxcompanies_subdomain` (`subdomain`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
```

### Field Mapping (Job → Companies)

| Job Field | Companies Column | Notes |
|-----------|------------------|-------|
| `job.target` | `database` | Database name (indexed, lookup key) |
| `job.dbhost` | `dbHost` | Write host (indexed) |
| `job.dbhost` (ro) | `dbHostRead` | Read replica - derive from dbhost pattern |
| - | `name` | User must provide (company name) |
| - | Other fields | User editable, defaults to empty |

---

## Requirements

### Functional Requirements

1. **Action Button**: When a job is Deployed, show an action icon (🏢) on the Jobs page
2. **Modal Form**: Clicking the icon opens a popup form to manage the overlord company record
3. **Field Mapping**: Form pre-populates with data from the job (target → database, dbhost → host)
4. **Save**: User can edit and save the form back to `overlord.companies`
5. **Cleanup**: When a job database is removed, automatically delete the corresponding overlord row

### Non-Functional Requirements

1. **Security**: Only job owners (or admins) can manage overlord records
2. **SQL Safety**: All queries must use prepared statements
3. **Validation**: Check for SQL injection, validate all inputs
4. **Audit**: Log overlord changes (optional, TBD)

---

## Architecture

### HCA Layer Impact

| Layer | Directory | Changes |
|-------|-----------|---------|
| **shared** | `pulldb/infra/` | NEW: `overlord.py` - External DB connection |
| **entities** | `pulldb/domain/` | UPDATE: `settings.py` - Add overlord settings |
| **entities** | `pulldb/domain/` | NEW: `overlord_models.py` - Company data model |
| **features** | `pulldb/web/features/jobs/` | NEW: `overlord.py` - Modal routes |
| **features** | `pulldb/worker/` | UPDATE: `cleanup.py` - Add cleanup hook |
| **pages** | `pulldb/web/templates/` | NEW: `overlord_modal.html` |
| **pages** | `pulldb/web/templates/` | UPDATE: Job action buttons |

### System Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              User Flow                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Jobs Page              Modal Form                  Backend             │
│   (Deployed job)    →    (Edit companies)    →    (overlord.companies)  │
│        │                       │                        │                │
│   [🏢 icon]            ┌──────────────┐          ┌────────────┐         │
│        │               │ Company ID   │          │ Validate   │         │
│        └──────────────→│ Database     │─────────→│ Job exists │         │
│                        │ Host         │          │ Write row  │         │
│                        │ ...          │          └────────────┘         │
│                        └──────────────┘                                  │
│                                                                          │
│   Cleanup Flow (on job delete/supersede):                               │
│   Worker → Check if overlord row exists → Delete if present              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Configuration

### New Settings

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `overlord_enabled` | `PULLDB_OVERLORD_ENABLED` | `false` | Master toggle for integration |
| `overlord_dbhost` | `PULLDB_OVERLORD_DBHOST` | - | Overlord MySQL server hostname |
| `overlord_database` | `PULLDB_OVERLORD_DATABASE` | `overlord` | Database name on overlord server |
| `overlord_table` | `PULLDB_OVERLORD_TABLE` | `companies` | Table name for company records |
| `overlord_credential_ref` | `PULLDB_OVERLORD_CREDENTIAL_REF` | - | AWS Secrets Manager path |

### Credential Management

Credentials stored in AWS Secrets Manager using the same pattern as `db_hosts`:
```
aws-secretsmanager:/pulldb/overlord/credentials
```

Secret format:
```json
{
  "username": "pulldb_service",
  "password": "..."
}
```

---

## Security

### Authorization Rules

1. **Job Must Exist**: Cannot create overlord record without a valid job
2. **Job Must Be Deployed**: Only deployed jobs can have overlord records
3. **Owner Check**: Only job owner OR admin can manage the record
4. **Database Match**: Overlord record `database` field must match `job.target`

### SQL Injection Prevention

```python
# CORRECT - Parameterized query
cursor.execute(
    "INSERT INTO companies (database, dbhost) VALUES (%s, %s)",
    (job.target, job.dbhost)
)

# CORRECT - Escaped identifiers for dynamic table/column names
from pulldb.infra.mysql import escape_identifier
table = escape_identifier(settings.overlord_table)
cursor.execute(f"SELECT * FROM {table} WHERE database = %s", (database,))

# WRONG - Never do this
cursor.execute(f"INSERT INTO companies VALUES ('{user_input}')")  # SQL INJECTION!
```

---

## Implementation Plan

### Phase 1: Settings Infrastructure (1-2 days)

**Files to modify:**
- `pulldb/domain/settings.py` - Add `SettingCategory.OVERLORD` and 5 settings

**Tasks:**
1. Add `OVERLORD = "Overlord Integration"` to `SettingCategory` enum
2. Add 5 overlord settings to `SETTINGS_REGISTRY`
3. Add overlord section to Admin Settings UI
4. Test settings CRUD

### Phase 2: Connection Layer (1-2 days)

**Files to create:**
- `pulldb/infra/overlord.py` - `OverlordRepository` class
- `pulldb/domain/overlord_models.py` - `OverlordCompanyData` dataclass

**Tasks:**
1. Create `OverlordRepository` with methods:
   - `is_enabled() -> bool`
   - `get_company_by_database(database: str) -> dict | None`
   - `upsert_company(data: OverlordCompanyData) -> bool`
   - `delete_company_by_database(database: str) -> bool`
2. Add credential resolution using `CredentialResolver`
3. Write unit tests

### Phase 3: UI Components (2-3 days)

**Files to create:**
- `pulldb/web/features/jobs/overlord.py` - Routes
- `pulldb/web/templates/partials/overlord_modal.html` - Modal form

**Files to modify:**
- `pulldb/web/features/jobs/routes.py` - Include overlord routes
- `pulldb/web/templates/jobs/active.html` - Add action button

**Tasks:**
1. Create modal template with form fields
2. Add HTMX routes for GET (load form) and POST (save)
3. Add 🏢 icon button to deployed jobs in Active view
4. Implement form validation
5. Write integration tests

### Phase 4: Cleanup Integration (1 day)

**Files to modify:**
- `pulldb/worker/cleanup.py` - Add overlord cleanup hook

**Tasks:**
1. Add hook in `_drop_target_database_unsafe()` or job deletion flow
2. Check if overlord row exists for `job.target`
3. Delete if present (silent fail if not)
4. Test cleanup scenarios

### Phase 5: Testing & Documentation (1-2 days)

**Tasks:**
1. End-to-end test: deploy job → add overlord → delete job → verify cleanup
2. Update KNOWLEDGE-POOL.md with overlord documentation
3. Add help tooltips in UI

---

## Questions to Resolve

### Critical (Blocking)

| # | Question | Status | Answer |
|---|----------|--------|--------|
| 1 | What is the exact `overlord.companies` schema? | ✅ RESOLVED | 27 columns - see "Overlord Schema" section above |
| 2 | Where is the overlord DB hosted? | ✅ RESOLVED | `db-mysql-db2-clone-dbmove-test-cluster.cluster-*.rds.amazonaws.com` (dev clone) |
| 3 | What fields map from Job → Companies? | ✅ RESOLVED | `job.target` → `database`, `job.dbhost` → `dbHost`/`dbHostRead` |
| 4 | Credential path format? | ✅ RESOLVED | AWS Secrets: `pr-dev/overlord/credentials` (TBD prod path) |

### Design (Non-blocking)

| # | Question | Status | Answer |
|---|----------|--------|--------|
| 5 | Can users modify existing records or only create? | 📝 PROPOSED | Both - UPDATE if row exists, INSERT if not |
| 6 | What if multiple jobs exist for same target? | 📝 PROPOSED | Allow - each job manages its own row by `database` field |
| 7 | Should action appear in job history view? | 📝 PROPOSED | No - only Active/Deployed view for now |
| 8 | Should changes be logged to audit_logs? | 📝 PROPOSED | Yes - new `ACTION_TYPE.OVERLORD_UPDATE` |

---

## Estimated Effort

| Phase | Days | Complexity |
|-------|------|------------|
| 1. Settings Infrastructure | 1-2 | Low |
| 2. Connection Layer | 1-2 | Medium |
| 3. UI Components | 2-3 | Medium |
| 4. Cleanup Integration | 1 | Low |
| 5. Testing & Documentation | 1-2 | Low |
| **Total** | **6-10** | **Medium** |

---

## References

### Existing Patterns to Follow

| Pattern | Location | Use For |
|---------|----------|---------|
| External DB Connection | `pulldb/worker/staging.py:560-600` | Overlord connection |
| Settings CRUD | `pulldb/web/features/admin/routes.py:3171` | Settings POST |
| Modal Forms | `pulldb/web/templates/partials/confirm_modal.html` | Modal template |
| SQL Injection Prevention | `pulldb/infra/mysql.py` | Safe identifiers |
| Credential Resolution | `pulldb/infra/secrets.py:160-260` | AWS Secrets |
| Cleanup Hooks | `pulldb/worker/cleanup.py:500+` | Delete hook |

### Dev Guidance from Feature Request

> AI: you would need to build infrastructure for managing the {overlord_dbhost} in settings, the {overlord_database}: overlord, and the {overlord_table}: companies, {overlord_user}: pulldb_service, overlord password will be managed using the aws secrets process under hosts.
>
> Security markers for the table access, the database must be directly linked to an existing active job by the `database` field in the companies table and must not interact with any other tables in the overlord table.
>
> Goal: When the table is Deployed and only when it is deployed there will be an icon action added to the action column on the Jobs active page that brings up the popup that manages the overlord company record for this job ONLY!
>
> The overlord companies management form will popout a row management form that displays all the fields if they exist, if they don't then default to the mapped columns from what is in the jobs to the table fields for the companies table in that form. Once the user is done editing there will be an action button that saves this forms data back to the companies table.
>
> BEFORE saving make sure to validate all input and check for sql injection issues, all sql must use mysql prepare and execute instead of direct sql queries.
>
> When databases are removed check for the companies table row and remove the row if it exists based on the target database name record and database column in the companies table.

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-01-31 | AI Research | Initial research and planning document |
| 2026-01-31 | AI Research | Schema discovery complete - all critical questions resolved |
| 2026-01-31 | AI | Edge case handling for external changes implemented and tested |

---

## Update (2026-01-31)

✅ Edge case handling for external changes to `overlord.companies` implemented and tested. See [54166071-EDGE-CASES.md](54166071-EDGE-CASES.md) for details.
