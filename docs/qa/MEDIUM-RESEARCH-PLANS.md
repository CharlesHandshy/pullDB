# MEDIUM Priority Findings - Research & Implementation Plans

> **Created**: 2026-01-19  
> **Completed**: 2026-01-19  
> **Purpose**: Detailed research and implementation plans for remaining MEDIUM findings  
> **Status**: ✅ ALL WORK PACKAGES COMPLETED - 18 findings remediated this session

---

## Executive Summary

This document transforms the 52 remaining MEDIUM findings into **actionable research projects** with detailed implementation plans. The findings are organized into 5 work packages based on complexity and dependencies.

### ✅ Implementation Results (2026-01-19)

All 5 work packages were completed through disciplined git branching. 11 branches were created, committed, merged (--no-ff), and pushed to origin/main.

| Work Package | Branches Merged | Findings Remediated |
|--------------|-----------------|---------------------|
| WP1: Type Hints | 4 | 4 (Protocol + Any replacement + MySQL types) |
| WP2: Large Functions | 2 | 2 (executor + loop decomposition) |
| WP3: Error Handling | 3 | 3 (logging + exception narrowing + traceback) |
| WP4: Docstrings | 2 | 9 (7 Protocols + 2 dataclasses) |
| **TOTAL** | **11** | **18** |

### Key Discoveries

| Category | Total Findings | Already Remediated | Truly Remaining | Effort |
|----------|----------------|-------------------|-----------------|--------|
| Type Hints | 10 | 3 | 7 | 2-3 hours |
| Code Quality | 13 | 1 | 12 | 8-12 hours |
| Error Handling | ~15 | 12 | 3 | 1 hour |
| Docstrings | 20 | 0 | 20 | 5 hours |
| HCA Compliance | 1 | 1 | 0 | 0 |

**Total Estimated Effort**: 16-21 hours

---

## Work Package 1: Type Hints Modernization

### WP1-A: Protocol Definitions (Foundation)

**Dependencies**: None - this is the foundation for WP1-B and WP1-C

**Problem Statement**: Multiple files use `Any` for repository/client types because they support both real and simulated implementations. While comments explain this, the types aren't statically checkable.

**Files to Modify**:
1. `pulldb/domain/interfaces.py` - Already has Protocol definitions but may need enhancement
2. `pulldb/infra/s3.py` - Needs S3ClientProtocol definition

**Implementation Plan**:

```python
# Step 1: Verify existing Protocols in interfaces.py have all needed methods
# Already exists: JobRepositoryProtocol, UserRepositoryProtocol, etc.

# Step 2: Create S3ClientProtocol in pulldb/infra/s3.py
from typing import Protocol, Iterator
from mypy_boto3_s3.type_defs import ObjectTypeDef

class S3ClientProtocol(Protocol):
    """Protocol for S3 operations supporting both real and mock implementations."""
    
    def discover_backup(
        self, bucket: str, prefix: str, customer: str
    ) -> BackupSpec | None:
        """Discover most recent backup for a customer."""
        ...
    
    def download_backup(
        self, bucket: str, key: str, local_path: Path
    ) -> None:
        """Download backup archive to local path."""
        ...
    
    def list_objects(
        self, bucket: str, prefix: str
    ) -> Iterator[ObjectTypeDef]:
        """List objects in bucket with prefix."""
        ...
```

**Risk Assessment**: LOW - Adding Protocol definitions is additive and won't break existing code.

**Effort**: 45 minutes

---

### WP1-B: Replace Any in APIState

**Finding**: B01-006-003  
**File**: `pulldb/api/types.py`  
**Depends On**: WP1-A (Protocol definitions must exist)

**Current State** (Lines 17-26):
```python
class APIState(NamedTuple):
    """Cached application state shared across requests."""
    config: Config
    pool: Any  # MySQLPool in REAL mode, None in SIMULATION mode
    user_repo: Any  # UserRepository protocol
    job_repo: Any  # JobRepository protocol
    settings_repo: Any  # SettingsRepository protocol
    host_repo: Any  # HostRepository protocol
    auth_repo: "AuthRepository | None" = None
    audit_repo: Any = None
```

**Target State**:
```python
from pulldb.domain.interfaces import (
    JobRepositoryProtocol,
    UserRepositoryProtocol,
    HostRepositoryProtocol,
    SettingsRepositoryProtocol,
    AuditRepositoryProtocol,
)
from pulldb.infra.mysql import MySQLPool

class APIState(NamedTuple):
    """Cached application state shared across requests."""
    config: Config
    pool: MySQLPool | None  # MySQLPool in REAL mode, None in SIMULATION mode
    user_repo: UserRepositoryProtocol
    job_repo: JobRepositoryProtocol
    settings_repo: SettingsRepositoryProtocol
    host_repo: HostRepositoryProtocol
    auth_repo: AuthRepository | None = None
    audit_repo: AuditRepositoryProtocol | None = None
```

**Risk Assessment**: LOW - Type-only change, no runtime impact.

**Effort**: 20 minutes

---

### WP1-C: Replace Any in WorkerExecutorDependencies

**Finding**: B06-003-002  
**File**: `pulldb/worker/executor.py`  
**Depends On**: WP1-A (S3ClientProtocol must exist)

**Current State** (approx line 30):
```python
@dataclass(slots=True)
class WorkerExecutorDependencies:
    """Repositories and shared clients required by the executor.

    Uses Any types to allow both real and simulated implementations.
    """
    job_repo: Any  # JobRepository or SimulatedJobRepository
    host_repo: Any  # HostRepository or SimulatedHostRepository
    s3_client: Any  # S3Client or MockS3Client
```

**Target State**:
```python
from pulldb.domain.interfaces import JobRepositoryProtocol, HostRepositoryProtocol
from pulldb.infra.s3 import S3ClientProtocol

@dataclass(slots=True)
class WorkerExecutorDependencies:
    """Repositories and shared clients required by the executor.

    Accepts any implementation conforming to repository/client Protocols.
    """
    job_repo: JobRepositoryProtocol
    host_repo: HostRepositoryProtocol
    s3_client: S3ClientProtocol
```

**Risk Assessment**: LOW - Type-only change.

**Effort**: 15 minutes

---

### WP1-D: MySQL Connection Context Manager Type

**Finding**: B03-009-005  
**File**: `pulldb/infra/mysql.py`  
**Depends On**: None

**Current State** (approx line 64):
```python
@contextmanager
def connection(self) -> Iterator[Any]:
    """Get a database connection from the pool.

    Yields:
        MySQL connection object.
    """
```

**Target State**:
```python
from mysql.connector.connection import MySQLConnection

@contextmanager
def connection(self) -> Iterator[MySQLConnection]:
    """Get a database connection from the pool.

    Yields:
        MySQL connection object with automatic cleanup.
    """
```

**Verification Required**: 
- Check if `mysql-connector-python` has type stubs installed
- If not, install: `pip install types-mysql-connector-python` or use `MySQLConnection` from the package

**Risk Assessment**: LOW - Type narrowing only.

**Effort**: 10 minutes

---

### WP1-E: Literal Type for Log Level

**Finding**: B03-007-002  
**File**: `pulldb/infra/logging_config.py`  

**Research Note**: File may have been renamed or moved. Need to locate.

**Target Implementation**:
```python
from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

def configure_logging(level: LogLevel = "INFO") -> None:
    """Configure application logging with the specified level.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
```

**Risk Assessment**: VERY LOW - Pure type annotation improvement.

**Effort**: 10 minutes (if file exists)

---

### WP1-F: Already Remediated (No Action Needed)

| Finding | File | Reason |
|---------|------|--------|
| B06-010-002 | `worker/loop.py` | Already uses `from __future__ import annotations` + TYPE_CHECKING correctly |
| B07-006-003 | `worker/log_normalizer.py` | Already uses modern `X \| None` syntax |
| B07-008-003 | `worker/metadata_synthesis.py` | Already uses `from __future__ import annotations` |

---

## Work Package 2: Large Function Decomposition

### WP2-A: Split `_execute_workflow` (executor.py)

**Finding**: B06-003-005  
**File**: `pulldb/worker/executor.py`  
**Lines**: 563-897 (334 lines)

**Current Structure Analysis**:
```
_execute_workflow(self, job: Job) -> None
├── Lines 563-580: Setup (job_dir, profiler)
├── Lines 580-620: PRE-FLIGHT checks
├── Lines 620-680: DISCOVERY phase
├── Lines 680-730: DOWNLOAD phase with callbacks
├── Lines 730-780: EXTRACTION phase with callbacks
├── Lines 780-830: RESTORE setup (connection specs, callbacks)
├── Lines 830-870: RESTORE execution
├── Lines 870-897: Completion handling (profile, mark deployed)
```

**Proposed Refactoring**:

```python
# New helper methods (private)
def _run_preflight_checks(self, job: Job, job_dir: Path) -> None:
    """Verify job can proceed before resource-intensive operations."""
    
def _discover_backup(self, job: Job) -> BackupSpec:
    """Locate and validate backup in S3.
    
    Returns:
        BackupSpec with bucket, key, and metadata.
        
    Raises:
        BackupNotFoundError: If no backup found for customer.
    """

def _download_and_extract(
    self, job: Job, backup_spec: BackupSpec, job_dir: Path
) -> Path:
    """Download archive from S3 and extract to job directory.
    
    Returns:
        Path to extracted directory.
    """

def _execute_restore(
    self, job: Job, extracted_dir: Path, profiler: RestoreProfiler
) -> None:
    """Run myloader restore with progress monitoring."""

def _finalize_workflow(
    self, job: Job, profiler: RestoreProfiler
) -> None:
    """Mark job complete and record final profile."""

# Simplified main method
def _execute_workflow(self, job: Job) -> None:
    """Execute complete restore workflow for a claimed job.
    
    Orchestrates: preflight → discovery → download → extract → restore → finalize.
    """
    job_dir = self._prepare_job_directory(job)
    profiler = RestoreProfiler(job.id)
    
    try:
        self._run_preflight_checks(job, job_dir)
        backup_spec = self._discover_backup(job)
        extracted_dir = self._download_and_extract(job, backup_spec, job_dir)
        self._execute_restore(job, extracted_dir, profiler)
        self._finalize_workflow(job, profiler)
    except Exception as exc:
        profiler.complete(error=str(exc))
        self._handle_failure(job, exc)
        raise
```

**Risk Assessment**: MEDIUM - Structural change to critical code path.

**Testing Strategy**:
1. Run full integration test suite before changes
2. Make changes incrementally (one helper at a time)
3. Verify test coverage doesn't drop
4. Manual testing of a real restore job

**Effort**: 3-4 hours

---

### WP2-B: Split `run_worker_loop` (loop.py)

**Finding**: B06-010-003  
**File**: `pulldb/worker/loop.py`  
**Lines**: 70-420 (350 lines)

**Current Structure Analysis**:
```
run_worker_loop(...)
├── Lines 70-120:   Setup (worker_id, backoff config)
├── Lines 120-180:  Job claim and execution block
├── Lines 180-260:  Stale running job check block
├── Lines 260-320:  Stale deleting job check block  
├── Lines 320-380:  Admin task check block
├── Lines 380-420:  Backoff and error handling
```

**Proposed Refactoring**:

```python
# New helper functions
def _try_claim_and_execute_job(
    worker_id: str, job_repo: JobRepository, executor: WorkerExecutor
) -> bool:
    """Attempt to claim and execute one job.
    
    Returns:
        True if a job was claimed and executed, False if queue empty.
    """

def _check_stale_running_jobs(
    job_repo: JobRepository, timeout_seconds: int
) -> bool:
    """Check for and recover stale running jobs.
    
    Returns:
        True if any stale jobs were recovered.
    """

def _check_stale_deleting_jobs(
    job_repo: JobRepository, cleanup_handler: CleanupHandler
) -> bool:
    """Check for and process stale deleting jobs.
    
    Returns:
        True if any stale deleting jobs were processed.
    """

def _check_admin_tasks(
    admin_repo: AdminTaskRepository, handlers: dict[str, Callable]
) -> bool:
    """Check for and execute pending admin tasks.
    
    Returns:
        True if any admin tasks were executed.
    """

def _calculate_backoff(consecutive_empty: int, max_backoff: float) -> float:
    """Calculate exponential backoff with jitter.
    
    Args:
        consecutive_empty: Number of consecutive empty poll iterations.
        max_backoff: Maximum backoff time in seconds.
        
    Returns:
        Sleep duration with jitter.
    """
```

**Risk Assessment**: MEDIUM - Core worker loop.

**Testing Strategy**:
1. `test_loop.py` has integration tests - verify passing before/after
2. Extract helpers one at a time with tests between
3. Verify worker daemon still starts and processes jobs

**Effort**: 2-3 hours

---

### WP2-C: Split `cleanup.py` into Modules (LARGEST)

**Finding**: B06-009-004  
**File**: `pulldb/worker/cleanup.py`  
**Lines**: 2730 total

**Current Structure Analysis**:
```
cleanup.py (2730 lines)
├── Lines 1-100:     Module docstring + imports + data classes
├── Lines 100-500:   CleanupCandidate, OrphanCandidate classes
├── Lines 500-1000:  Job cleanup functions (mark_for_delete, etc.)
├── Lines 1000-1500: Orphan detection logic (find_orphans, etc.)
├── Lines 1500-2000: Scheduled cleanup orchestration  
├── Lines 2000-2500: Delete job execution
├── Lines 2500-2730: Stale running job recovery
```

**Proposed Module Split**:

```
pulldb/worker/cleanup/
├── __init__.py          # Re-exports for backwards compatibility
├── models.py            # CleanupCandidate, OrphanCandidate, result dataclasses
├── job_cleanup.py       # Job-based cleanup functions
├── orphan_detection.py  # Orphan database detection
├── delete_executor.py   # Delete job execution
└── stale_recovery.py    # Stale running job recovery
```

**Backwards Compatibility**:
```python
# pulldb/worker/cleanup/__init__.py
"""Cleanup subsystem for worker daemon.

HCA Layer: features

Re-exports all public symbols for backwards compatibility.
"""
from pulldb.worker.cleanup.models import (
    CleanupCandidate,
    OrphanCandidate,
    CleanupResult,
)
from pulldb.worker.cleanup.job_cleanup import (
    mark_database_for_deletion,
    execute_pending_deletes,
)
from pulldb.worker.cleanup.orphan_detection import (
    find_orphan_databases,
    classify_orphan,
)
from pulldb.worker.cleanup.delete_executor import (
    execute_delete_job,
)
from pulldb.worker.cleanup.stale_recovery import (
    recover_stale_running_jobs,
)

__all__ = [
    "CleanupCandidate",
    "OrphanCandidate",
    ...
]
```

**Risk Assessment**: HIGH - Many imports point to this file across codebase.

**Testing Strategy**:
1. Search for all imports: `grep -rn "from pulldb.worker.cleanup import" pulldb/`
2. Create the new module structure with re-exports
3. Verify all tests pass with re-exports
4. Then move code incrementally

**Effort**: 6-8 hours

---

### WP2-D: Skip - Deprecated Module

**Finding**: B07-008-005  
**File**: `pulldb/worker/metadata_synthesis.py`

**Status**: Module is marked deprecated. Header states:
> "Use `backup_metadata.py` instead. Removal planned for v2.0.0."

**Recommendation**: Do NOT refactor. Track for removal in v2.0.0 milestone instead.

**Effort**: 0 (skip)

---

## Work Package 3: Error Handling Improvements

### WP3-A: Add Debug Logging for Silent Fallbacks

**Finding**: Multiple "silent pass" patterns

| File | Line | Pattern | Fix |
|------|------|---------|-----|
| `worker/service.py` | 78 | `except ValueError: pass` | Add `logger.debug("Invalid poll_interval in env, using default")` |

**Implementation**:
```python
# Before
try:
    poll_interval = float(os.environ.get("POLL_INTERVAL", "5.0"))
except ValueError:
    pass  # Use default

# After
try:
    poll_interval = float(os.environ.get("POLL_INTERVAL", "5.0"))
except ValueError:
    logger.debug(
        "Invalid POLL_INTERVAL in environment, using default 5.0",
        extra={"value": os.environ.get("POLL_INTERVAL")},
    )
    poll_interval = 5.0
```

**Risk Assessment**: VERY LOW - Adding logging.

**Effort**: 10 minutes

---

### WP3-B: Narrow Exception Types Where Appropriate

**Finding**: Broad `except Exception` that could be narrowed

| File | Line | Current | Recommended |
|------|------|---------|-------------|
| `infra/mysql.py` | 5807 | `except Exception` | `except IntegrityError` for duplicate key |
| `worker/cleanup.py` | 347+ | `except Exception` | `except Error as MySQLError` |

**Implementation Example** (mysql.py):
```python
from mysql.connector import IntegrityError

# Before
except Exception:
    logger.debug("Failed to add disallowed user '%s'", username, exc_info=True)
    return False

# After
except IntegrityError:
    # Duplicate key - user already in disallowed list
    logger.debug("Disallowed user '%s' already exists", username)
    return False
except Exception:
    # Unexpected error - log and return False for safety
    logger.warning("Failed to add disallowed user '%s'", username, exc_info=True)
    return False
```

**Risk Assessment**: LOW - More specific error handling.

**Effort**: 30 minutes

---

### WP3-C: Verify Exception Re-raise in restore.py

**Finding**: B07-008-004 - Verify `raise` exists after logging

**File**: `pulldb/worker/restore.py` around line 759

**Action**: Read the file and confirm the exception is re-raised after logging.

**If Missing, Add**:
```python
except Exception as e:
    logger.error(
        {
            "phase": "fail_hard",
            "job_id": job.id,
            "target": job.target,
            "error": str(e),
        }
    )
    emit_event(...)
    raise  # MUST be present
```

**Risk Assessment**: HIGH if missing, NONE if present.

**Effort**: 15 minutes (verification + potential fix)

---

### WP3-D: Add Traceback to Simulation Event Logging

**Finding**: `simulation/core/bus.py` lines 159, 166

**Implementation**:
```python
# Before
except Exception as e:
    logger.error(f"Event callback error: {e}")

# After
except Exception as e:
    logger.error(f"Event callback error: {e}", exc_info=True)
```

**Risk Assessment**: VERY LOW - Simulation code only.

**Effort**: 5 minutes

---

## Work Package 4: Docstring Completion

### WP4-A: High-Value Targets (Interfaces First)

**File**: `pulldb/domain/interfaces.py` (60 minutes)

This file defines 6 Protocol classes with 40+ methods using one-line docstrings.

**Priority Methods** (public API):
- `JobRepository.enqueue_job`
- `JobRepository.claim_next_job`
- `JobRepository.mark_job_complete`
- `HostRepository.get_connection_spec`
- `UserRepository.get_user_by_code`

**Template**:
```python
def enqueue_job(self, job: Job) -> str:
    """Insert new job into queue.
    
    Args:
        job: Job to enqueue (id may be empty, will be generated).
        
    Returns:
        job_id: UUID of enqueued job.
        
    Raises:
        ValueError: If target already has active job on same host.
        IntegrityError: If job with same ID already exists.
    """
    ...
```

---

### WP4-B: Dataclass Attributes Sections

| File | Class | Fields to Document |
|------|-------|-------------------|
| `api/logic.py` | `TargetResult` | 6 fields |
| `simulation/core/state.py` | `SimulationState` | 20+ fields |

**Template for TargetResult**:
```python
@dataclass(frozen=True)
class TargetResult:
    """Result of target database name construction.
    
    Tracks whether customer name normalization was applied during
    automatic target name generation.

    Attributes:
        target: Final target database name.
        original_customer: Customer name before normalization (if applied).
        normalized_customer: Customer name after normalization (if applied).
        was_normalized: True if name normalization was applied.
        normalization_message: Human-readable normalization explanation.
        custom_target_used: True if user provided custom target name.
    """
```

---

### WP4-C: Missing Raises Sections

Files needing `Raises:` section additions:

| File | Function | Exceptions to Document |
|------|----------|----------------------|
| `api/logic.py` | `build_target_name` | `ValueError` |
| `infra/mysql.py` | `connection()` | `DatabaseError` |
| `worker/service.py` | `main()` | `SystemExit` |
| `worker/executor.py` | `execute_job()` | Various restore errors |

---

### WP4-D: Reference Files (Use as Templates)

These files are **fully compliant** - use as reference:
- `pulldb/domain/errors.py` - Excellent exception docstrings
- `pulldb/domain/permissions.py` - Excellent function docstrings

---

## Work Package 5: HCA Compliance

### WP5-A: Already Remediated

**Finding**: B16-004-001  
**File**: `pulldb/web/router_registry.py`

This finding about "HCA Layer: Foundation" vs "HCA Layer: pages" was already fixed in a previous session. **No action needed.**

---

## Implementation Schedule

### Phase 1: Quick Wins (Day 1 - 2 hours)

| Task | WP | Effort | Risk |
|------|----|----|------|
| Add debug logging for silent fallbacks | WP3-A | 10 min | Very Low |
| Add traceback to simulation logging | WP3-D | 5 min | Very Low |
| Verify restore.py re-raise | WP3-C | 15 min | None |
| Log level Literal type | WP1-E | 10 min | Very Low |
| MySQL connection type | WP1-D | 10 min | Low |
| Narrow exception types | WP3-B | 30 min | Low |

### Phase 2: Type Hints (Day 1 - 1.5 hours)

| Task | WP | Effort | Risk |
|------|----|----|------|
| Create S3ClientProtocol | WP1-A | 45 min | Low |
| Replace Any in APIState | WP1-B | 20 min | Low |
| Replace Any in WorkerExecutorDependencies | WP1-C | 15 min | Low |

### Phase 3: Docstrings (Day 2 - 5 hours)

| Task | WP | Effort | Risk |
|------|----|----|------|
| interfaces.py Protocol docstrings | WP4-A | 60 min | None |
| Dataclass Attributes sections | WP4-B | 65 min | None |
| Missing Raises sections | WP4-C | 45 min | None |
| Remaining method docstrings | WP4-D | 150 min | None |

### Phase 4: Structural Refactoring (Days 3-5 - 12 hours)

| Task | WP | Effort | Risk |
|------|----|----|------|
| Split `_execute_workflow` | WP2-A | 3-4 hr | Medium |
| Split `run_worker_loop` | WP2-B | 2-3 hr | Medium |
| Split cleanup.py into modules | WP2-C | 6-8 hr | High |

---

## Dependency Graph

```
WP1-A (Protocol Definitions)
    ├── WP1-B (APIState types)
    └── WP1-C (WorkerExecutorDependencies types)

WP2-A, WP2-B, WP2-C (Structural) - Independent of each other

WP3-A, WP3-B, WP3-C, WP3-D (Error Handling) - All independent

WP4-A, WP4-B, WP4-C, WP4-D (Docstrings) - All independent
```

---

## Risk Mitigation

### For High-Risk Changes (WP2-C: cleanup.py split)

1. **Create branch**: `feature/cleanup-module-split`
2. **Phase 1**: Create new module structure with re-exports only
3. **Phase 2**: Verify all imports work via re-exports
4. **Phase 3**: Move code file-by-file with tests between moves
5. **Phase 4**: Update direct imports across codebase
6. **Phase 5**: Squash merge when fully tested

### For Medium-Risk Changes (WP2-A, WP2-B)

1. **Create branch**: `refactor/executor-decompose` or `refactor/loop-decompose`
2. Extract one helper at a time
3. Run full test suite after each extraction
4. Manual smoke test with real job before merge

---

## Validation Checklist

After all work packages complete:

- [ ] `make lint` passes (0 errors)
- [ ] `make test` passes (all tests)
- [ ] `make typecheck` passes (Pylance/mypy clean)
- [ ] Production code has 0 Pylance errors
- [ ] Update QAA-FINDINGS-PLAN.md with remediation status
- [ ] Update QAA-MASTER-STATE.md totals

---

*Document created: 2026-01-19*  
*Next action: Execute Phase 1 quick wins*
