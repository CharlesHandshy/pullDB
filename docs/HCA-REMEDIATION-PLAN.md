# HCA Remediation Plan

> **Created:** 2026-02-11
> **Audited:** 2026-02-11 (3 passes)
> **Context:** Post-audit of HCA enqueue extraction + Overlord Companies feature
> **Status:** Complete
> **Scope:** ~20 files touched, ~5 new test files, 1 new CI rule, net -700 lines in admin/routes.py

### HCA Layer Reference (highest → lowest)

```
plugins   → pulldb/binaries/          (highest — can import all below)
pages     → pulldb/cli/, web/, api/
widgets   → pulldb/worker/service.py
features  → pulldb/worker/*.py
entities  → pulldb/domain/
shared    → pulldb/infra/              (lowest — can only import shared)
```

**Import rule:** A layer may only import from the **same or lower** layers.

**Dependency Inversion exception:** The codebase uses an established Dependency Inversion Pattern (DIP) where `infra` (shared) imports Protocol definitions, models, and errors from `domain` (entities). There are **12 existing infra→domain imports** today (`Config`, `CommandResult`, `MySQLCredentials`, `LockedUserError`, domain models, interfaces, etc.). This is standard DDD practice — the infrastructure layer implements domain-defined contracts. Phases 4 and 5 follow this established pattern.

---

## Dependency Graph

```
Phase 1 (quick wins) [S] ─────────────────────────────┐
    │                                                   │
Phase 2 (extract routes) [M] ── depends on 1a          │
    │                                                   │
Phase 3 (error subclasses) [L] ── parallel with 2      │
    │                                                   │
Phase 4 (overlord model reloc) [M] ── parallel with 3  │
    │                                                   │
Phase 5 (repo protocol) [M] ── depends on 3            │
    │                                                   │
Phase 6 (perf) [M] ── depends on 2, 4                  │
    │                                                   │
Phase 7 (tests) [L] ── depends on 2-6                  │
    │                                                   │
Phase 8 (docs & compliance) [S] ── after all code      │
    │                                                   │
Phase 9 (CI layer enforcement) [S] ── final ───────────┘
```

**Parallel tracks:**
- Track A: Phase 1 → 2 (route extraction)
- Track B: Phase 3 → 5 (error model + repo protocol)
- Track C: Phase 4 (overlord model relocation, parallel with Track B)
- **Convergence:** Phase 6 (perf) starts after both Track A and Track C complete
- Sequential: Phase 7 → 8 → 9 (tests, docs, CI gate)

**Effort estimates:** S = half-day, M = 1 day, L = 2-3 days. Total: ~8-10 focused days.

---

## Phase 1 — Quick Wins (no behavior changes, low risk) [S]

### 1a. Fix private attribute access in `_get_overlord_repos` and provisioning handler

- Add public `@property` accessors to `OverlordManager` for `overlord_repo`, `tracking_repo`, and `overlord_conn`
- Update `_get_overlord_repos` (line ~6630) which uses `getattr(overlord_manager, "_overlord_repo", None)` etc.
- Also update the provisioning handler (lines ~6186-6189) which directly writes `overlord_manager._overlord_conn`, `overlord_manager._overlord_repo` — these need public setter methods or a `provision(conn, repo)` method on `OverlordManager`
- Confirm the import direction is legal: `pages` (`web/features/admin/`) → `features` (`worker/overlord_manager.py`) is **downward** — OK
- **Files:** `pulldb/worker/overlord_manager.py`, `pulldb/web/features/admin/routes.py`

### 1b. Add consistent SQL validation to new overlord repository methods

- Add `_validate_table_name(self._table)` calls to `get_all()`, `get_by_id()`, `update_by_id()`, `delete_by_id()` to match the pattern used by existing methods
- **File:** `pulldb/infra/overlord.py`

### 1c. Verify `MAX_TARGET_LENGTH` is explicitly defined

- Confirm `domain/naming.py` has `MAX_TARGET_LENGTH = MAX_DATABASE_NAME_LENGTH - STAGING_SUFFIX_LENGTH` as a module-level assignment (not just in `__all__`)
- **File:** `pulldb/domain/naming.py`

### 1d. Add `domain/services/__init__.py` public re-exports

- Export `enqueue_job`, `EnqueueResult`, `TargetResult`, `EnqueueDeps` from the package `__init__.py`
- **File:** `pulldb/domain/services/__init__.py`

**Done when:**
- [x] All 4 items committed and passing `pytest`
- [x] `python -m pulldb.audit --drift --severity high` clean
- [x] No new lint warnings

---

## Phase 2 — Extract Overlord Routes (structural, moderate risk) [M]

### 2a. Create `pulldb/web/features/admin/overlord_routes.py`

- Move the Overlord Companies CRUD block from admin/routes.py (lines ~6615-7320, ~705 lines): `_get_overlord_repos`, `_text_filter_match`, `_enrich_companies_with_tracking`, and all **9** Companies route handlers:
  1. `GET /overlord/companies` (page view)
  2. `GET /api/overlord/companies/paginated`
  3. `GET /api/overlord/companies/paginated/distinct`
  4. `GET /overlord/companies/{company_id}` (detail)
  5. `POST /api/overlord/companies/create`
  6. `POST /api/overlord/companies/{company_id}/update`
  7. `POST /api/overlord/companies/{company_id}/delete`
  8. `POST /api/overlord/companies/{company_id}/claim`
  9. `POST /api/overlord/companies/{company_id}/release`
- New file gets its own `router = APIRouter(prefix="/web/admin", tags=["web-admin-overlord"])`
- **Target:** `admin/routes.py` drops from ~7,320 lines to ~6,615 lines
- **Out of scope:** The 7 overlord provisioning routes (lines ~6077-6615, ~538 lines: provision, test, check-host-change, cleanup-old-host, rotate, refresh-credentials, deprovision) remain in `admin/routes.py` for now. These are tightly coupled to the admin provisioning UI and can be extracted in a follow-up
- **File:** new `pulldb/web/features/admin/overlord_routes.py`

### 2b. Register the sub-router in the router registry

- Register in `pulldb/web/router_registry.py` alongside the existing `admin_router` include
- Add `from pulldb.web.features.admin.overlord_routes import router as admin_overlord_router` and `main_router.include_router(admin_overlord_router)` after the existing admin router line
- Do **not** daisy-chain through `admin/routes.py` — sub-routers register at the registry level
- **File:** `pulldb/web/router_registry.py`

### 2c. Verify no circular imports

- Run import check after extraction: `python -c "from pulldb.web.features.admin.overlord_routes import router"`
- `_get_overlord_repos` helper shared between overlord routes only — stays in the new file

**Done when:**
- [x] `admin/routes.py` is ≤ 6,650 lines (provisioning routes remain)
- [x] `overlord_routes.py` is ≥ 650 lines (Companies CRUD block)
- [x] All overlord UI endpoints respond identically (manual smoke test)
- [x] `pytest` green, `python -m pulldb.audit --drift --severity high` clean

---

## Phase 3 — Domain Error Model (behavioral, needs careful migration) [L]

### 3a. Create domain error subclasses

Define in `pulldb/domain/errors.py`:

```python
class EnqueueError(Exception):              # base — NO status_code attribute
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)

class JobNotFoundError(EnqueueError): ...        # was status_code=404
class UserDisabledError(EnqueueError): ...       # was status_code=403
class HostUnauthorizedError(EnqueueError): ...   # was status_code=403
class DuplicateJobError(EnqueueError): ...       # was status_code=409
class DatabaseProtectionError(EnqueueError): ... # was status_code=409 (external DB)
class JobLockedError(EnqueueError): ...          # was status_code=409 (locked)
class RateLimitError(EnqueueError): ...          # was status_code=429
class EnqueueBackupNotFoundError(EnqueueError): ... # was status_code=404 (distinct from BackupDiscoveryError which is a worker-phase failure)
class EnqueueValidationError(EnqueueError): ...  # was status_code=400
class HostUnavailableError(EnqueueError): ...    # was status_code=503
```

- **Remove `status_code` from base `EnqueueError` entirely** — all three consumer sites (api/logic.py, restore/routes.py, jobs/routes.py) are updated in 3c below within the same phase, so there is no backward-compat window that requires a deprecation period
- **File:** `pulldb/domain/errors.py`

### 3b. Update `domain/services/enqueue.py` to raise specific subclasses

- Replace all **28** `raise EnqueueError(status_code, ...)` sites with the appropriate typed subclass
- Each subclass constructor takes only `detail: str` (no status code)
- Mapping requires classifying each of the 28 raise sites by their current status code → subclass
- Confirm `enqueue.py` imports stay within HCA bounds: entities → shared is legal (downward)
- **File:** `pulldb/domain/services/enqueue.py`

### 3c. Update the three pages-layer error handlers

`pulldb/api/logic.py` — `_wrap_enqueue_error` maps subclass → HTTP status code:

```python
_ERROR_STATUS_MAP: dict[type[EnqueueError], int] = {
    EnqueueValidationError: 400,
    HostUnauthorizedError: 403,
    UserDisabledError: 403,
    JobNotFoundError: 404,
    EnqueueBackupNotFoundError: 404,
    DuplicateJobError: 409,
    DatabaseProtectionError: 409,
    JobLockedError: 409,
    RateLimitError: 429,
    HostUnavailableError: 503,
}
```

- `pulldb/web/features/restore/routes.py` — same mapping for template error rendering
- `pulldb/web/features/jobs/routes.py` — same for resubmit handler
- **Files:** 3 files above

### 3d. Update tests

- `tests/qa/test_custom_target.py` — `pytest.raises(EnqueueError)` → `pytest.raises(HostUnavailableError)` etc.
- Verify all existing tests still pass with the subclass changes (subclasses are `isinstance` compatible with `EnqueueError`)
- Add negative/error-path tests verifying each subclass is raised by `enqueue.py` under the correct condition (e.g., `DuplicateJobError` for existing job, `UserDisabledError` for disabled user)
- **Files:** `tests/qa/test_custom_target.py`, `tests/qa/api/test_jobs.py`

**Done when:**
- [x] `status_code` attribute deleted from `EnqueueError` base class
- [x] `grep -rn "raise EnqueueError(" pulldb/` returns zero hits (all raise sites use subclasses)
- [x] All 3 consumer error handlers use `_ERROR_STATUS_MAP` lookup
- [x] `pytest` green, `python -m pulldb.audit --drift --severity high` clean

---

## Phase 4 — Relocate Overlord Domain Models (HCA violation fix) [M]

> **Why:** `OverlordTracking`, `OverlordCompany`, `OverlordTrackingStatus`, and the `OverlordError` hierarchy are currently defined in `pulldb/infra/overlord.py` (shared layer). These are entity-level concepts that belong in `pulldb/domain/`. Moving them establishes the correct semantic ownership.
>
> **HCA note:** After relocation, `pulldb/infra/overlord.py` will import these models from `pulldb/domain/overlord.py`. This is shared→entities (upward), but follows the project's **established Dependency Inversion Pattern** — 12 existing infra→domain imports already use this pattern for `Config`, `CommandResult`, `MySQLCredentials`, interfaces, etc.

### 4a. Create `pulldb/domain/overlord.py`

Move from `pulldb/infra/overlord.py` to `pulldb/domain/overlord.py`:

- `OverlordTrackingStatus` enum
- `OverlordTracking` dataclass
- `OverlordCompany` dataclass (including `from_row()` factory)
- `OverlordError` and all subclasses: `OverlordConnectionError`, `OverlordOwnershipError`, `OverlordAlreadyClaimedError`, `OverlordSafetyError`, `OverlordExternalChangeError`, `OverlordRowDeletedError`

- **File:** new `pulldb/domain/overlord.py`

### 4b. Update `pulldb/infra/overlord.py` imports

- Replace local definitions with `from pulldb.domain.overlord import ...`
- This is shared→entities (upward by strict HCA), but follows the established **Dependency Inversion Pattern** used throughout the codebase (see header note)
- **File:** `pulldb/infra/overlord.py`

### 4c. Update all consumers (4 files, 6 import sites)

| File | What changes |
|------|--------------|
| `pulldb/worker/overlord_manager.py` (line ~23) | Block import → `pulldb.domain.overlord` |
| `pulldb/web/features/admin/routes.py` (lines ~6178, ~6188, ~6497) | 3 lazy imports → `pulldb.domain.overlord` (or `overlord_routes.py` if Phase 2 done) |
| `pulldb/api/overlord.py` (line ~18) | Error classes → `pulldb.domain.overlord` |
| `pulldb/api/main.py` (line ~225) | `OverlordConnection` stays in `pulldb.infra.overlord` (it's an infra concern — connection management) |

- **Note:** `OverlordConnection` and `OverlordRepository` remain in `pulldb/infra/overlord.py` — they are infrastructure implementations, not domain entities
- **Files:** 4 files above

### 4d. Add re-exports to `pulldb/domain/__init__.py`

- Export the public symbols from `pulldb/domain/overlord.py` so consumers can use `from pulldb.domain import OverlordCompany` etc.
- **File:** `pulldb/domain/__init__.py`

**Done when:**
- [x] `grep -rn "class Overlord" pulldb/infra/overlord.py` returns zero hits (all moved)
- [x] `grep -rn "from pulldb.infra.overlord import.*Overlord" pulldb/` — only `pulldb/infra/overlord.py` itself has these imports (re-importing from domain)
- [x] `pytest` green, `python -m pulldb.audit --drift --severity high` clean

---

## Phase 5 — Move DB Checks to Repository Protocol (structural) [M]

### 5a. Add methods to `HostRepository` interface

In `pulldb/domain/interfaces.py`, add:

```python
def database_exists(self, hostname: str, db_name: str) -> bool: ...
def get_pulldb_metadata_owner(self, hostname: str, db_name: str) -> tuple[bool, str | None, str | None]: ...
```

- **File:** `pulldb/domain/interfaces.py`

### 5b. Implement in `pulldb/infra/mysql.py` (HostRepository at line ~4895)

- Move the raw `mysql.connector.connect()` logic from `enqueue.py` into the existing `HostRepository` class
- Two functions to move: `_target_database_exists_on_host()` (lines ~157-180) and `_get_pulldb_metadata_owner()` (lines ~199-230)
- Both use lazy `import mysql.connector` — move to class-level import in `mysql.py` where it's already imported
- Follows established DIP: infra implements domain-defined interface (shared→entities pattern, 12 existing precedents)
- **File:** `pulldb/infra/mysql.py`

### 5c. Simplify `enqueue.py` callers

- Replace `_target_database_exists_on_host(state, target, dbhost)` with `state.host_repo.database_exists(dbhost, target)`
- Replace `_get_pulldb_metadata_owner(state, target, dbhost)` with `state.host_repo.get_pulldb_metadata_owner(dbhost, target)`
- Remove the two private functions from `enqueue.py`
- **File:** `pulldb/domain/services/enqueue.py`

### 5d. Update tests

- Test patches for `_target_database_exists_on_host` change to mocking `state.host_repo.database_exists`
- This actually simplifies the tests — mock the repo method directly instead of patching a private function
- **Files:** `tests/qa/api/test_jobs.py`, `tests/qa/test_custom_target.py`

**Done when:**
- [x] `grep -rn "mysql.connector" pulldb/domain/` returns zero hits (no raw MySQL in domain layer)
- [x] `_target_database_exists_on_host` and `_get_pulldb_metadata_owner` deleted from `enqueue.py`
- [x] `pytest` green, `python -m pulldb.audit --drift --severity high` clean

---

## Phase 6 — Overlord Companies Performance [M]

### 6a. Add SQL-side filtering/pagination to `OverlordRepository`

- Add `get_paginated(filters, sort, offset, limit) -> tuple[list[dict], int]` method
- Keep `get_all()` for enrichment/stats scenarios but add request-scoped caching via a FastAPI dependency (not global TTL cache — avoids stale data across requests)
- **File:** `pulldb/infra/overlord.py`

### 6b. Reduce triple-scan in paginated endpoint

- Stats, filtering, and distinct values currently each call `get_all()` independently
- Use request-scoped cache: inject a `CachedOverlordData` dependency that calls `get_all()` once per request and provides `.stats`, `.filtered()`, `.distinct_values()` views
- Add the caching dependency to the existing `pulldb/web/dependencies.py` module (it's a single file, not a package)
- **Files:** `pulldb/web/features/admin/overlord_routes.py` (post Phase 2 extraction), `pulldb/web/dependencies.py`

### 6c. Address orphaned tracking records (Overlord Audit M4)

- Add a periodic cleanup task or a cleanup-on-access check that removes tracking records for companies no longer present in the remote overlord database
- **File:** `pulldb/worker/overlord_manager.py` or new `pulldb/worker/overlord_cleanup.py`

**Done when:**
- [x] Paginated endpoint makes ≤ 2 SQL queries (data + count) instead of 3x `get_all()`
- [x] Orphan cleanup mechanism exists and is tested
- [x] `pytest` green

---

## Phase 7 — Test Coverage [L]

### 7a. Tests for `api/logic.py` wrapper

- Test `EnqueueResult` → `JobResponse` mapping
- Test `_wrap_enqueue_error` converts `EnqueueError` subclasses → correct `HTTPException` status codes
- Test that **every** subclass in `_ERROR_STATUS_MAP` is exercised (one parametrized test)
- **File:** new `tests/qa/api/test_logic_wrapper.py`

### 7b. Tests for Overlord Companies routes

- Paginated endpoint: filter, sort, pagination
- `_text_filter_match` with wildcards
- `_enrich_companies_with_tracking` enrichment logic
- CRUD endpoints: create, update, delete with ownership checks
- Claim/release flow
- Addresses Overlord Audit **M2** (missing tests for `OverlordRepository` SQL methods)
- **File:** new `tests/qa/web/test_overlord_companies.py`

### 7c. Tests for new `HostRepository` methods (from Phase 5)

- `database_exists` with mock MySQL connection
- `get_pulldb_metadata_owner` with various table states (no table, empty table, matching/non-matching owner)
- **File:** existing host repo test file or new `tests/qa/infra/test_host_repo.py`

### 7d. Tests for overlord model relocation (from Phase 4)

- Verify `from pulldb.domain.overlord import OverlordCompany, OverlordTracking` works
- Verify `from pulldb.infra.overlord import OverlordRepository` still works (backward compat)
- **File:** new `tests/qa/domain/test_overlord_models.py`

### 7e. Error path coverage for enqueue subclasses (from Phase 3)

- Parametrized test: for each subclass, set up the trigger condition in `enqueue.py` and verify the correct exception type is raised
- Verify `isinstance(subclass_instance, EnqueueError)` holds for all subclasses
- **File:** `tests/qa/api/test_jobs.py` (extend existing)

**Done when:**
- [x] All new test files pass
- [x] `pytest --cov pulldb/domain/services/enqueue.py` shows coverage increase
- [x] Overlord Audit M2 can be marked FIXED

---

## Phase 8 — Documentation & Compliance [S]

### 8a. Update KNOWLEDGE-POOL.json

- Add entries for: `pulldb/domain/schemas.py`, `pulldb/domain/services/enqueue.py`, `pulldb/web/features/admin/overlord_routes.py`, `pulldb/domain/overlord.py`
- Update `pulldb/api/logic.py` entry to reflect thin-wrapper status
- Remove/update any entries referencing overlord models in `pulldb/infra/overlord.py`

### 8b. Update WORKSPACE-INDEX

- Reflect moved symbols, new files, new exports

### 8c. Run drift detection

```bash
python -m pulldb.audit --drift --severity high
python -m pulldb.audit --full
```

### 8d. Session log entry

- Append to `.pulldb/SESSION-LOG.md` summarizing the HCA remediation work

### 8e. Evaluate removing `api/logic.py` wrapper entirely

- After Phase 3 (error subclasses), the wrapper is just a `try/except` mapping
- Consider an `@handle_enqueue_errors` decorator on the API routes instead
- API routes would call domain functions directly
- This is optional but reduces indirection

**Done when:**
- [x] `python -m pulldb.audit --drift` returns zero high/critical alerts
- [x] KNOWLEDGE-POOL.json reflects all new/moved files
- [x] SESSION-LOG.md entry committed

---

## Phase 9 — CI Layer Enforcement [S]

> **Why:** Without automated enforcement, HCA violations will silently re-accumulate. This phase prevents regression.

### 9a. Add import-linter configuration

Install [`import-linter`](https://github.com/seddonym/import-linter) and configure layer contracts:

```toml
# pyproject.toml
[tool.importlinter]
root_packages = ["pulldb"]

[[tool.importlinter.contracts]]
name = "HCA Layer Isolation"
type = "layers"
layers = [
    "pulldb.cli",
    "pulldb.web",
    "pulldb.worker.service",
    "pulldb.worker",
    "pulldb.domain",
    "pulldb.infra",
]
```

> **Why not `|` grouping?** `pulldb.web` imports from `pulldb.api` (router_registry.py imports `create_overlord_router` from `pulldb.api.overlord`). The `|` separator in import-linter prohibits sibling imports. Until the web→api dependency is resolved, keep them as separate layers. `pulldb.api` is excluded from the contract for now since it serves as a shared router factory consumed by web.

> **Known DIP exceptions:** import-linter's `layers` contract will flag infra→domain imports (12 existing sites). Use `ignore_imports` to whitelist the established Dependency Inversion Pattern:

```toml
[[tool.importlinter.contracts]]
name = "HCA Layer Isolation"
type = "layers"
layers = [
    "pulldb.cli",
    "pulldb.web",
    "pulldb.worker.service",
    "pulldb.worker",
    "pulldb.domain",
    "pulldb.infra",
]
ignore_imports = [
    "pulldb.infra.* -> pulldb.domain.interfaces",
    "pulldb.infra.* -> pulldb.domain.models",
    "pulldb.infra.* -> pulldb.domain.errors",
    "pulldb.infra.* -> pulldb.domain.config",
    "pulldb.infra.* -> pulldb.domain.overlord",
    "pulldb.infra.* -> pulldb.domain.validation",
    "pulldb.infra.* -> pulldb.domain.color_schemas",
    "pulldb.infra.* -> pulldb.domain.services.provisioning",
]
```

- **File:** `pyproject.toml`

### 9b. Add to pre-commit hooks

- Add `lint-imports` as a pre-commit check
- **File:** `.pre-commit-config.yaml` or `Makefile` lint target

### 9c. Add to CI pipeline

- Run `lint-imports` in the same CI job as `pytest` / `ruff`
- **File:** CI config (GitHub Actions or equivalent)

**Done when:**
- [x] `lint-imports` passes on current codebase (with DIP ignore list)
- [x] A deliberate HCA violation (e.g., `domain/` importing from `web/`) fails the check
- [x] Pre-commit hook runs `lint-imports` on every commit
- [x] DIP exceptions are documented in `pyproject.toml` comments

---

## Overlord Audit Tracker

Items from `docs/OVERLORD-AUDIT-FINDINGS.md` addressed by this plan:

| Audit ID | Issue | Phase | Status |
|----------|-------|-------|--------|
| M2 | Missing tests for `OverlordRepository` SQL methods | 7b | Complete |
| M4 | Orphaned tracking records not cleaned up | 6c | Complete |
| L2 | Missing type hints in helper functions | 2a (during extraction) | Complete |
| L4 | Documentation drift - schema fields | 8c | Complete |

---

## Known Issues & Decisions

### Dependency Inversion Pattern (DIP) vs. strict HCA

Strict HCA says shared (infra) cannot import from entities (domain). However, the codebase has **12 established infra→domain imports** for implementing domain-defined protocols, using domain models as return types, and raising domain errors. This is standard Dependency Inversion (DDD practice) and is accepted as a project convention. Phases 4 and 5 extend this pattern. Phase 9 codifies the exception via `ignore_imports`.

### `pulldb/auth/` classification inconsistency

The copilot-instructions classify `pulldb/auth/` as **shared layer**, but the code self-labels as **features layer** (see `pulldb/auth/repository.py` line 7). Import analysis confirms it behaves as features: it imports downward from domain and infra, and no domain code imports from it. **Resolution:** Update copilot-instructions to classify auth as features, or add a note in `.pulldb/standards/hca.md`. Track separately from this plan.

### `pulldb.web` → `pulldb.api` cross-import

`pulldb/web/router_registry.py` imports `create_overlord_router` from `pulldb/api/overlord.py`. Both are pages-layer, but this creates a cross-package dependency. Options:
1. Move `create_overlord_router` into `pulldb/web/features/admin/overlord_routes.py` during Phase 2 (preferred — eliminates cross-import)
2. Accept sibiling pages-layer imports as legal (pragmatic, but blocks `|` grouping in import-linter)

Track as a follow-up after Phase 2.

---

## Rollback Strategy

Each phase is designed to be independently revertible:

- **Phases 1-2, 4:** Pure refactors — `git revert` the merge commit restores previous state with no behavior change
- **Phase 3:** Behavioral change — if issues arise, the `_ERROR_STATUS_MAP` fallback can temporarily default to `status_code=500` for unrecognized exceptions while debugging. All subclasses remain `isinstance`-compatible with `EnqueueError`, so existing `except EnqueueError` handlers continue to work
- **Phase 5:** If `HostRepository` changes cause test failures, the original private functions in `enqueue.py` can be reinstated from git history while the repo implementation is fixed
- **Phase 6:** Performance changes — revert to `get_all()` if paginated queries produce incorrect results
- **Phase 9:** CI gate — disable the `lint-imports` check in pre-commit if it produces false positives during stabilization

---

## Codebase Facts (validated 2026-02-11)

Reference data to avoid re-discovery during execution:

| Fact | Value |
|------|-------|
| `admin/routes.py` current length | ~7,320 lines |
| `EnqueueError` raise sites in `enqueue.py` | 28 |
| `HostRepository` implementation | `pulldb/infra/mysql.py` line ~4895 |
| Router registration file | `pulldb/web/router_registry.py` |
| FastAPI dependencies file | `pulldb/web/dependencies.py` (single file, not package) |
| Files importing from `pulldb.infra.overlord` | 4 files, 6 import sites |
| Existing infra→domain imports (DIP) | 12 sites across 6 files |
| `OverlordCompany.from_row()` input type | `dict[str, Any]` (no infra-specific types) |
| Raw `mysql.connector` in `enqueue.py` | 2 functions (lines ~157, ~199) |
