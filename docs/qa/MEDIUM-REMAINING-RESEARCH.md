# MEDIUM Priority Findings - Remaining Research Plans

> **Created**: 2026-01-20  
> **Author**: QA&A Remediation Agent  
> **Purpose**: Detailed research plans for **23 remaining MEDIUM findings**  
> **Status**: 🔬 RESEARCH PHASE - Ready for implementation

---

## Executive Summary

This document provides **comprehensive research and implementation plans** for the 23 remaining MEDIUM priority findings from the QA&A audit. Each finding is documented with:

1. **Problem Analysis** - Root cause and impact assessment
2. **Research** - Standards reference, edge cases, patterns
3. **Implementation Plan** - Step-by-step with code examples
4. **Risk Assessment** - Potential issues and mitigations
5. **Testing Strategy** - Verification approach
6. **Effort Estimate** - Time and complexity

### Finding Distribution

| Category | Count | Effort Est. | Priority |
|----------|-------|-------------|----------|
| Error Handling | 10 | 3-4 hours | 🔴 HIGH - FAIL HARD violations |
| Docstrings | 6 | 2 hours | 🟡 MEDIUM - Maintainability |
| Code Quality | 4 | 4-6 hours | 🟡 MEDIUM - Security & structure |
| Type Hints | 2 | 30 min | 🟢 LOW - Style consistency |
| HCA Compliance | 1 | 15 min | 🟢 LOW - Documentation only |
| **TOTAL** | **23** | **~10-13 hours** | |

---

## Work Package 5: Error Handling (10 findings)

**Theme**: Violations of FAIL HARD protocol - silent exception swallowing

**Standard Reference**: `engineering-dna/protocols/fail-hard.md`

### WP5-A: S3 Broad Exception Catching

**Findings**: B03-012-003, B03-012-004  
**File**: `pulldb/infra/s3.py`  
**Lines**: 298-301, 388-390  
**Severity**: MEDIUM

#### Problem Analysis

The S3 client catches broad `Exception` where boto3/botocore specific exceptions would be more appropriate. This masks unexpected errors and violates FAIL HARD.

**Current Pattern** (Line 298-301):
```python
try:
    response = self._client.list_objects_v2(...)
except Exception as e:
    logger.warning(f"S3 listing failed: {e}")
    return None
```

**Issues**:
1. Catches ALL exceptions including `KeyboardInterrupt`, `SystemExit`
2. Masks unexpected errors (e.g., credential issues, network config)
3. `return None` silently degrades service

#### Research: Boto3 Exception Hierarchy

```
botocore.exceptions.BotoCoreError (base)
├── ClientError (HTTP errors: 404, 403, 500, etc.)
├── EndpointConnectionError (network)
├── ConnectTimeoutError
├── ReadTimeoutError
├── SSLError
└── ParamValidationError

botocore.exceptions.NoCredentialsError (auth)
botocore.exceptions.PartialCredentialsError (auth)
```

**Key Insight**: For S3 operations, we typically want:
- `ClientError` for AWS-returned errors (can inspect `.response['Error']['Code']`)
- `EndpointConnectionError` for network issues
- `NoCredentialsError` for auth issues

#### Implementation Plan

**Step 1**: Import specific exceptions at module level
```python
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)
```

**Step 2**: Replace broad catch at line 298-301
```python
try:
    response = self._client.list_objects_v2(
        Bucket=bucket,
        Prefix=prefix,
        MaxKeys=max_keys,
    )
except ClientError as e:
    error_code = e.response.get("Error", {}).get("Code", "Unknown")
    logger.warning(
        "S3 list failed: code=%s bucket=%s prefix=%s",
        error_code, bucket, prefix,
        exc_info=True,
    )
    if error_code in ("NoSuchBucket", "AccessDenied"):
        return None  # Expected recoverable
    raise  # Unexpected → FAIL HARD
except EndpointConnectionError:
    logger.warning(
        "S3 endpoint unreachable: bucket=%s",
        bucket,
        exc_info=True,
    )
    return None  # Network transient
```

**Step 3**: Apply same pattern at lines 388-390

#### Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Breaking change if code expects `None` for all failures | LOW | Audit callers; same behavior for expected errors |
| Missing exception type | LOW | BotoCoreError as fallback catch |
| Credential errors now propagate | DESIRED | This is correct FAIL HARD behavior |

#### Testing Strategy

1. **Unit test**: Mock `ClientError` with different error codes
2. **Unit test**: Mock `EndpointConnectionError` for transient failure
3. **Integration**: Verify real S3 operations still work
4. **Negative test**: Verify unexpected exceptions propagate

#### Effort Estimate

- Research complete: 0 min
- Implementation: 30 min
- Testing: 30 min
- **Total**: 1 hour

---

### WP5-B: Staging Exception Pattern

**Finding**: B06-006-004  
**File**: `pulldb/worker/staging.py`  
**Line**: 290  
**Severity**: MEDIUM

#### Problem Analysis

Catches broad `Exception` and re-raises as custom error, losing exception chaining information.

**Current Pattern** (approx line 290):
```python
try:
    # Database operations
except Exception as e:
    raise StagingCreationError(f"Failed to create staging: {e}")
```

**Issues**:
1. No `from e` - loses original traceback
2. Catches overly broad exception type
3. String interpolation of exception loses structured info

#### Implementation Plan

**Fix with exception chaining**:
```python
try:
    # Database operations
except mysql.connector.Error as e:
    raise StagingCreationError(
        f"Failed to create staging database: {e.msg}"
    ) from e
except PermissionError as e:
    raise StagingCreationError(
        f"Insufficient permissions for staging: {e}"
    ) from e
```

#### Effort Estimate: 20 minutes

---

### WP5-C: Deploy Module Patterns

**Findings**: B06-007-003, B06-007-004  
**File**: `pulldb/worker/atomic_rename.py`  
**Lines**: 353-364 (f-string SQL), 374 (exception loop)  
**Severity**: MEDIUM (Security concern for B06-007-003)

#### Problem Analysis

**B06-007-003 (SECURITY)**: f-string used for SQL construction
```python
# DANGEROUS:
sql = f"RENAME TABLE `{source_db}`.`{table}` TO `{target_db}`.`{table}`"
```

**B06-007-004**: Exception in loop with `last_exc` pattern masks failures
```python
last_exc = None
for table in tables:
    try:
        # rename
    except Exception as e:
        last_exc = e
if last_exc:
    raise last_exc  # Only raises last error, others lost
```

#### Research: SQL Injection in RENAME TABLE

MySQL `RENAME TABLE` doesn't support parameterized queries for table names. The safe approach is **identifier validation**:

```python
import re

def validate_identifier(name: str) -> str:
    """Validate and quote a MySQL identifier.
    
    Args:
        name: Database or table name to validate.
        
    Returns:
        Backtick-quoted identifier.
        
    Raises:
        ValueError: If identifier contains unsafe characters.
    """
    # MySQL identifiers: alphanumeric, underscore, dollar sign
    # Max 64 chars, cannot be purely numeric
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_$]*$', name):
        raise ValueError(f"Invalid identifier: {name!r}")
    if len(name) > 64:
        raise ValueError(f"Identifier too long: {len(name)} > 64")
    return f"`{name}`"
```

#### Implementation Plan

**B06-007-003 Fix**:
```python
def _build_rename_sql(self, source_db: str, target_db: str, table: str) -> str:
    """Build RENAME TABLE statement with validated identifiers.
    
    Args:
        source_db: Source database name.
        target_db: Target database name.
        table: Table name to rename.
        
    Returns:
        SQL statement with properly quoted identifiers.
        
    Raises:
        ValueError: If any identifier contains invalid characters.
    """
    src_db = validate_identifier(source_db)
    tgt_db = validate_identifier(target_db)
    tbl = validate_identifier(table)
    return f"RENAME TABLE {src_db}.{tbl} TO {tgt_db}.{tbl}"
```

**B06-007-004 Fix** - Collect all errors:
```python
from dataclasses import dataclass

@dataclass
class RenameResult:
    """Result of a table rename operation."""
    table: str
    success: bool
    error: Exception | None = None

def _rename_tables(self, tables: list[str]) -> list[RenameResult]:
    """Rename tables, collecting all errors.
    
    Returns:
        List of results, one per table.
        
    Raises:
        AtomicRenameError: If any table failed, includes all errors.
    """
    results = []
    for table in tables:
        try:
            self._rename_single_table(table)
            results.append(RenameResult(table, success=True))
        except Exception as e:
            results.append(RenameResult(table, success=False, error=e))
    
    failures = [r for r in results if not r.success]
    if failures:
        error_summary = "; ".join(
            f"{r.table}: {r.error}" for r in failures
        )
        raise AtomicRenameError(
            f"Failed to rename {len(failures)}/{len(tables)} tables: {error_summary}"
        )
    return results
```

#### Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Identifier validation too strict | MEDIUM | Valid names rejected | Test with real schema names |
| All-or-nothing change in error behavior | LOW | Callers may expect partial success | Document behavior change |

#### Effort Estimate: 2 hours (includes security review)

---

### WP5-D: Password Module Exception Chaining

**Finding**: B08-001-002  
**File**: `pulldb/auth/password.py`  
**Lines**: 63-66  
**Severity**: MEDIUM

#### Problem Analysis

Exception raised without chaining, losing original traceback.

**Current**:
```python
except Exception:
    raise PasswordError("Failed to hash password")
```

**Fixed**:
```python
except Exception as e:
    raise PasswordError(f"Failed to hash password: {e}") from e
```

#### Effort Estimate: 10 minutes

---

### WP5-E: Simulation Bus Exception Handling

**Findings**: B09-002-003, B09-002-004  
**File**: `pulldb/simulation/core/bus.py`  
**Lines**: 143-144, 149-150  
**Severity**: MEDIUM

#### Problem Analysis

Broad exception catch without re-raise in event bus handlers.

**Current Pattern**:
```python
try:
    handler(event)
except Exception:
    pass  # Silent swallow - FAIL HARD violation
```

**Research**: In simulation context, we want to:
1. Log handler failures for debugging
2. Continue processing other handlers (don't break simulation)
3. Track failure count for simulation health

#### Implementation Plan

```python
try:
    handler(event)
except Exception as e:
    logger.warning(
        "Event handler failed: event=%s handler=%s error=%s",
        type(event).__name__,
        handler.__name__,
        e,
        exc_info=True,
    )
    self._handler_errors += 1  # Track for health monitoring
    # Continue to next handler - simulation resilience
```

#### Effort Estimate: 30 minutes

---

### WP5-F: Seeding Silent Exception

**Finding**: B09-006-003  
**File**: `pulldb/simulation/core/seeding.py`  
**Lines**: 666-667  
**Severity**: MEDIUM

#### Problem Analysis

Exception silently swallowed during seeding operations.

**Fix Pattern**: Add logging before continuing

```python
except Exception as e:
    logger.warning(
        "Seeding operation failed, continuing: %s",
        e,
        exc_info=True,
    )
```

#### Effort Estimate: 10 minutes

---

### WP5-G: Simulation Router Exception Suppression

**Finding**: B11-002-003  
**File**: `pulldb/simulation/api/router.py`  
**Lines**: 221-225, 330-336  
**Severity**: MEDIUM

#### Problem Analysis

Uses `raise ... from None` which suppresses exception context.

**Current**:
```python
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e)) from None
```

**Issue**: `from None` hides the original traceback in logs.

**Fixed**:
```python
except ValueError as e:
    logger.debug("Validation error: %s", e, exc_info=True)
    raise HTTPException(status_code=400, detail=str(e)) from e
```

**Note**: For API responses, we don't want to expose internal details to users, but we DO want them in logs for debugging.

#### Effort Estimate: 20 minutes

---

### Error Handling Summary

| ID | File | Lines | Fix Type | Effort |
|----|------|-------|----------|--------|
| B03-012-003 | s3.py | 298-301 | Narrow exception | 30 min |
| B03-012-004 | s3.py | 388-390 | Narrow exception | 15 min |
| B06-006-004 | staging.py | 290 | Add `from e` | 20 min |
| B06-007-003 | atomic_rename.py | 353-364 | SQL identifier validation | 1 hr |
| B06-007-004 | atomic_rename.py | 374 | Collect all errors | 45 min |
| B08-001-002 | password.py | 63-66 | Add `from e` | 10 min |
| B09-002-003 | bus.py | 143-144 | Add logging | 15 min |
| B09-002-004 | bus.py | 149-150 | Add logging | 15 min |
| B09-006-003 | seeding.py | 666-667 | Add logging | 10 min |
| B11-002-003 | router.py | 221-225, 330-336 | Log before re-raise | 20 min |

**Total Error Handling Effort**: ~4 hours

---

## Work Package 6: Docstrings (6 findings)

**Theme**: Missing or incomplete documentation for simulation engine components

**Standard Reference**: `engineering-dna/standards/python.md` §Docstrings

### WP6-A: Simulation Engine Core Documentation

**Findings**: B09-003-002, B09-003-003, B09-003-004, B09-003-005  
**File**: `pulldb/simulation/core/engine.py`  
**Lines**: 20, 33, 38, 42  
**Severity**: MEDIUM

#### Problem Analysis

Core simulation engine lacks docstrings for:
- `EngineConfig` dataclass (line 20)
- `start()` method (line 33)
- `tick()` method (line 38)
- `stop()` method (line 42)

#### Implementation Plan

```python
@dataclass(frozen=True)
class EngineConfig:
    """Configuration for the simulation engine.
    
    Controls timing, concurrency, and behavior of the discrete-event simulation.
    
    Attributes:
        tick_interval_ms: Milliseconds between simulation ticks (default: 100).
        max_ticks: Maximum ticks before auto-stop, or None for unlimited.
        random_seed: Seed for reproducible randomness, or None for system entropy.
        enable_logging: Whether to emit debug logs during simulation.
    """
    tick_interval_ms: int = 100
    max_ticks: int | None = None
    random_seed: int | None = None
    enable_logging: bool = False


class SimulationEngine:
    """Discrete-event simulation engine for pullDB worker testing.
    
    Manages the simulation lifecycle: initialization, tick-based execution,
    and graceful shutdown. Thread-safe for use with async handlers.
    """
    
    def start(self) -> None:
        """Initialize and start the simulation.
        
        Sets up the event bus, initializes all registered handlers, and
        begins the tick loop. Safe to call multiple times (idempotent).
        
        Raises:
            SimulationError: If engine is already running.
        """
        ...
    
    def tick(self) -> bool:
        """Advance the simulation by one time unit.
        
        Processes all pending events, updates state, and advances the
        simulation clock. Called automatically in run loop or manually
        for step debugging.
        
        Returns:
            True if simulation should continue, False if complete.
            
        Raises:
            SimulationError: If engine not started.
        """
        ...
    
    def stop(self) -> None:
        """Gracefully stop the simulation.
        
        Flushes pending events, runs cleanup handlers, and releases
        resources. Safe to call multiple times (idempotent).
        """
        ...
```

#### Effort Estimate: 45 minutes

---

### WP6-B: Scenarios Method Documentation

**Finding**: B09-005-003  
**File**: `pulldb/simulation/core/scenarios.py`  
**Line**: 388  
**Severity**: MEDIUM

#### Problem Analysis

Method docstring missing Args section.

#### Implementation Plan

Read the method signature and add proper Args/Returns documentation:

```python
def configure_scenario(
    self,
    scenario_type: ScenarioType,
    config: ScenarioConfig,
) -> Scenario:
    """Configure and register a simulation scenario.
    
    Creates a scenario instance with the given configuration and
    registers it with the engine for execution during simulation.
    
    Args:
        scenario_type: Type of scenario to create (e.g., CONCURRENT_JOBS).
        config: Configuration parameters for the scenario.
        
    Returns:
        Configured Scenario instance ready for execution.
        
    Raises:
        ValueError: If scenario_type is not supported.
        ConfigurationError: If config is invalid for scenario_type.
    """
```

#### Effort Estimate: 20 minutes

---

### WP6-C: Adapters Module Documentation

**Finding**: B10-001-003  
**File**: `pulldb/simulation/adapters/__init__.py`  
**Lines**: 1-2  
**Severity**: MEDIUM

#### Problem Analysis

Module docstring lacks detail about exports.

#### Implementation Plan

```python
"""Simulation adapters for testing without external dependencies.

HCA Layer: shared

This module provides mock implementations of infrastructure components:

Exports:
    MockMySQLConnection: Thread-safe mock for MySQL operations.
    MockS3Client: In-memory S3 client for backup testing.
    MockExecutor: Simulated subprocess execution.

Usage:
    from pulldb.simulation.adapters import MockMySQLConnection
    
    conn = MockMySQLConnection()
    conn.execute("INSERT INTO jobs ...")

Note:
    These adapters maintain internal state for realistic simulation
    but do not persist data between test runs.
"""
from pulldb.simulation.adapters.mock_exec import MockExecutor
from pulldb.simulation.adapters.mock_mysql import MockMySQLConnection
from pulldb.simulation.adapters.mock_s3 import MockS3Client

__all__ = ["MockExecutor", "MockMySQLConnection", "MockS3Client"]
```

#### Effort Estimate: 30 minutes

---

### WP6-D: Searchable Dropdown Error Documentation

**Finding**: B15-006-003  
**File**: `pulldb/web/widgets/searchable_dropdown/__init__.py`  
**Severity**: MEDIUM

#### Problem Analysis

Factory function could document error cases.

#### Implementation Plan

Add Raises section to factory function.

#### Effort Estimate: 15 minutes

---

### Docstrings Summary

| ID | File | Focus | Effort |
|----|------|-------|--------|
| B09-003-002 | engine.py | EngineConfig docstring | 15 min |
| B09-003-003 | engine.py | start() docstring | 10 min |
| B09-003-004 | engine.py | tick() docstring | 10 min |
| B09-003-005 | engine.py | stop() docstring | 10 min |
| B09-005-003 | scenarios.py | Args section | 20 min |
| B10-001-003 | adapters/__init__.py | Module exports | 30 min |
| B15-006-003 | searchable_dropdown | Raises section | 15 min |

**Total Docstrings Effort**: ~2 hours

---

## Work Package 7: Code Quality (4 findings)

### WP7-A: Auth Repository f-string Patterns

**Findings**: B08-002-002, B08-002-003  
**File**: `pulldb/auth/repository.py`  
**Lines**: 67 (logger), 858-861 (SQL)  
**Severity**: MEDIUM (Security for SQL)

#### Problem Analysis

**B08-002-002**: f-string in logger call
```python
logger.info(f"User {username} logged in")  # Should use %s
```

**B08-002-003**: f-string for SQL construction (SECURITY)
```python
sql = f"SELECT * FROM users WHERE username = '{username}'"  # SQL INJECTION RISK
```

#### Implementation Plan

**B08-002-002 Fix** (logging best practice):
```python
logger.info("User %s logged in", username)
```

**B08-002-003 Fix** (SQL parameterization):
```python
sql = "SELECT * FROM users WHERE username = %s"
cursor.execute(sql, (username,))
```

#### Effort Estimate: 1 hour (careful SQL review)

---

### WP7-B: Processlist Query Extraction

**Finding**: B07-009-002  
**File**: `pulldb/worker/processlist_monitor.py`  
**Severity**: MEDIUM

#### Problem Analysis

Repeated SQL query patterns could be extracted into constants or builders.

#### Implementation Plan

Create query builder or constants at module level:

```python
# Query constants
PROCESSLIST_QUERY = """
    SELECT id, user, host, db, command, time, state, info
    FROM information_schema.PROCESSLIST
    WHERE command != 'Sleep'
    AND time > %s
"""

BLOCKING_QUERY = """
    SELECT blocking_pid, waiting_pid, blocking_query
    FROM sys.innodb_lock_waits
    WHERE waiting_query IS NOT NULL
"""
```

#### Effort Estimate: 45 minutes

---

### Code Quality Summary

| ID | File | Issue | Fix Type | Effort |
|----|------|-------|----------|--------|
| B08-002-002 | repository.py | f-string logger | Use %s format | 20 min |
| B08-002-003 | repository.py | f-string SQL | Parameterize | 40 min |
| B07-009-002 | processlist_monitor.py | Repeated queries | Extract constants | 45 min |

**Total Code Quality Effort**: ~2 hours

---

## Work Package 8: Type Hints (2 findings)

### WP8-A: type[X] Convention Consistency

**Findings**: B09-002-002, B09-005-002  
**Files**: `bus.py`, `scenarios.py`  
**Severity**: MEDIUM (Style)

#### Problem Analysis

Uses `type[X]` convention which is verbose but valid. Finding notes it as "consistent with project style" - this may be informational only.

**Current**:
```python
def register_handler(self, event_type: type[Event]) -> None:
```

**Alternative** (if we want to change):
```python
from typing import TypeVar
E = TypeVar('E', bound=Event)

def register_handler(self, event_type: type[E]) -> None:
```

#### Decision

**KEEP AS-IS** - The `type[X]` pattern is valid Python 3.9+ and is consistent across the simulation package. Changing would be churn without benefit.

**Action**: Mark as "Won't Fix - Style Consistent"

#### Effort Estimate: 0 minutes (document decision)

---

## Work Package 9: HCA Compliance (1 finding)

### WP9-A: Adapters Module Docstring Detail

**Finding**: B10-001-003  
**File**: `pulldb/simulation/adapters/__init__.py`  
**Severity**: MEDIUM

**Note**: This is duplicated from WP6-C (Docstrings). Already covered.

---

## Implementation Sequence

### Recommended Order (Risk-First)

1. **SECURITY FIRST** (1.5 hours)
   - B06-007-003: atomic_rename.py SQL injection
   - B08-002-003: repository.py SQL injection
   - B03-010-006: paths.py f-string SQL (if applicable)

2. **FAIL HARD VIOLATIONS** (2.5 hours)
   - B03-012-003/004: s3.py exception narrowing
   - B06-006-004: staging.py exception chaining
   - B08-001-002: password.py exception chaining
   - B09-002-003/004, B09-006-003: simulation logging

3. **CODE QUALITY** (1 hour)
   - B08-002-002: repository.py logging format
   - B07-009-002: processlist_monitor.py query extraction

4. **DOCSTRINGS** (2 hours)
   - B09-003-002/003/004/005: engine.py documentation
   - B09-005-003: scenarios.py Args section
   - B10-001-003: adapters module documentation
   - B15-006-003: searchable_dropdown Raises

5. **TYPE HINTS** (0 hours)
   - B09-002-002, B09-005-002: Document as "Won't Fix - Style Consistent"

### Git Branch Strategy

```
main
├── security/sql-injection-fixes     # WP7-A (SQL parts)
├── fix/fail-hard-s3-exceptions      # WP5-A
├── fix/fail-hard-staging-chaining   # WP5-B  
├── fix/fail-hard-deploy-patterns    # WP5-C
├── fix/fail-hard-simulation-logging # WP5-E, WP5-F, WP5-G
├── docs/simulation-engine-docstrings # WP6-A
├── docs/simulation-adapters         # WP6-C
├── refactor/processlist-queries     # WP7-B
└── chore/logging-format-fix         # WP7-A (logging part)
```

---

## Risk Matrix

| Risk | Findings | Impact | Probability | Mitigation |
|------|----------|--------|-------------|------------|
| SQL Injection | B06-007-003, B08-002-003 | HIGH | LOW | Identifier validation, parameterized queries |
| Silent Failures | B03-012-*, B09-* | MEDIUM | HIGH | Logging + specific exceptions |
| Breaking Changes | B05-C error collection | LOW | MEDIUM | Document behavior, test callers |
| Test Gaps | All | LOW | MEDIUM | Add unit tests for each fix |

---

## Verification Checklist

For each branch merge:

- [ ] All changed files pass `python3 -m py_compile`
- [ ] No new Pylance errors in production code
- [ ] Unit tests pass: `pytest tests/ -x`
- [ ] Related integration tests pass
- [ ] Code reviewed against standards

---

## Document History

| Date | Author | Change |
|------|--------|--------|
| 2026-01-20 | QA Agent | Initial research plans for 23 MEDIUM findings |
