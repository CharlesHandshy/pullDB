# Phase 4 Implementation Plan

## Web Interface & Enhanced Authentication

**Version**: 0.1.0 (Planning Draft)  
**Last Updated**: 2025-11-29  
**Status**: Planning - Pre-Implementation

---

## Executive Summary

Phase 4 transforms pullDB from a CLI-only tool to a multi-interface system with:
- **Web Interface**: Browser-based job management
- **RBAC**: Role-based access control (admin/manager/user)
- **Enhanced Authentication**: Password login, sessions, optional 2FA

### Design Principles

1. **Minimal Disruption**: Additive changes only—no variable renames, no breaking refactors
2. **Backward Compatibility**: CLI continues working unchanged during and after transition
3. **Incremental Rollout**: Feature flags enable gradual activation
4. **Preserve Test Suite**: 328 existing tests must continue passing

---

## Current State Analysis

### Existing Authentication Flow

```
CLI (pulldb restore) → _get_calling_username() → SUDO_USER/USER env
                                ↓
API (POST /api/jobs) → req.user field → get_or_create_user()
                                ↓
Worker → MySQL credentials only (no user auth)
```

**Key Observations**:
- No API authentication middleware
- API trusts `user` field in request body
- CLI uses trusted wrapper pattern (sudoers)
- Worker is isolated—uses MySQL credentials only

### Current Schema (auth_users)

```sql
CREATE TABLE auth_users (
    user_id CHAR(36) PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    user_code CHAR(6) NOT NULL UNIQUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    disabled_at TIMESTAMP(6) NULL
);
```

### Current User Model

```python
@dataclass(frozen=True)
class User:
    user_id: str
    username: str
    user_code: str
    is_admin: bool
    created_at: datetime
    disabled_at: datetime | None = None
```

### is_admin Usage Locations

| File | Usage | Impact |
|------|-------|--------|
| `domain/models.py` | User dataclass field | Add `role` field alongside |
| `infra/mysql.py` | UserRepository queries | Add `role` to SELECT/INSERT |
| `api/main.py` | UserInfoResponse | Add `role` to response |
| `cli/admin_commands.py` | Display formatting | Add role display |
| `tests/test_user_repository.py` | Test fixtures | Update test data |

---

## Implementation Phases

### Phase 4a: Schema Changes (Additive)

**Goal**: Add new tables and columns without breaking existing functionality.

#### New Migration Files

**`schema/pulldb_service/070_auth_users_role.sql`**
```sql
-- 070_auth_users_role.sql
-- Add role column to auth_users (additive, non-breaking)

ALTER TABLE auth_users 
ADD COLUMN role ENUM('user', 'manager', 'admin') NOT NULL DEFAULT 'user'
AFTER is_admin;

-- Backfill: admin users get 'admin' role
UPDATE auth_users SET role = 'admin' WHERE is_admin = TRUE;
```

**`schema/pulldb_service/071_auth_credentials.sql`**
```sql
-- 071_auth_credentials.sql
-- Password and 2FA storage for web authentication

CREATE TABLE auth_credentials (
    user_id CHAR(36) PRIMARY KEY,
    password_hash VARCHAR(255) NULL,  -- bcrypt hash, NULL = no password set
    totp_secret VARCHAR(64) NULL,     -- Base32 encoded TOTP secret
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_credentials_user FOREIGN KEY (user_id) 
        REFERENCES auth_users(user_id) ON DELETE CASCADE
);
```

**`schema/pulldb_service/072_sessions.sql`**
```sql
-- 072_sessions.sql
-- Session management for web authentication

CREATE TABLE sessions (
    session_id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    token_hash CHAR(64) NOT NULL,  -- SHA-256 of session token
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at TIMESTAMP(6) NOT NULL,
    last_activity TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ip_address VARCHAR(45) NULL,   -- IPv4 or IPv6
    user_agent VARCHAR(255) NULL,
    CONSTRAINT fk_session_user FOREIGN KEY (user_id) 
        REFERENCES auth_users(user_id) ON DELETE CASCADE,
    INDEX idx_sessions_user (user_id),
    INDEX idx_sessions_expires (expires_at)
);
```

### Phase 4b: Domain Model Updates

**Goal**: Extend User model without breaking existing code.

#### User Model Changes (`domain/models.py`)

```python
class UserRole(Enum):
    """User role for RBAC.
    
    Values correspond to auth_users.role ENUM in database.
    """
    USER = "user"
    MANAGER = "manager"  
    ADMIN = "admin"


@dataclass(frozen=True)
class User:
    """User entity from auth_users table."""
    
    user_id: str
    username: str
    user_code: str
    is_admin: bool  # KEEP for backward compatibility
    role: UserRole  # NEW: RBAC role
    created_at: datetime
    disabled_at: datetime | None = None
    
    @property
    def is_manager_or_above(self) -> bool:
        """Check if user has manager or admin role."""
        return self.role in (UserRole.MANAGER, UserRole.ADMIN)
```

**Migration Strategy**: 
- Add `role` field with default
- Update `_row_to_user()` to read role from database
- Existing tests that create User objects will need `role=UserRole.USER` added

### Phase 4c: Authentication Repository

**Goal**: Create new `AuthRepository` for authentication operations.

#### New Module: `pulldb/auth/repository.py`

```python
"""Authentication repository for password and session management."""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from pulldb.infra.mysql import MySQLPool


class AuthRepository:
    """Repository for authentication operations.
    
    Handles password verification, session creation/validation,
    and 2FA verification. Separate from UserRepository to maintain
    single responsibility.
    """
    
    def __init__(self, pool: MySQLPool) -> None:
        self.pool = pool
    
    def get_password_hash(self, user_id: str) -> Optional[str]:
        """Get stored password hash for user."""
        ...
    
    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        """Set password hash for user."""
        ...
    
    def create_session(
        self, 
        user_id: str, 
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        ttl_hours: int = 24
    ) -> tuple[str, str]:
        """Create new session. Returns (session_id, session_token)."""
        ...
    
    def validate_session(self, session_token: str) -> Optional[str]:
        """Validate session token. Returns user_id if valid, None otherwise."""
        ...
    
    def invalidate_session(self, session_id: str) -> None:
        """Invalidate a session (logout)."""
        ...
    
    def invalidate_all_user_sessions(self, user_id: str) -> int:
        """Invalidate all sessions for user. Returns count invalidated."""
        ...
```

### Phase 4d: API Authentication Middleware

**Goal**: Add optional authentication to API without breaking CLI.

#### Authentication Mode Configuration

```python
# Environment variable: PULLDB_AUTH_MODE
# Values: 'trusted' (default), 'session', 'both'
#
# trusted: Accept X-Trusted-User header (CLI mode)
# session: Require session token (web mode)
# both: Accept either (transition mode)
```

#### API Authentication Dependency (`api/auth.py`)

```python
"""FastAPI authentication dependencies."""

from fastapi import Depends, Header, HTTPException, status
from typing import Optional

from pulldb.domain.models import User


async def get_current_user(
    x_trusted_user: Optional[str] = Header(None),
    x_session_token: Optional[str] = Header(None),
    state: "APIState" = Depends(get_api_state),
) -> User:
    """Resolve current user from request headers.
    
    Authentication modes (PULLDB_AUTH_MODE):
    - 'trusted': Only X-Trusted-User header (CLI)
    - 'session': Only X-Session-Token header (web)
    - 'both': Accept either (transition)
    
    Returns:
        Authenticated User object.
        
    Raises:
        HTTPException 401: Invalid or missing authentication.
    """
    auth_mode = os.getenv("PULLDB_AUTH_MODE", "trusted")
    
    if auth_mode == "trusted" or auth_mode == "both":
        if x_trusted_user:
            user = state.user_repo.get_user_by_username(x_trusted_user)
            if user and not user.disabled_at:
                return user
    
    if auth_mode == "session" or auth_mode == "both":
        if x_session_token:
            user_id = state.auth_repo.validate_session(x_session_token)
            if user_id:
                user = state.user_repo.get_user_by_id(user_id)
                if user and not user.disabled_at:
                    return user
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )
```

#### CLI Changes (Minimal)

```python
# cli/main.py - Add header to requests

def _api_headers() -> dict[str, str]:
    """Build API request headers with authentication."""
    return {
        "X-Trusted-User": _get_calling_username(),
        "Content-Type": "application/json",
    }
```

### Phase 4e: RBAC Enforcement

**Goal**: Add role-based permission checks.

#### Permission Matrix

| Operation | user | manager | admin |
|-----------|------|---------|-------|
| Submit own job | ✅ | ✅ | ✅ |
| View own jobs | ✅ | ✅ | ✅ |
| Cancel own job | ✅ | ✅ | ✅ |
| View all jobs | ❌ | ✅ (read) | ✅ |
| Cancel any job | ❌ | ✅ | ✅ |
| Submit for others | ❌ | ✅ | ✅ |
| Manage users | ❌ | ❌ | ✅ |
| System config | ❌ | ❌ | ✅ |

#### Permission Helpers (`domain/permissions.py`)

```python
"""RBAC permission checks."""

from pulldb.domain.models import User, UserRole


def can_view_job(user: User, job_owner_id: str) -> bool:
    """Check if user can view a specific job."""
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.MANAGER:
        return True  # Managers can view all
    return user.user_id == job_owner_id


def can_cancel_job(user: User, job_owner_id: str) -> bool:
    """Check if user can cancel a specific job."""
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.MANAGER:
        return True  # Managers can cancel any
    return user.user_id == job_owner_id


def can_submit_for_user(actor: User, target_user_id: str) -> bool:
    """Check if actor can submit jobs for target user."""
    if actor.role == UserRole.ADMIN:
        return True
    if actor.role == UserRole.MANAGER:
        return True
    return actor.user_id == target_user_id


def can_manage_users(user: User) -> bool:
    """Check if user can manage other users."""
    return user.role == UserRole.ADMIN
```

### Phase 4f: Web UI (Simple)

**Goal**: Basic web interface using Jinja2 + HTMX.

#### Project Structure

```
pulldb/
├── web/
│   ├── __init__.py
│   ├── routes.py         # FastAPI routes for web pages
│   ├── templates/
│   │   ├── base.html     # Base template with nav
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   ├── jobs.html
│   │   ├── history.html
│   │   └── components/
│   │       ├── job_row.html
│   │       └── status_badge.html
│   └── static/
│       ├── styles.css
│       └── htmx.min.js
```

#### Dependencies to Add

```toml
# pyproject.toml additions
dependencies = [
    ...
    "jinja2>=3.1.0",
    "python-multipart>=0.0.9",  # Form handling
    "passlib[bcrypt]>=1.7.4",   # Password hashing
    "pyotp>=2.9.0",             # TOTP 2FA
]
```

---

## Migration Strategy

### Step 1: Schema Migration (Zero Downtime)

1. Run migrations during low-traffic window
2. `070_auth_users_role.sql` - Adds column with default
3. `071_auth_credentials.sql` - New table, no impact
4. `072_sessions.sql` - New table, no impact

### Step 2: Code Deployment (Backward Compatible)

1. Deploy with `PULLDB_AUTH_MODE=trusted` (default)
2. All existing CLIs continue working
3. New web routes available but not publicly linked

### Step 3: Web UI Activation

1. Set `PULLDB_AUTH_MODE=both`
2. Create admin password via admin CLI
3. Enable web UI routes
4. Monitor for issues

### Step 4: Full Transition (Optional)

1. Migrate all users to password auth
2. Set `PULLDB_AUTH_MODE=session`
3. CLI updated to use session tokens

---

## Test Coverage Estimates

| Category | New Tests | Description |
|----------|-----------|-------------|
| Auth Repository | 20 | Session CRUD, password verify |
| RBAC Permissions | 15 | Role-based checks |
| API Auth Middleware | 15 | Header parsing, mode switching |
| Web Routes | 10 | Login, logout, dashboard |
| Integration | 10 | End-to-end flows |
| **Total** | **70** | |

### Existing Tests Impact

- **328 existing tests**: All must pass
- **User fixture updates**: Add `role=UserRole.USER` where User is constructed
- **API tests**: May need `X-Trusted-User` header if mode changes

---

## File Change Summary

### New Files

| Path | Purpose |
|------|---------|
| `schema/pulldb_service/070_auth_users_role.sql` | Role column migration |
| `schema/pulldb_service/071_auth_credentials.sql` | Credentials table |
| `schema/pulldb_service/072_sessions.sql` | Sessions table |
| `pulldb/auth/__init__.py` | Auth module init |
| `pulldb/auth/repository.py` | AuthRepository |
| `pulldb/auth/password.py` | Password hashing |
| `pulldb/domain/permissions.py` | RBAC helpers |
| `pulldb/api/auth.py` | API auth middleware |
| `pulldb/web/__init__.py` | Web module init |
| `pulldb/web/routes.py` | Web page routes |
| `pulldb/web/templates/*.html` | Jinja2 templates |
| `pulldb/tests/test_auth_repository.py` | Auth tests |
| `pulldb/tests/test_permissions.py` | RBAC tests |

### Modified Files

| Path | Changes |
|------|---------|
| `domain/models.py` | Add UserRole enum, role field |
| `infra/mysql.py` | Update _row_to_user(), add role to queries |
| `api/main.py` | Add auth dependency, web routes mount |
| `cli/main.py` | Add X-Trusted-User header to requests |
| `pyproject.toml` | Add new dependencies |
| `requirements.txt` | Add new dependencies |

### Unchanged Files

| Path | Reason |
|------|--------|
| `worker/service.py` | Worker uses MySQL auth only |
| `worker/executor.py` | No user context needed |
| `infra/secrets.py` | Separate credential system |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Break CLI during transition | Feature flag with `trusted` default |
| Session token leaks | Use SHA-256 hash storage, short TTL |
| Password storage breach | bcrypt with 12 rounds, no plaintext |
| Role escalation | Database constraint on ENUM values |
| Test suite regression | Run full suite before each commit |

---

## Success Criteria

1. ✅ All 328 existing tests pass
2. ✅ CLI works unchanged with `PULLDB_AUTH_MODE=trusted`
3. ✅ Web login works with `PULLDB_AUTH_MODE=session`
4. ✅ RBAC prevents unauthorized operations
5. ✅ Sessions expire after configured TTL
6. ✅ No breaking changes to API contracts

---

## Next Steps

1. **Review this document** with team
2. **Create feature branch** `feature/phase-4-auth`
3. **Start Phase 4a** (schema changes)
4. **Iterate through phases** with tests at each step
5. **Update roadmap** on completion
