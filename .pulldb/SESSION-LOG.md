# pullDB Development Session Log

> **Purpose**: Automatic audit trail of development conversations, decisions, and rationale.  
> **Format**: Reverse chronological (newest first)  
> **Maintained by**: AI assistant (automatic, ongoing)

---

## 2025-12-11 | Phase 2: E2E Tests Migration to Simulation Infrastructure

### Context
Continuation of mock infrastructure unification. Phase 1 completed dev_server.py migration.
Phase 2 migrates e2e tests (Playwright) to use the same unified simulation infrastructure.

### What Was Done
1. **Refactored `tests/e2e/conftest.py`** - Replaced 447 lines of duplicate mock code with `E2EAPIState`
2. **Created `E2EAPIState` class** - Mirrors `DevAPIState`, uses `_initialize_simulation_state()`
3. **Preserved test data compatibility** - Seeded users, hosts, jobs matching original e2e expectations
4. **Maintained auth compatibility** - Same "testpass123" password hash for e2e login tests

### Key Changes
- Removed: `MockUserRepo`, `MockAuthRepo`, `MockJobRepo`, `MockHostRepo`, `create_mock_*` helpers
- Added: `E2EAPIState` class using simulation infrastructure
- Added: `_seed_e2e_data()` and `_seed_auth_credentials()` methods
- File reduced from 447 to ~440 lines (much cleaner, less duplication)

### Rationale
- **Single Source of Truth**: All three mock systems (dev, e2e, simulation) now share one implementation
- **Prevents Drift**: Future changes to simulation automatically apply to e2e tests
- **Easier Maintenance**: One place to update mock behavior

### Files Modified
- `tests/e2e/conftest.py` (major refactor)

---

## 2025-12-XX | Mock Infrastructure Unification & Cleanup-Staging Bug Fix

### Context
User reported bug: `Cleanup failed: 'MockJobRepo' object has no attribute 'find_job_by_staging_prefix'` on the cleanup-staging page in dev server mode.

### Root Cause
The dev server (`scripts/dev_server.py`) used custom `MockJobRepo` but did NOT set `PULLDB_MODE=SIMULATION`. This meant cleanup code took the "real" path expecting full `JobRepository` interface, but got incomplete mock.

Additionally, discovered THREE separate mock implementations causing drift:
1. `pulldb/simulation/` - Production simulation mode (most complete)
2. `scripts/dev_server.py` - Dev server custom mocks (incomplete)
3. `tests/e2e/conftest.py` - Playwright e2e test mocks (incomplete)

### What Was Done
1. **Created `pulldb/simulation/core/seeding.py`** - Data seeding functions for dev scenarios
2. **Enhanced `SimulatedJobRepository`** - Added compatibility properties (`active_jobs`, `history_jobs`, `_cancel_requested`)
3. **Set `PULLDB_MODE=SIMULATION`** at top of dev_server.py
4. **Created `DevAPIState` class** - Replaces `MockAPIState`, uses unified simulation infrastructure
5. **Deleted ~1100 lines of duplicate mock code** from dev_server.py
6. **Fixed `prune_job_events` signature** - Added default value to match production
7. **Created `tests/simulation/test_protocol_parity.py`** - Catches future mock drift at CI time

### Rationale
- **FAIL HARD**: Three separate mocks inevitably drift, causing silent failures
- **Single Source of Truth**: Unified simulation prevents drift
- **Protocol Parity Tests**: CI catches missing methods BEFORE they cause bugs
- **HCA Compliance**: Seeding module in shared layer, DevAPIState in pages layer

### Key Decisions
| Decision | Why |
|----------|-----|
| Unify to simulation module | Single source prevents drift |
| Keep scenario switching | Dev workflow requires different states |
| Add parity tests | CI catches drift early |
| Leave e2e for phase 2 | Focus on immediate bug fix first |

### Files Modified
- `pulldb/simulation/core/seeding.py` (created)
- `pulldb/simulation/adapters/mock_mysql.py` (added properties, fixed signature)
- `scripts/dev_server.py` (refactored, deleted ~1100 lines)
- `tests/simulation/test_protocol_parity.py` (created)

### Test Results
- 42 tests pass (simulation + unit)
- Dev server starts correctly
- Protocol parity tests catch future drift

---

## 2025-12-04 | Automatic Session Logging Implementation

### Context
User requested automatic, ongoing session logging that captures what we discuss, what's being audited/fixed, and WHY - without needing reminders. Should be as natural as HCA enforcement.

### What Was Done
1. **Created `.pulldb/SESSION-LOG.md`** - Append-only audit trail
2. **Updated `.github/copilot-instructions.md`** - Added session logging as Critical Directive #5
3. **Updated `.pulldb/CONTEXT.md`** - Added to "Ongoing Behaviors (AUTOMATIC)" section
4. **Defined trigger points**: Session start, after significant work, before session end
5. **Established log format**: Date, Topic, Context, Actions, Rationale, Files

### Rationale
- **Institutional memory**: Captures WHY decisions were made for future reference
- **Accountability**: Creates audit trail of development activity
- **Onboarding**: New developers can read history to understand evolution
- **Pattern recognition**: Reviewing logs reveals recurring issues

### Design Decisions
| Decision | Why |
|----------|-----|
| Reverse chronological | Newest work most relevant |
| Mandatory like HCA | Must be automatic, not opt-in |
| Reference principles | Connect actions to standards (FAIL HARD, Laws of UX) |
| Concise format | Scannable, not verbose |

### Files Modified
- `.pulldb/SESSION-LOG.md` (created)
- `.github/copilot-instructions.md` (added session logging directive)
- `.pulldb/CONTEXT.md` (added ongoing behaviors section)

---

## 2025-12-04 | Web UI Style Guide & Visual Audit

### Context
User requested a comprehensive audit of the web UI with recommendations based on modern design principles and UX research.

### What Was Done
1. **Audited entire web UI** (~2,100 lines of CSS in base.html, 15+ templates)
2. **Researched UX principles** - Consulted Nielsen's 10 Heuristics, Laws of UX (lawsofux.com)
3. **Created comprehensive style guide** (`docs/STYLE-GUIDE.md`) documenting:
   - Design philosophy (internal tool priorities)
   - Color system with semantic mapping
   - Typography scale
   - Component patterns (buttons, cards, badges, tables, forms)
   - Accessibility requirements
4. **Added to knowledge base** (`docs/KNOWLEDGE-POOL.md`) for quick reference
5. **Built visual styleguide page** (`/web/admin/styleguide`) showing all components
6. **Captured screenshots** using Playwright MCP for visual review

### Key Findings
| Issue | Impact | Status |
|-------|--------|--------|
| CSS bloat (2,100+ lines inline) | Maintenance burden | Documented for refactor |
| Inconsistent component patterns | Cognitive load | Canonical patterns defined |
| Missing focus states | Accessibility | Added to checklist |
| No dark mode | User preference | Low priority, planned |

### Rationale
- Internal tools benefit from **consistency over creativity**
- Established design tokens enable team scalability
- Visual documentation reduces onboarding time
- Laws of UX provide evidence-based guidance

### Files Modified
- `docs/STYLE-GUIDE.md` (created)
- `docs/KNOWLEDGE-POOL.md` (updated)
- `pulldb/web/templates/admin/styleguide.html` (created)
- `pulldb/web/features/admin/routes.py` (added styleguide route)

---

## 2025-12-04 | Manager Templates Enhancement

### Context
Building out web pages for manager functions to match admin/dashboard quality standards.

### What Was Done
1. Enhanced `manager/index.html` with admin-style section cards
2. Enhanced `manager/my_team.html` with stats grid and improved tables
3. Enhanced `manager/user_detail.html` with profile card pattern
4. Enhanced `manager/create_user.html` with form card pattern
5. Enhanced `manager/submit_for_user.html` with sectioned form layout

### Rationale
- **Law of Similarity**: Consistent patterns help users recognize functionality
- **Aesthetic-Usability Effect**: Polished UI perceived as more usable
- Manager role is critical for team workflows - deserves first-class UI

---

## 2025-12-04 | RLock Refactoring (Simulation Mode)

### Context
User identified dangerous `_unlocked` pattern in mock_mysql.py where internal methods could be called without proper locking.

### What Was Done
1. Refactored `SimulatedUserRepository` to use `RLock` (reentrant lock)
2. Eliminated all `_unlocked` helper methods
3. Public methods now safely call other public methods (nested lock acquisition)
4. Verified with test script

### Rationale
- **FAIL HARD principle**: Unsafe patterns should be eliminated, not documented
- `RLock` allows same thread to re-acquire lock - perfect for nested calls
- Simpler code = fewer bugs

### Before/After
```python
# BEFORE (dangerous)
def get_or_create_user(self, username):
    with self._state.lock:
        user = self._get_user_by_username_unlocked(username)  # Could be called outside lock!
        
# AFTER (safe)
def get_or_create_user(self, username):
    with self._state.lock:  # RLock - reentrant
        user = self.get_user_by_username(username)  # Safe - same thread can re-acquire
```

---

## Session Log Guidelines

When appending to this log, include:

1. **Date & Topic** - `## YYYY-MM-DD | Brief Topic`
2. **Context** - What prompted this work
3. **What Was Done** - Concrete actions taken
4. **Key Findings** - Issues discovered (if audit)
5. **Rationale** - WHY decisions were made
6. **Files Modified** - For traceability

## 2025-12-06 | Refactor Backup Discovery Logic

### Context
Addressed "Code Duplication" gap from Web2 Audit Report. Logic for searching customers and backups in S3 was duplicated between API and Web2.

### What Was Done
- Created `pulldb/domain/services/discovery.py` with `DiscoveryService`.
- Refactored `pulldb/api/main.py` to use the shared service.
- Refactored `pulldb/web2/features/restore/routes.py` to use the shared service.
- Verified with unit tests in simulation mode.

### Rationale
- **DRY Principle**: Centralized S3 search logic to a single domain service.
- **HCA**: Moved business logic from API/Web layers to Domain layer.
- **Maintainability**: Changes to S3 structure or logic now only need to happen in one place.

### Files Modified
- `pulldb/domain/services/discovery.py` (new)
- `pulldb/api/main.py`
- `pulldb/web2/features/restore/routes.py`
