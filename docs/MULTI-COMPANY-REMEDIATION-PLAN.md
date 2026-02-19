# Multi-Company Remediation Plan

> **Created:** 2026-02-19  
> **Status:** PLANNING  
> **Scope:** Address all remaining bugs, quality issues, missing functionality, tests, and documentation drift from the multi-company implementation audit.

---

## Audit Summary

The multi-company implementation (Phases 1–4) is functionally complete and builds successfully. A comprehensive code review identified **19 items** across 5 categories:

| Severity | Count | Description |
|----------|-------|-------------|
| **BLOCKER** | 2 | Release operations corrupt multi-company data; tracking table is single-company |
| **HIGH** | 3 | Can't clear fields to empty; schema migration drift; zero test coverage |
| **MEDIUM** | 5 | showConfirm signature; missing status check; delete loading state; dirty-state tracking; KNOWLEDGE-POOL drift |
| **LOW** | 9 | Model reuse; frontend validation; filter validation; select always-sends; error leaks; tab refresh; batch ops; escape key; API docs |

---

## Phase Plan

### Phase 5: Blockers & High-Severity Fixes

> **Priority:** MUST DO — these are data-safety and correctness issues.

#### 5A + 5B. Release & Tracking for Multi-Company Databases

##### The Problem (as originally reported)

Two related blockers were identified:

1. **5A — Release uses `WHERE database`**: `_release_restore()`, `_release_clear()`,
   and `_release_delete()` all operate via `WHERE database = %s`, which hits
   **every** overlord.companies row for a database.
2. **5B — Single-company tracking**: `previous_snapshot` stores one company
   row. `update_synced()` overwrites `company_id` / `current_dbhost` /
   `current_subdomain` with the last-synced company's values.

The initial plan proposed per-company-ID release operations and a full
multi-company snapshot. After deeper analysis, a **much simpler fix**
emerged.

##### Key Insight: Routing Is Shared, Edits Are Per-Company

All company rows for a database share the same physical MySQL server.
Their `dbHost` and `dbHostRead` values are identical — routing is a
**database-level** concern, not a company-level one. The per-company
differences (subdomain, name, branding, franchise) are identity/display
fields that users deliberately edit.

This means:
- **Clear routing** (`WHERE database`, set dbHost="") → already correct
  for multi-company. All companies need their routing cleared.
- **Delete all** (`WHERE database`, DELETE) → already correct. Removing
  the overlord presence for a database means removing all its companies.
- **Restore routing** is the *only* broken path — it currently restores
  subdomain and name via `WHERE database`, overwriting every company
  with the single snapshot's values.

##### What `tracking.company_id` Actually Does

Traced every usage:
- **`update_synced()`**: Stored via `COALESCE(%s, company_id)` — last-synced value.
- **API response** ([overlord.py L1114](pulldb/api/overlord.py#L1114)): Informational display only.
- **Release logic**: **Not referenced at all.** None of `_release_restore`,
  `_release_clear`, or `_release_delete` read `tracking.company_id`.
- **`verify_external_state()`**: Uses `get_by_database()`, not `get_by_id(tracking.company_id)`.

**`tracking.company_id` is advisory.** It carries no control-flow weight.
Orphaning it (by deleting that company row) is harmless.

##### Recommended Fix: Narrow + Expand

**The fix is two small, surgical changes — no architectural rework needed.**

**Change 1 — Narrow `_release_restore()` to routing-only fields:**

The current code restores `dbHost`, `dbHostRead`, `subdomain`, and `name`
via `WHERE database`. The subdomain/name restoration is:
- **Wrong for multi-company** (overwrites all companies with one snapshot's values)
- **Arguably wrong for single-company too** (if a user intentionally renamed
  the company or changed the subdomain during a staging session, they probably
  want that to persist — release should restore *routing*, not undo *edits*)

Fix: Remove `subdomain` and `name` from the restore data. Only restore
`dbHost` and `dbHostRead`. The `WHERE database = %s` path then correctly
restores routing for ALL companies in one statement.

```python
# BEFORE (restores 4 fields — breaks multi-company, arguably wrong for single too)
if "dbHost" in tracking.previous_snapshot:
    restore_data["dbHost"] = tracking.previous_snapshot["dbHost"] or ""
if "dbHostRead" in tracking.previous_snapshot:
    restore_data["dbHostRead"] = tracking.previous_snapshot["dbHostRead"] or ""
if "subdomain" in tracking.previous_snapshot:
    restore_data["subdomain"] = tracking.previous_snapshot["subdomain"] or ""
if "name" in tracking.previous_snapshot:
    restore_data["name"] = tracking.previous_snapshot["name"] or ""

# AFTER (routing-only — correct for single AND multi-company)
if "dbHost" in tracking.previous_snapshot:
    restore_data["dbHost"] = tracking.previous_snapshot["dbHost"] or ""
if "dbHostRead" in tracking.previous_snapshot:
    restore_data["dbHostRead"] = tracking.previous_snapshot["dbHostRead"] or ""
```

No change needed for `_release_clear()` or `_release_delete()`.

**Change 2 — Expand claim snapshot to all companies:**

Change `claim()` to call `get_all_by_database()` instead of
`get_row_snapshot()` and store the full list in `previous_snapshot`:

```python
# BEFORE
current = self._overlord_repo.get_row_snapshot(database_name)   # one row

# AFTER
all_companies = self._overlord_repo.get_all_by_database(database_name)
current = all_companies[0] if all_companies else None  # first for backward compat
# Store full list for audit trail
full_snapshot = {"companies": all_companies} if all_companies else None
```

Pass `full_snapshot` to `previous_snapshot` and extract individual fields
from `current` for `previous_dbhost`, `previous_dbhost_read`, `company_id`.

This doesn't change any logic — `_release_restore` only reads `dbHost`
and `dbHostRead` from the snapshot (which are the same across all companies).
The full list is stored for **audit/safety** so we have a complete record
of what existed before pullDB touched anything.

##### Why NOT Master/Alias Enforcement

We considered preventing deletion of the "master" company (the one stored
in `tracking.company_id`) until all "alias" companies are removed. After
analysis, this is **unnecessary coupling**:

1. `tracking.company_id` is advisory — no logic depends on it
2. Orphaning it is harmless — release doesn't use it
3. It would add a constraint that doesn't map to any real user workflow
4. If a user wants to delete a company, pullDB shouldn't second-guess the
   overlord schema's own constraints

##### Why NOT Per-Company-ID Release

We considered switching release to `update_by_id` / `delete_by_id`. This
is also unnecessary:

1. `_release_clear`: `WHERE database` is correct (clear all routing)
2. `_release_delete`: `WHERE database` is correct (delete all companies)
3. `_release_restore`: With routing-only restoration, `WHERE database` is
   correct (all companies shared the same original routing)

Per-company-ID release would only be needed if we restored non-routing
fields per-company. Since we're narrowing to routing-only, it's not needed.

##### Summary of Changes

| Component | Change | Scope |
|-----------|--------|-------|
| `_release_restore()` | Remove subdomain + name from restore_data | 4 lines removed |
| `claim()` | Call `get_all_by_database()`, store full list in snapshot | ~8 lines changed |
| `_release_clear()` | No change | — |
| `_release_delete()` | No change | — |
| `verify_external_state()` | No change | — |
| `update_synced()` | No change | — |
| `tracking.company_id` | No change (stays advisory) | — |
| Tracking schema | No change (unique per database is correct) | — |

**Total: ~12 lines of code changed. Zero architectural rework.**

##### Acceptance Criteria

- Release-restore on a 3-company database restores routing for all 3
  companies (dbHost, dbHostRead) without overwriting their individual
  subdomain/name/branding values
- Release-clear on a 3-company database clears routing for all 3 (as today)
- Release-delete on a 3-company database deletes all 3 (as today)
- Claim on a 3-company database stores all 3 in `previous_snapshot.companies`
- Single-company databases behave exactly as before
- `tracking.company_id` remains advisory — no enforcement
- User can delete any company (including the one in `tracking.company_id`)
  without blocking

---

#### 5C. `_collectCompanyFields()` empty field clearing (HIGH)

**Problem:** Clearing a field to empty string is impossible — falsy values are omitted from the payload, so the API preserves the old value. Once set, optional text fields can never be cleared through the UI.

**Files:** `pulldb/web/templates/partials/overlord_modal.html` (~L2400–2455)

**Fix:**
1. Change the collection pattern from `if (val) fields[key] = val` to always include the field: `fields[key] = val` (send empty string explicitly).
2. On the backend in `sync()`, change `if value is not None` to treat empty string as "set to empty" (not "skip").
3. Integer/select fields already always send — make the behavior consistent.

**Acceptance criteria:**
- User can clear admin email, company name, mascot, etc. to empty
- Empty fields are sent as `""` in the payload
- Backend writes empty string to the database

---

#### 5D. Schema migration file drift (HIGH)

**Problem:** Migration defines column as `user_code` but all Python code uses `created_by`. Migration cannot be re-run on a fresh database.

**File:** `schema/migrations/009_overlord_tracking.sql` (L17)

**Fix:** Rename `user_code` to `created_by` in the migration file. Also rename `INDEX idx_user (user_code)` to `INDEX idx_user (created_by)`. Verify the deployed column name matches.

**Acceptance criteria:**
- Migration creates column named `created_by`
- Python code and migration file are aligned
- Fresh database setup works end-to-end

---

### Phase 6: Medium-Severity Fixes

> **Priority:** SHOULD DO — usability and correctness issues.

#### 6A. `showConfirm()` signature mismatch

**Problem:** Calls pass a description string as the second argument, but `showConfirm(message, options={})` expects an options object. The description text is silently ignored.

**Files:** `overlord_modal.html` (~L2542, ~L2911)

**Fix:** Change calls to:
```javascript
await showConfirm('Delete company record #N?\n\nThis will permanently remove the record.', { title: 'Delete Company', type: 'danger' });
await showConfirm('Reset employee password?\n\nSetting a new password will...', { title: 'Reset Password', type: 'warning' });
```

---

#### 6B. `delete_company` endpoint missing job status check

**Problem:** `add_company` and `sync_overlord` verify job status is "deployed" or "expiring", but `delete_company` skips this check.

**File:** `pulldb/api/overlord.py` (~L673–710)

**Fix:** Add the same status guard:
```python
if job.status.value not in ("deployed", "expiring"):
    raise HTTPException(status_code=400, detail=f"Job is '{job.status.value}', must be 'deployed' or 'expiring'")
```

---

#### 6C. Loading state on `deleteCompanyRecord()`

**Problem:** Delete button remains clickable during the async request — allows double-clicks.

**File:** `overlord_modal.html` (deleteCompanyRecord function)

**Fix:** Disable button + show "Deleting..." text during the fetch, re-enable on completion/failure (same pattern as `saveCompanyCard()`).

---

#### 6D. Dirty-state tracking on edit card close

**Problem:** Closing the company edit card (Cancel / Back to List) silently discards all unsaved changes.

**File:** `overlord_modal.html` (closeCompanyEditCard function)

**Fix:**
1. Capture `_originalFields` when opening the edit card (snapshot of all field values).
2. On close, compare current values with `_originalFields`.
3. If dirty, prompt with `showConfirm('Discard unsaved changes?', { title: 'Unsaved Changes', type: 'warning' })`.

---

#### 6E. KNOWLEDGE-POOL.json update

**Problem:** New methods, endpoints, and response fields not documented.

**File:** `docs/KNOWLEDGE-POOL.json`

**Fix:** Add entries for:
- `get_all_by_database()`, `get_all_companies()`, `add_company()`, `remove_company()`
- `POST /{job_id}/company`, `DELETE /{job_id}/company/{company_id}`
- `companies` list in `OverlordStateResponse`
- `company_id` in `OverlordSyncRequest`

---

### Phase 7: Tests

> **Priority:** MUST DO — zero test coverage for multi-company code paths.

#### 7A. Unit tests — Repository layer

**File:** New: `tests/unit/infra/test_overlord_repository.py`

| Test | Description |
|------|-------------|
| `test_get_all_by_database_returns_multiple` | Multiple rows returned and ordered by companyID |
| `test_get_all_by_database_returns_empty` | No rows → empty list |
| `test_update_by_id_targets_single_row` | Only the PK-matched row is updated |
| `test_delete_by_id_targets_single_row` | Only the PK-matched row is deleted |

#### 7B. Unit tests — Manager layer

**File:** Extend `tests/unit/worker/test_overlord_manager.py`

| Test | Description |
|------|-------------|
| `test_get_all_companies` | Returns list from repository |
| `test_add_company_enforces_claim` | Raises OwnershipError without claim |
| `test_add_company_forces_database_field` | data["database"] always set to database_name |
| `test_remove_company_cross_database_check` | Rejects if company row belongs to different database |
| `test_remove_company_not_found` | Returns False for non-existent company_id |
| `test_sync_with_company_id` | Uses `update_by_id` path, not `update` |
| `test_release_restore_multi_company` | Restores each company from snapshot (after Phase 5B) |
| `test_release_delete_multi_company` | Deletes only tracked company (after Phase 5A) |
| `test_release_clear_multi_company` | Clears only tracked company (after Phase 5A) |

#### 7C. Integration tests — API layer

**File:** Extend `tests/integration/test_overlord_api.py`

| Test | Description |
|------|-------------|
| `test_get_returns_companies_list` | Response includes `companies` array |
| `test_post_company_creates_record` | POST `/company` returns 200 with new company_id |
| `test_post_company_requires_deployed_status` | POST `/company` returns 400 for non-deployed job |
| `test_delete_company_removes_record` | DELETE `/company/{id}` returns 200 |
| `test_delete_company_rejects_wrong_database` | DELETE returns 400 for cross-database company |
| `test_delete_company_requires_deployed_status` | DELETE returns 400 for non-deployed job (after 6B) |
| `test_sync_with_company_id_param` | POST `/sync` with company_id uses PK path |

---

### Phase 8: Low-Severity & Polish

> **Priority:** NICE TO HAVE — code quality and UX improvements.

| ID | Item | File | Effort |
|----|------|------|--------|
| 8A | Create `OverlordCompanyCreateRequest` model (remove `job_id` reuse) | `api/overlord.py` | Small |
| 8B | Frontend subdomain validation before submit | `overlord_modal.html` | Small |
| 8C | Validate filter columns against `_VALID_COLUMNS` | `infra/overlord.py` | Small |
| 8D | Consistent field sending (always send all fields or track dirty) | `overlord_modal.html` | Medium |
| 8E | Remove internal error details from 500 responses | `api/overlord.py` | Small |
| 8F | Refresh company table on tab switch-back | `overlord_modal.html` | Small |
| 8G | Escape key handler for modal/edit card close | `overlord_modal.html` | Small |
| 8H | Batch operations (future iteration) | Multiple | Large |
| 8I | API documentation for new endpoints | `docs/api/` | Small |

---

## Execution Order

```
Phase 5 (Blockers + High)     ──┐
  5D. Schema migration fix       │  Independent, quick
  5C. Empty field clearing        │  Independent, quick
  5AB. Release narrowing +        │  ~12 lines, the key fix
       claim snapshot expansion ──┘
                                  │
Phase 6 (Medium)               ──┤  Independent of Phase 5
  6A–6E all independent          │
                                  │
Phase 7 (Tests)                ──┘  Should be written AFTER Phase 5 fixes
  7A–7C                            (tests validate the fixed behavior)

Phase 8 (Low/Polish)           ──   Anytime, independent
```

**Recommended implementation order:**
1. `5D` → quick schema alignment fix
2. `5C` → quick frontend fix
3. `5AB` → narrow `_release_restore()` + expand claim snapshot (~12 lines)
4. `7A–7C` → tests for all new behavior
5. `6A–6E` → medium fixes
6. `8*` → polish items as time permits

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Release-restore overwrites non-routing fields (5AB) | **HIGH** — multi-company subdomain/name corruption on release | Narrow to routing-only fields; `WHERE database` then correctly handles all companies |
| Missing full snapshot on claim (5AB) | **LOW** — audit trail incomplete but no functional impact | Store all companies in snapshot for traceability |
| Schema migration drift (5D) | **MEDIUM** — fresh installs fail | Align column names immediately |
| Zero test coverage | **HIGH** — regressions go undetected | Write tests alongside Phase 5 fixes |

> **Risk downgrade note:** The original assessment rated 5A/5B as BLOCKER
> (CRITICAL). After analysis, `_release_clear` and `_release_delete` are
> already correct for multi-company. Only `_release_restore` has a real
> problem, and it's a focused fix (remove 2 field restores). Downgraded
> to HIGH.

---

## Files Modified/Created

| File | Phases | Type |
|------|--------|------|
| `pulldb/worker/overlord_manager.py` | 5A, 5B | Modify release methods + claim snapshot |
| `pulldb/infra/overlord.py` | 5A | Use PK-based methods in release path |
| `pulldb/web/templates/partials/overlord_modal.html` | 5C, 6A, 6C, 6D, 8B, 8D, 8F, 8G | Frontend fixes |
| `pulldb/api/overlord.py` | 6B, 8A, 8E | API fixes |
| `schema/migrations/009_overlord_tracking.sql` | 5D | Column rename |
| `docs/KNOWLEDGE-POOL.json` | 6E | Documentation update |
| `tests/unit/infra/test_overlord_repository.py` | 7A | New file |
| `tests/unit/worker/test_overlord_manager.py` | 7B | Extend |
| `tests/integration/test_overlord_api.py` | 7C | Extend |
