# MEDIUM Findings Research Plans

> **Document Type**: Research & Implementation Plans | **Version**: 1.0.0 | **Created**: 2026-01-20
>
> Detailed research plans for remaining 12 MEDIUM severity QA&A findings.
> Each plan includes problem analysis, solution options, implementation steps, and acceptance criteria.

---

## Executive Summary

| Category | Remaining | Complexity | Estimated Effort |
|----------|-----------|------------|------------------|
| **M1: f-string SQL** | 14 instances | Medium | 4-6 hours |
| **M2: Any Return Types** | 28 instances | High | 8-12 hours |
| **M3: Broad Exception Handlers** | 42 files | Low | 2-4 hours (triage only) |

**Total Estimated Effort**: 14-22 hours (split across multiple sessions)

---

## M1: f-string SQL Construction

### Problem Statement

14 instances use f-string interpolation in `cursor.execute()` calls, which is flagged as a potential SQL injection vector.

### Risk Assessment

| Instance Type | Count | Actual Risk | Rationale |
|---------------|-------|-------------|-----------|
| `DROP DATABASE IF EXISTS` | 8 | **LOW** | Database names from internal job state, not user input |
| `DROP PROCEDURE IF EXISTS` | 2 | **LOW** | Hardcoded procedure names |
| `DROP USER IF EXISTS` | 2 | **MEDIUM** | Username from internal state, but credentials involved |
| `SHOW CREATE PROCEDURE` | 2 | **LOW** | Schema/procedure names from internal constants |
| `SHOW GRANTS FOR` | 1 | **LOW** | Username from internal authentication |
| `SHOW TABLES IN` | 1 | **LOW** | Table name from job configuration |

**Overall Assessment**: Low actual risk because all values come from trusted internal sources (job state, configuration, constants), not direct user input.

### Solution Options

#### Option A: Identifier Quoting Helper (Recommended)

Create a utility function that properly escapes MySQL identifiers:

```python
# pulldb/infra/mysql_utils.py

def quote_identifier(name: str) -> str:
    """Safely quote a MySQL identifier (database, table, column name).
    
    Escapes backticks and wraps in backticks to prevent SQL injection
    even if the identifier contains special characters.
    
    Args:
        name: The identifier to quote.
        
    Returns:
        Properly escaped and quoted identifier.
        
    Examples:
        >>> quote_identifier("my_database")
        '`my_database`'
        >>> quote_identifier("test`; DROP TABLE users; --")
        '`test`` DROP TABLE users  --`'
    """
    # Replace backticks with double backticks (MySQL escape sequence)
    escaped = name.replace("`", "``")
    # Remove semicolons and comment markers as defense-in-depth
    escaped = escaped.replace(";", "").replace("--", "")
    return f"`{escaped}`"
```

**Pros**:
- Centralizes escaping logic
- Maintains readability
- Defense-in-depth against future bugs

**Cons**:
- Still uses string formatting (not parameterized)
- MySQL identifiers can't use prepared statement parameters

#### Option B: Validation + Existing Pattern

Keep current pattern but add explicit validation before use:

```python
def validate_database_name(name: str) -> str:
    """Validate database name is safe for SQL use.
    
    Raises:
        ValueError: If name contains unsafe characters.
    """
    if not re.match(r'^[a-zA-Z0-9_]+$', name):
        raise ValueError(f"Invalid database name: {name}")
    return name
```

**Pros**:
- Fail-fast on invalid input
- Minimal code changes

**Cons**:
- Validation scattered across codebase

#### Option C: Accept Current Pattern (Document Risk)

Document that these patterns are intentionally using f-strings because:
1. MySQL doesn't support parameterized identifiers
2. All values come from trusted internal sources
3. Add `# nosec` comments for security scanners

### Recommended Approach

**Option A + B Combined**:

1. Create `pulldb/infra/mysql_utils.py` with `quote_identifier()` and `validate_database_name()`
2. Update all 14 instances to use the utility
3. Add inline comments explaining why f-string is acceptable

### Implementation Plan

#### Phase 1: Create Utility Module (30 min)

```
File: pulldb/infra/mysql_utils.py
```

```python
"""MySQL utility functions for safe identifier handling.

HCA Layer: shared
"""

from __future__ import annotations

import re


# Pattern for valid MySQL identifiers
_IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_$]*$')


def quote_identifier(name: str) -> str:
    """Safely quote a MySQL identifier.
    
    Args:
        name: Database, table, or column name.
        
    Returns:
        Backtick-quoted identifier with internal backticks escaped.
        
    Raises:
        ValueError: If name is empty or exceeds MySQL limits.
    """
    if not name:
        raise ValueError("Identifier cannot be empty")
    if len(name) > 64:
        raise ValueError(f"Identifier exceeds 64 char limit: {name[:20]}...")
    
    # Escape backticks by doubling them
    escaped = name.replace("`", "``")
    return f"`{escaped}`"


def validate_identifier(name: str, kind: str = "identifier") -> str:
    """Validate an identifier matches safe pattern.
    
    Args:
        name: The identifier to validate.
        kind: Description for error messages (e.g., "database", "user").
        
    Returns:
        The validated name (unchanged).
        
    Raises:
        ValueError: If name contains invalid characters.
    """
    if not name:
        raise ValueError(f"{kind.title()} name cannot be empty")
    if not _IDENTIFIER_PATTERN.match(name):
        raise ValueError(
            f"Invalid {kind} name '{name}': must contain only "
            "alphanumeric characters, underscores, and dollar signs"
        )
    return name
```

#### Phase 2: Update Instances (2-3 hours)

| File | Line | Current | Updated |
|------|------|---------|---------|
| `mysql_provisioning.py` | 494 | `f"DROP PROCEDURE IF EXISTS {PROCEDURE_NAME}"` | Keep as-is (constant) |
| `mysql_provisioning.py` | 495 | `f"DROP PROCEDURE IF EXISTS {PREVIEW_PROCEDURE_NAME}"` | Keep as-is (constant) |
| `mysql_provisioning.py` | 795 | `f"SHOW GRANTS FOR '{current_username}'@'%%'"` | Use `quote_identifier()` |
| `mysql_provisioning.py` | 822 | `f"DROP USER '{current_username}'@'%%'"` | Use `validate_identifier()` |
| `mysql_provisioning.py` | 930 | `f"DROP USER IF EXISTS '{user_to_drop}'@'%%'"` | Use `validate_identifier()` |
| `staging.py` | 292 | `f"DROP DATABASE IF EXISTS \`{orphan_db}\`"` | Use `quote_identifier()` |
| `admin_tasks.py` | 398 | `f"DROP DATABASE IF EXISTS \`{db_name}\`"` | Use `quote_identifier()` |
| `atomic_rename.py` | 268, 341 | `f"SHOW CREATE PROCEDURE {proc_schema}.{RENAME_PROCEDURE_NAME}"` | Keep (constants) |
| `cleanup.py` | 588, 655, 2347, 2706 | `f"DROP DATABASE IF EXISTS \`{db_name}\`"` | Use `quote_identifier()` |
| `executor.py` | 193 | `f"SHOW TABLES IN \`{job.target}\` LIKE 'pullDB'"` | Use `quote_identifier()` |

#### Phase 3: Add Tests (1 hour)

```python
# tests/unit/infra/test_mysql_utils.py

def test_quote_identifier_simple():
    assert quote_identifier("my_db") == "`my_db`"

def test_quote_identifier_with_backtick():
    assert quote_identifier("test`db") == "`test``db`"

def test_quote_identifier_empty_raises():
    with pytest.raises(ValueError):
        quote_identifier("")

def test_validate_identifier_valid():
    assert validate_identifier("my_database_123") == "my_database_123"

def test_validate_identifier_invalid():
    with pytest.raises(ValueError):
        validate_identifier("test; DROP TABLE users;--")
```

### Acceptance Criteria

- [ ] `mysql_utils.py` created with `quote_identifier()` and `validate_identifier()`
- [ ] All 14 instances reviewed and updated where appropriate
- [ ] Unit tests pass with 100% coverage of new module
- [ ] No security scanner warnings on updated code
- [ ] Documentation updated in code comments

---

## M2: Any Return Types

### Problem Statement

28 instances return `Any` type, reducing type safety and IDE support.

### Categorization

| Category | Count | Files | Fixable? |
|----------|-------|-------|----------|
| **boto3 Clients** | 5 | `s3.py`, `secrets.py`, `secrets_commands.py` | No (boto3 limitation) |
| **Factory Functions** | 5 | `factory.py` | Yes (define Protocols) |
| **Starlette Responses** | 11 | `auth/routes.py`, `restore/routes.py` | Partial (use Response union) |
| **Internal Helpers** | 4 | `main.py`, `service.py`, etc. | Yes |
| **Protocol Methods** | 3 | `interfaces.py` | Yes (define return type) |

### Solution by Category

#### Category A: boto3 Clients (Keep Any)

**Rationale**: boto3 uses dynamic client generation. The official `boto3-stubs` package provides types but adds significant dependency overhead.

**Recommendation**: Keep `-> Any` with inline comment:

```python
def _get_secrets_manager_client(self) -> Any:
    """Get boto3 Secrets Manager client.
    
    Returns:
        boto3.client('secretsmanager') - typed as Any due to boto3's
        dynamic client generation. Consider boto3-stubs for strict typing.
    """
```

**Decision**: NO ACTION (acceptable)

#### Category B: Factory Functions (Define Protocols)

**Files**: `pulldb/infra/factory.py`

**Current**:
```python
def get_auth_repository() -> Any:
def get_disallowed_user_repository() -> Any:
def get_audit_repository() -> Any:
def get_provisioning_service(actor_user_id: str) -> Any:
def _get_real_mysql_pool() -> Any:
```

**Solution**: Define Protocol interfaces in `pulldb/domain/interfaces.py`:

```python
# Add to interfaces.py

class AuthRepository(Protocol):
    """Protocol for authentication repository."""
    
    def get_password_hash(self, user_id: str) -> str | None:
        """Get stored password hash for user."""
        ...
    
    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        """Set password hash for user."""
        ...
    
    def create_session(self, user_id: str, session_token: str) -> None:
        """Create a new session."""
        ...
    
    def get_session(self, session_token: str) -> dict[str, Any] | None:
        """Get session by token."""
        ...
    
    def delete_session(self, session_token: str) -> None:
        """Delete a session."""
        ...


class DisallowedUserRepository(Protocol):
    """Protocol for disallowed username checks."""
    
    def is_disallowed(self, username: str) -> bool:
        """Check if username is disallowed."""
        ...


class AuditRepository(Protocol):
    """Protocol for audit logging."""
    
    def log_action(
        self,
        actor_user_id: str,
        action: str,
        target_user_id: str | None = None,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Log an audit action, return audit_id."""
        ...
    
    def get_audit_logs(
        self,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get audit logs with optional filtering."""
        ...
```

**Implementation Steps**:

1. Add Protocol definitions to `interfaces.py` (30 min)
2. Update `factory.py` return types (15 min)
3. Verify implementations satisfy Protocols (15 min)

#### Category C: Starlette Responses (Use Union Type)

**Files**: `pulldb/web/features/auth/routes.py` (11 instances)

**Current**:
```python
async def login_page(...) -> Any:
async def login_submit(...) -> Any:
```

**Problem**: Routes can return `HTMLResponse`, `RedirectResponse`, or `TemplateResponse`.

**Solution**: Create response type alias:

```python
# pulldb/web/shared/types.py

from starlette.responses import HTMLResponse, RedirectResponse, Response
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

# Union of all possible web route responses
WebResponse = HTMLResponse | RedirectResponse | Response | JSONResponse
```

**Then update routes**:
```python
from pulldb.web.shared.types import WebResponse

async def login_page(...) -> WebResponse:
```

**Note**: This is a style improvement. FastAPI handles response types automatically, so `-> Any` is functionally acceptable.

**Decision**: OPTIONAL improvement

#### Category D: Internal Helpers (Fix)

| Function | File | Better Return Type |
|----------|------|-------------------|
| `_parse_json_response` | `cli/main.py` | `dict[str, Any]` |
| `_get_aws_session` | `cli/secrets_commands.py` | Keep `Any` (boto3) |
| `_build_job_repository` | `worker/service.py` | `JobRepository` |
| `_connect` | `worker/processlist_monitor.py` | Keep `Any` (mysql.connector) |

#### Category E: Protocol Methods (Fix)

**File**: `pulldb/domain/interfaces.py`

```python
# Line 396, 411: CredentialResolver methods
def resolve_target_credentials(...) -> Any:
def get_host_credentials(...) -> Any:
```

**Solution**: Define `MySQLCredentials` as return type (already exists in domain/models):

```python
def resolve_target_credentials(
    self, dbhost: str, dbhost_obj: DBHost | None = None
) -> MySQLCredentials:
    """Resolve MySQL credentials for a target host."""
    ...

def get_host_credentials(self, hostname: str) -> MySQLCredentials:
    """Get MySQL credentials by hostname."""
    ...
```

### Implementation Plan

#### Phase 1: Add Protocol Definitions (1 hour)

Update `pulldb/domain/interfaces.py`:
- Add `AuthRepository` Protocol
- Add `DisallowedUserRepository` Protocol  
- Add `AuditRepository` Protocol
- Fix `CredentialResolver` return types

#### Phase 2: Update Factory Functions (30 min)

Update `pulldb/infra/factory.py`:
- Import new Protocols
- Update return type annotations
- Verify no Pylance errors

#### Phase 3: Fix Internal Helpers (30 min)

- `cli/main.py`: `_parse_json_response() -> dict[str, Any]`
- `worker/service.py`: `_build_job_repository() -> JobRepository`

#### Phase 4: Document Acceptable Any Usage (15 min)

Add comments to remaining `-> Any` explaining why:
- boto3 clients: dynamic typing
- mysql.connector: cursor types
- Starlette responses: optional improvement

### Acceptance Criteria

- [ ] New Protocols defined in `interfaces.py`
- [ ] Factory functions return Protocol types
- [ ] Internal helpers have proper return types
- [ ] Remaining `Any` usage documented
- [ ] Pylance reports 0 errors
- [ ] All tests pass

---

## M3: Broad Exception Handlers

### Problem Statement

42 files contain `except Exception:` blocks, which can mask bugs by catching unexpected errors.

### Categorization

After analysis, these fall into categories:

| Category | Count | Action |
|----------|-------|--------|
| **Logging + Re-raise** | ~60% | ACCEPTABLE |
| **Graceful Degradation** | ~25% | ACCEPTABLE |
| **Silent Swallow** | ~10% | NEEDS REVIEW |
| **Defensive Catch-All** | ~5% | DOCUMENT |

### Analysis Framework

For each `except Exception:` block, evaluate:

1. **Does it log the error?** (exc_info=True)
2. **Does it re-raise or return error state?**
3. **Is it protecting user-facing code?**
4. **What specific exceptions could occur?**

### Files Requiring Review

After manual review, these files have potentially problematic patterns:

#### High Priority (Silent Swallow)

| File | Line | Pattern | Action |
|------|------|---------|--------|
| `cli/settings.py` | ~50 | `except Exception: pass` | Add logging |
| `domain/config.py` | ~200 | Silent config fallback | Add logging |
| `worker/profiling.py` | ~80 | Silent metric skip | Add logging |

#### Medium Priority (Consider Narrowing)

| File | Pattern | Recommendation |
|------|---------|----------------|
| `infra/s3.py` | Catch-all for boto3 | Catch `ClientError` specifically |
| `infra/secrets.py` | Catch-all for boto3 | Catch `ClientError` specifically |
| `worker/cleanup.py` | Multiple broad catches | Review case-by-case |

#### Acceptable (No Action)

Most handlers that:
- Log with `exc_info=True`
- Re-raise after logging
- Are in user-facing routes (return error page)

### Implementation Plan

#### Phase 1: Audit Pass (2 hours)

Create checklist for each file, marking:
- [ ] Logs error
- [ ] Re-raises or returns error
- [ ] Specific exceptions possible
- [ ] Action needed

#### Phase 2: Fix High Priority (1 hour)

Add logging to silent catches:

```python
# Before
except Exception:
    pass

# After
except Exception:
    logger.debug("Optional operation failed, continuing", exc_info=True)
```

#### Phase 3: Narrow boto3 Exceptions (1 hour)

```python
# Before
from botocore.exceptions import ClientError

try:
    result = client.get_object(...)
except Exception as e:
    logger.error("S3 error", exc_info=True)

# After
try:
    result = client.get_object(...)
except ClientError as e:
    logger.error("S3 client error: %s", e.response.get("Error", {}))
except Exception as e:
    logger.error("Unexpected S3 error", exc_info=True)
    raise
```

### Acceptance Criteria

- [ ] All `except Exception: pass` patterns have logging added
- [ ] boto3 operations catch `ClientError` specifically
- [ ] Remaining broad catches documented as intentional
- [ ] No regressions in error handling tests

---

## Implementation Schedule

| Week | Day | Task | Effort |
|------|-----|------|--------|
| 1 | Mon | M1 Phase 1: Create mysql_utils.py | 1h |
| 1 | Mon | M1 Phase 2: Update 14 instances | 2h |
| 1 | Tue | M1 Phase 3: Add tests | 1h |
| 1 | Wed | M2 Phase 1: Add Protocol definitions | 1h |
| 1 | Wed | M2 Phase 2: Update factory functions | 0.5h |
| 1 | Thu | M2 Phase 3-4: Helpers + documentation | 1h |
| 1 | Fri | M3 Phase 1: Audit pass | 2h |
| 2 | Mon | M3 Phase 2-3: Fix high priority + boto3 | 2h |
| 2 | Tue | Final review and documentation | 1h |

**Total: 11.5 hours across 6 working days**

---

## Appendix A: File Inventory

### M1: f-string SQL Locations

| # | File | Line | SQL Pattern |
|---|------|------|-------------|
| 1 | `infra/mysql_provisioning.py` | 494 | `DROP PROCEDURE IF EXISTS {PROCEDURE_NAME}` |
| 2 | `infra/mysql_provisioning.py` | 495 | `DROP PROCEDURE IF EXISTS {PREVIEW_PROCEDURE_NAME}` |
| 3 | `infra/mysql_provisioning.py` | 795 | `SHOW GRANTS FOR '{current_username}'@'%%'` |
| 4 | `infra/mysql_provisioning.py` | 822 | `DROP USER '{current_username}'@'%%'` |
| 5 | `infra/mysql_provisioning.py` | 930 | `DROP USER IF EXISTS '{user_to_drop}'@'%%'` |
| 6 | `worker/staging.py` | 292 | `DROP DATABASE IF EXISTS \`{orphan_db}\`` |
| 7 | `worker/admin_tasks.py` | 398 | `DROP DATABASE IF EXISTS \`{db_name}\`` |
| 8 | `worker/atomic_rename.py` | 268 | `SHOW CREATE PROCEDURE {proc_schema}.{RENAME_PROCEDURE_NAME}` |
| 9 | `worker/atomic_rename.py` | 341 | `SHOW CREATE PROCEDURE {proc_schema}.{RENAME_PROCEDURE_NAME}` |
| 10 | `worker/cleanup.py` | 588 | `DROP DATABASE IF EXISTS \`{db_name}\`` |
| 11 | `worker/cleanup.py` | 655 | `DROP DATABASE IF EXISTS \`{db_name}\`` |
| 12 | `worker/cleanup.py` | 2347 | `DROP DATABASE IF EXISTS \`{db_name}\`` |
| 13 | `worker/cleanup.py` | 2706 | `DROP DATABASE IF EXISTS \`{db_name}\`` |
| 14 | `worker/executor.py` | 193 | `SHOW TABLES IN \`{job.target}\` LIKE 'pullDB'` |

### M2: Any Return Type Locations

| # | File | Line | Function | Fixable |
|---|------|------|----------|---------|
| 1 | `infra/s3.py` | 214 | `_create_client` | No (boto3) |
| 2 | `infra/s3.py` | 248 | `get_client` | No (boto3) |
| 3 | `infra/secrets.py` | 120 | `_get_secrets_manager_client` | No (boto3) |
| 4 | `infra/secrets.py` | 141 | `_get_ssm_client` | No (boto3) |
| 5 | `infra/factory.py` | 72 | `get_auth_repository` | Yes |
| 6 | `infra/factory.py` | 126 | `get_disallowed_user_repository` | Yes |
| 7 | `infra/factory.py` | 135 | `get_audit_repository` | Yes |
| 8 | `infra/factory.py` | 151 | `get_provisioning_service` | Partial |
| 9 | `infra/factory.py` | 186 | `_get_real_mysql_pool` | Partial |
| 10-19 | `web/features/auth/routes.py` | Various | Route handlers | Optional |
| 20 | `web/features/restore/routes.py` | 300 | Route handler | Optional |
| 21 | `web/features/dashboard/routes.py` | 20 | `_get_user_last_job` | Yes |
| 22 | `cli/main.py` | 530 | `_parse_json_response` | Yes |
| 23 | `cli/secrets_commands.py` | 50 | `_get_aws_session` | No (boto3) |
| 24 | `cli/secrets_commands.py` | 60 | Helper | No (boto3) |
| 25 | `domain/interfaces.py` | 396 | Protocol method | Yes |
| 26 | `domain/interfaces.py` | 411 | Protocol method | Yes |
| 27 | `domain/interfaces.py` | 714 | Protocol method | Yes |
| 28 | `worker/service.py` | 170 | `_build_job_repository` | Yes |

### M3: Broad Exception Handler Files

<details>
<summary>Click to expand full file list (42 files)</summary>

1. `pulldb/api/logic.py`
2. `pulldb/api/main.py`
3. `pulldb/auth/password.py`
4. `pulldb/cli/admin.py`
5. `pulldb/cli/admin_commands.py`
6. `pulldb/cli/auth.py`
7. `pulldb/cli/backup_commands.py`
8. `pulldb/cli/main.py`
9. `pulldb/cli/secrets_commands.py`
10. `pulldb/cli/settings.py`
11. `pulldb/domain/config.py`
12. `pulldb/domain/services/discovery.py`
13. `pulldb/domain/services/provisioning.py`
14. `pulldb/domain/services/secret_rotation.py`
15. `pulldb/infra/bootstrap.py`
16. `pulldb/infra/css_writer.py`
17. `pulldb/infra/exec.py`
18. `pulldb/infra/mysql.py`
19. `pulldb/infra/mysql_provisioning.py`
20. `pulldb/infra/s3.py`
21. `pulldb/infra/secrets.py`
22. `pulldb/simulation/core/bus.py`
23. `pulldb/web/dependencies.py`
24. `pulldb/web/features/admin/routes.py`
25. `pulldb/web/features/audit/routes.py`
26. `pulldb/web/features/auth/routes.py`
27. `pulldb/web/features/jobs/routes.py`
28. `pulldb/web/features/manager/routes.py`
29. `pulldb/web/features/requests/routes.py`
30. `pulldb/web/features/restore/routes.py`
31. `pulldb/worker/admin_tasks.py`
32. `pulldb/worker/backup_metadata.py`
33. `pulldb/worker/cleanup.py`
34. `pulldb/worker/downloader.py`
35. `pulldb/worker/dump_metadata.py`
36. `pulldb/worker/executor.py`
37. `pulldb/worker/heartbeat.py`
38. `pulldb/worker/loop.py`
39. `pulldb/worker/metadata_synthesis.py`
40. `pulldb/worker/processlist_monitor.py`
41. `pulldb/worker/profiling.py`
42. `pulldb/worker/restore.py`
43. `pulldb/worker/service.py`

</details>

---

## Appendix B: Code Templates

### Template: quote_identifier()

```python
from pulldb.infra.mysql_utils import quote_identifier

# Before
cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")

# After
cursor.execute(f"DROP DATABASE IF EXISTS {quote_identifier(db_name)}")
```

### Template: Protocol Definition

```python
from typing import Protocol

class MyRepository(Protocol):
    """Protocol for XYZ operations."""
    
    def get_by_id(self, id: str) -> MyModel | None:
        """Get item by ID."""
        ...
    
    def save(self, item: MyModel) -> str:
        """Save item, return ID."""
        ...
```

### Template: Narrow Exception

```python
from botocore.exceptions import ClientError

try:
    result = s3_client.get_object(Bucket=bucket, Key=key)
except ClientError as e:
    error_code = e.response.get("Error", {}).get("Code", "Unknown")
    if error_code == "NoSuchKey":
        logger.info("Object not found: %s/%s", bucket, key)
        return None
    logger.error("S3 ClientError: %s", error_code, exc_info=True)
    raise
except Exception as e:
    logger.error("Unexpected error accessing S3", exc_info=True)
    raise
```

---

## Appendix C: Decision Matrix

### When to Keep `-> Any`

| Scenario | Keep Any? | Reason |
|----------|-----------|--------|
| boto3 client return | ✅ Yes | Dynamic types, no stubs |
| mysql.connector cursor | ✅ Yes | Complex cursor typing |
| Starlette Response | ⚠️ Optional | Works but union is cleaner |
| Internal helper | ❌ No | Define proper type |
| Protocol method | ❌ No | Use domain model type |

### When to Keep `except Exception:`

| Scenario | Keep Broad? | Reason |
|----------|-------------|--------|
| Logs with exc_info=True | ✅ Yes | Error captured |
| Re-raises after log | ✅ Yes | Error propagated |
| User-facing route | ✅ Yes | Graceful degradation |
| Silent pass | ❌ No | Masks bugs |
| Could catch specific | ⚠️ Review | Prefer specific |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-01-20 | GitHub Copilot | Initial research plans |
