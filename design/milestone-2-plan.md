# Milestone 2: MySQL Repository Layer - Detailed Plan

> **Status**: Ready to begin implementation
> **Prerequisites**: Milestone 1 complete (28/28 tests passing)
> **Duration**: 1-2 weeks
> **Target**: Complete MySQL abstraction layer with comprehensive test coverage

## Overview

Milestone 2 implements the repository pattern for all MySQL operations in pullDB. This layer abstracts database access for both API and Worker services, enforcing business rules at the data access level.

**Key Principles**:
- Repository classes encapsulate all SQL operations
- Domain models (dataclasses) define data structures
- Type hints on all interfaces for mypy validation
- Comprehensive unit tests with test MySQL instances
- Transaction management at repository layer
- Connection pooling for efficiency

## Architecture Context

**Service Usage**:
- **API Service**: Uses JobRepository, UserRepository, HostRepository, SettingsRepository (read-only S3 access for backup listing)
- **Worker Service**: Uses JobRepository, HostRepository, SettingsRepository (full S3 access for downloads)
- **CLI**: Does NOT use repositories - calls API service via HTTP

**Current Foundation** (from Milestone 1):
- `pulldb/infra/mysql.py` (59 lines): Basic MySQLPool with context manager
- `pulldb/infra/secrets.py` (405 lines): CredentialResolver for MySQL credentials
- `pulldb/domain/config.py` (227 lines): Configuration with MySQL settings integration

## Domain Models (New File)

### File: `pulldb/domain/models.py`

**Purpose**: Define dataclasses for all domain entities

**Classes to Implement**:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum

class JobStatus(Enum):
    """Job lifecycle status."""
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETE = "complete"
    CANCELED = "canceled"  # Reserved for Phase 1

@dataclass(frozen=True)
class User:
    """User entity from auth_users table."""
    user_id: str
    username: str
    user_code: str
    is_admin: bool
    created_at: datetime
    disabled_at: Optional[datetime] = None

@dataclass(frozen=True)
class Job:
    """Job entity from jobs table."""
    id: str
    owner_user_id: str
    owner_username: str
    owner_user_code: str
    target: str
    staging_name: str
    dbhost: str
    status: JobStatus
    submitted_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    options_json: Optional[dict] = None
    retry_count: int = 0
    error_detail: Optional[str] = None

@dataclass(frozen=True)
class JobEvent:
    """Job event entity from job_events table."""
    id: int
    job_id: str
    event_type: str
    detail: Optional[str]
    logged_at: datetime

@dataclass(frozen=True)
class DBHost:
    """Database host entity from db_hosts table."""
    id: int
    hostname: str
    credential_ref: str
    max_concurrent_restores: int
    enabled: bool
    created_at: datetime

@dataclass(frozen=True)
class Setting:
    """Setting entity from settings table."""
    setting_key: str
    setting_value: str
    description: Optional[str]
    updated_at: datetime
```

**Tasks**:
- [ ] Create `pulldb/domain/models.py`
- [ ] Implement JobStatus enum
- [ ] Implement User dataclass (frozen=True for immutability)
- [ ] Implement Job dataclass with all fields
- [ ] Implement JobEvent dataclass
- [ ] Implement DBHost dataclass
- [ ] Implement Setting dataclass
- [ ] Add docstrings (Google style) to all classes
- [ ] Add type hints to all fields
- [ ] Import and use datetime, Optional, Enum from standard library

## Repository Classes (Extend Existing File)

### File: `pulldb/infra/mysql.py` (extend from 59 lines)

**Current State**: Basic MySQLPool with context manager

**New Classes to Add**:

#### 1. JobRepository

**Purpose**: Manage job lifecycle and queue operations

**Methods to Implement**:

```python
class JobRepository:
    """Repository for job operations."""
    
    def __init__(self, pool: MySQLPool) -> None:
        """Initialize with connection pool."""
        
    def enqueue_job(self, job: Job) -> str:
        """Insert new job into queue.
        
        Args:
            job: Job to enqueue
            
        Returns:
            job_id of created job
            
        Raises:
            IntegrityError: If per-target exclusivity constraint violated
        """
        
    def get_next_queued_job(self) -> Optional[Job]:
        """Get next queued job (FIFO by submitted_at).
        
        Returns:
            Next queued job or None if queue empty
        """
        
    def get_job_by_id(self, job_id: str) -> Optional[Job]:
        """Get job by ID.
        
        Args:
            job_id: UUID of job
            
        Returns:
            Job or None if not found
        """
        
    def mark_job_running(self, job_id: str) -> None:
        """Mark job as running and set started_at.
        
        Args:
            job_id: UUID of job
            
        Raises:
            ValueError: If job not in queued status
        """
        
    def mark_job_complete(self, job_id: str) -> None:
        """Mark job as complete and set completed_at.
        
        Args:
            job_id: UUID of job
        """
        
    def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark job as failed with error detail.
        
        Args:
            job_id: UUID of job
            error: Error message to store
        """
        
    def get_active_jobs(self) -> list[Job]:
        """Get all active jobs (queued or running).
        
        Returns:
            List of active jobs ordered by submitted_at
        """
        
    def get_jobs_by_user(self, user_id: str) -> list[Job]:
        """Get all jobs for a user.
        
        Args:
            user_id: User UUID
            
        Returns:
            List of jobs ordered by submitted_at DESC
        """
        
    def check_target_exclusivity(self, target: str, dbhost: str) -> bool:
        """Check if target can accept new job (no active jobs).
        
        Args:
            target: Target database name
            dbhost: Target host
            
        Returns:
            True if no active jobs for target, False otherwise
        """
        
    def append_job_event(self, job_id: str, event_type: str, detail: Optional[str] = None) -> None:
        """Append event to job audit log.
        
        Args:
            job_id: UUID of job
            event_type: Type of event (queued, running, failed, etc.)
            detail: Optional detail message
        """
        
    def get_job_events(self, job_id: str) -> list[JobEvent]:
        """Get all events for a job.
        
        Args:
            job_id: UUID of job
            
        Returns:
            List of events ordered by logged_at
        """
```

**Implementation Notes**:
- Use `with self.pool.connection() as conn:` for all operations
- Use parameterized queries (no string interpolation) for SQL injection protection
- Handle `mysql.connector.IntegrityError` for constraint violations
- Convert MySQL rows to domain model dataclasses
- Use `cursor.execute()` with tuple parameters
- Commit transactions after writes
- Use `cursor.fetchone()` for single results, `cursor.fetchall()` for lists
- Convert MySQL TIMESTAMP(6) to Python datetime objects

**Tasks**:
- [ ] Implement JobRepository class
- [ ] Implement enqueue_job with INSERT and auto-generated job_id (UUID)
- [ ] Implement get_next_queued_job with SELECT and ORDER BY submitted_at
- [ ] Implement get_job_by_id with SELECT WHERE id
- [ ] Implement mark_job_running with UPDATE status and started_at
- [ ] Implement mark_job_complete with UPDATE status and completed_at
- [ ] Implement mark_job_failed with UPDATE status, completed_at, error_detail
- [ ] Implement get_active_jobs using active_jobs view
- [ ] Implement get_jobs_by_user with SELECT WHERE owner_user_id
- [ ] Implement check_target_exclusivity with COUNT query
- [ ] Implement append_job_event with INSERT into job_events
- [ ] Implement get_job_events with SELECT WHERE job_id
- [ ] Add comprehensive docstrings to all methods
- [ ] Handle IntegrityError for per-target exclusivity violations

#### 2. UserRepository

**Purpose**: Manage users and user_code generation

**Methods to Implement**:

```python
class UserRepository:
    """Repository for user operations."""
    
    def __init__(self, pool: MySQLPool) -> None:
        """Initialize with connection pool."""
        
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username.
        
        Args:
            username: Username to look up
            
        Returns:
            User or None if not found
        """
        
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID.
        
        Args:
            user_id: User UUID
            
        Returns:
            User or None if not found
        """
        
    def create_user(self, username: str, user_code: str) -> User:
        """Create new user.
        
        Args:
            username: Username
            user_code: Generated user code (6 chars)
            
        Returns:
            Created user
            
        Raises:
            IntegrityError: If username or user_code already exists
        """
        
    def get_or_create_user(self, username: str) -> User:
        """Get existing user or create new one with generated user_code.
        
        Args:
            username: Username
            
        Returns:
            User (existing or newly created)
            
        Raises:
            ValueError: If user_code cannot be generated (collision limit exceeded)
        """
        
    def generate_user_code(self, username: str) -> str:
        """Generate unique 6-character user code from username.
        
        Algorithm:
        1. Extract first 6 alphabetic characters (lowercase, letters only)
        2. Check if code is unique in database
        3. If collision, replace 6th char with next unused letter from username
        4. If still collision, try 5th char, then 4th char (max 3 adjustments)
        5. Fail if unique code cannot be generated
        
        Args:
            username: Username to generate code from
            
        Returns:
            Unique 6-character code
            
        Raises:
            ValueError: If unique code cannot be generated or username has < 6 letters
        """
        
    def check_user_code_exists(self, user_code: str) -> bool:
        """Check if user_code already exists.
        
        Args:
            user_code: Code to check
            
        Returns:
            True if exists, False otherwise
        """
```

**User Code Generation Algorithm** (Critical Business Logic):

```python
def generate_user_code(self, username: str) -> str:
    """Generate unique 6-character user code."""
    # Step 1: Extract letters only, lowercase
    letters = [c.lower() for c in username if c.isalpha()]
    
    if len(letters) < 6:
        raise ValueError(f"Username '{username}' has insufficient letters (need 6+)")
    
    # Step 2: Try first 6 letters
    base_code = ''.join(letters[:6])
    if not self.check_user_code_exists(base_code):
        return base_code
    
    # Step 3: Collision handling - try replacing positions 5, 4, 3 (indices 5, 4, 3)
    for position in [5, 4, 3]:  # Max 3 adjustments
        # Get unused letters after position
        used_letters = set(base_code[:position+1])
        available = [c for c in letters[position+1:] if c not in used_letters]
        
        for replacement in available:
            candidate = base_code[:position] + replacement + base_code[position+1:]
            if not self.check_user_code_exists(candidate):
                return candidate
    
    # Step 4: All collision strategies exhausted
    raise ValueError(f"Cannot generate unique user_code for '{username}' (collision limit exceeded)")
```

**Tasks**:
- [ ] Implement UserRepository class
- [ ] Implement get_user_by_username with SELECT WHERE username
- [ ] Implement get_user_by_id with SELECT WHERE user_id
- [ ] Implement create_user with INSERT and auto-generated UUID
- [ ] Implement generate_user_code with collision handling algorithm
- [ ] Implement check_user_code_exists with SELECT COUNT query
- [ ] Implement get_or_create_user with transaction (get → generate → create)
- [ ] Add comprehensive docstrings explaining user_code algorithm
- [ ] Handle IntegrityError for duplicate username/user_code

#### 3. HostRepository

**Purpose**: Manage database host configuration and credentials

**Methods to Implement**:

```python
class HostRepository:
    """Repository for database host operations."""
    
    def __init__(self, pool: MySQLPool, credential_resolver: CredentialResolver) -> None:
        """Initialize with connection pool and credential resolver.
        
        Args:
            pool: MySQL connection pool
            credential_resolver: Resolver for AWS credentials
        """
        
    def get_host_by_hostname(self, hostname: str) -> Optional[DBHost]:
        """Get host by hostname.
        
        Args:
            hostname: Hostname to look up
            
        Returns:
            DBHost or None if not found
        """
        
    def get_enabled_hosts(self) -> list[DBHost]:
        """Get all enabled hosts.
        
        Returns:
            List of enabled hosts
        """
        
    def get_host_credentials(self, hostname: str) -> MySQLCredentials:
        """Get resolved MySQL credentials for host.
        
        Args:
            hostname: Hostname to get credentials for
            
        Returns:
            Resolved MySQL credentials
            
        Raises:
            ValueError: If host not found or disabled
            CredentialResolutionError: If credentials cannot be resolved
        """
        
    def check_host_capacity(self, hostname: str) -> bool:
        """Check if host can accept new restore job.
        
        Checks running job count against max_concurrent_restores limit.
        
        Args:
            hostname: Hostname to check
            
        Returns:
            True if host has capacity, False otherwise
        """
```

**Tasks**:
- [ ] Implement HostRepository class
- [ ] Accept CredentialResolver in constructor (from Milestone 1.4)
- [ ] Implement get_host_by_hostname with SELECT WHERE hostname
- [ ] Implement get_enabled_hosts with SELECT WHERE enabled=TRUE
- [ ] Implement get_host_credentials using CredentialResolver.resolve()
- [ ] Implement check_host_capacity with COUNT running jobs query
- [ ] Add docstrings explaining credential resolution integration
- [ ] Handle CredentialResolutionError from secrets module

#### 4. SettingsRepository

**Purpose**: Manage configuration settings

**Methods to Implement**:

```python
class SettingsRepository:
    """Repository for settings operations."""
    
    def __init__(self, pool: MySQLPool) -> None:
        """Initialize with connection pool."""
        
    def get_setting(self, key: str) -> Optional[str]:
        """Get setting value by key.
        
        Args:
            key: Setting key
            
        Returns:
            Setting value or None if not found
        """
        
    def get_setting_required(self, key: str) -> str:
        """Get required setting value.
        
        Args:
            key: Setting key
            
        Returns:
            Setting value
            
        Raises:
            ValueError: If setting not found
        """
        
    def set_setting(self, key: str, value: str, description: Optional[str] = None) -> None:
        """Set setting value (INSERT or UPDATE).
        
        Args:
            key: Setting key
            value: Setting value
            description: Optional description
        """
        
    def get_all_settings(self) -> dict[str, str]:
        """Get all settings as dictionary.
        
        Returns:
            Dictionary mapping keys to values
        """
```

**Tasks**:
- [ ] Implement SettingsRepository class
- [ ] Implement get_setting with SELECT WHERE setting_key
- [ ] Implement get_setting_required with ValueError on missing
- [ ] Implement set_setting with INSERT ... ON DUPLICATE KEY UPDATE
- [ ] Implement get_all_settings with SELECT all rows
- [ ] Add docstrings

## Testing Strategy

### File: `pulldb/tests/test_repositories.py`

**Test Infrastructure**:
- Use real MySQL instance (local development MySQL)
- Create temporary test database for each test class
- Drop test database after tests complete
- Use pytest fixtures for setup/teardown

**Test Structure**:

```python
import pytest
from pulldb.infra.mysql import (
    MySQLPool, JobRepository, UserRepository, 
    HostRepository, SettingsRepository
)
from pulldb.domain.models import Job, JobStatus, User

@pytest.fixture(scope="class")
def test_db():
    """Create temporary test database."""
    # Create test database
    # Yield database name
    # Drop test database

@pytest.fixture
def pool(test_db):
    """Create connection pool to test database."""
    return MySQLPool(
        host="localhost",
        user="root",
        password="",
        database=test_db
    )

class TestJobRepository:
    """Tests for JobRepository."""
    
    def test_enqueue_job(self, pool):
        """Test job enqueue."""
        
    def test_get_next_queued_job(self, pool):
        """Test FIFO queue ordering."""
        
    def test_mark_job_running(self, pool):
        """Test status transition to running."""
        
    def test_mark_job_complete(self, pool):
        """Test status transition to complete."""
        
    def test_mark_job_failed(self, pool):
        """Test status transition to failed with error detail."""
        
    def test_per_target_exclusivity(self, pool):
        """Test unique constraint on active_target_key."""
        
    def test_append_job_event(self, pool):
        """Test event logging."""
        
    def test_get_job_events(self, pool):
        """Test event retrieval."""

class TestUserRepository:
    """Tests for UserRepository."""
    
    def test_generate_user_code_basic(self, pool):
        """Test basic user code generation."""
        
    def test_generate_user_code_collision_6th_char(self, pool):
        """Test collision handling at position 6."""
        
    def test_generate_user_code_collision_5th_char(self, pool):
        """Test collision handling at position 5."""
        
    def test_generate_user_code_collision_4th_char(self, pool):
        """Test collision handling at position 4."""
        
    def test_generate_user_code_exhausted(self, pool):
        """Test failure when all collision strategies exhausted."""
        
    def test_generate_user_code_insufficient_letters(self, pool):
        """Test failure with username < 6 letters."""
        
    def test_get_or_create_user_existing(self, pool):
        """Test get_or_create with existing user."""
        
    def test_get_or_create_user_new(self, pool):
        """Test get_or_create with new user."""

class TestHostRepository:
    """Tests for HostRepository."""
    
    def test_get_host_by_hostname(self, pool):
        """Test host lookup."""
        
    def test_get_host_credentials(self, pool, mock_secrets_manager):
        """Test credential resolution integration."""
        
    def test_check_host_capacity(self, pool):
        """Test capacity checking."""

class TestSettingsRepository:
    """Tests for SettingsRepository."""
    
    def test_get_setting(self, pool):
        """Test setting retrieval."""
        
    def test_set_setting_insert(self, pool):
        """Test setting creation."""
        
    def test_set_setting_update(self, pool):
        """Test setting update."""
        
    def test_get_all_settings(self, pool):
        """Test bulk retrieval."""
```

**Tasks**:
- [ ] Create `pulldb/tests/test_repositories.py`
- [ ] Implement test database fixture with setup/teardown
- [ ] Implement connection pool fixture
- [ ] Write 8+ tests for JobRepository (enqueue, status transitions, exclusivity, events)
- [ ] Write 8+ tests for UserRepository (code generation, collision handling, edge cases)
- [ ] Write 3+ tests for HostRepository (lookup, credentials, capacity)
- [ ] Write 4+ tests for SettingsRepository (get, set, update, bulk)
- [ ] Mock AWS Secrets Manager for HostRepository credential tests
- [ ] Verify all tests pass with pytest
- [ ] Target: 23+ tests, 100% coverage of repository methods

## Integration with Existing Code

### Update `pulldb/domain/config.py`

**Current State**: Configuration loads from environment and MySQL settings

**Changes Needed**:
- [ ] Import SettingsRepository
- [ ] Use SettingsRepository.get_all_settings() instead of raw SQL
- [ ] Simplify _load_settings_from_mysql() method

### Update `pulldb/infra/secrets.py`

**Current State**: CredentialResolver resolves AWS credentials

**No Changes Needed**: HostRepository will use existing CredentialResolver

## Error Handling Standards

**Repository Exception Handling**:
- Wrap `mysql.connector.IntegrityError` with descriptive ValueError
- Wrap `mysql.connector.OperationalError` with descriptive ConnectionError
- Let CredentialResolutionError bubble up from secrets module
- Include context in error messages (job_id, username, hostname, etc.)

**Example**:
```python
try:
    cursor.execute("INSERT INTO jobs ...")
    conn.commit()
except mysql.connector.IntegrityError as e:
    if "idx_jobs_active_target" in str(e):
        raise ValueError(
            f"Target '{target}' on host '{dbhost}' already has an active job"
        ) from e
    raise
```

## Documentation Requirements

**Each Repository Class Needs**:
- [ ] Module-level docstring explaining purpose
- [ ] Class-level docstring with usage example
- [ ] Method docstrings (Google style) with Args, Returns, Raises
- [ ] Type hints on all parameters and return values
- [ ] Inline comments for complex SQL queries
- [ ] Inline comments for business logic (user_code generation, exclusivity checks)

## Completion Criteria

**Definition of Done for Milestone 2**:
- [ ] All 4 repository classes implemented in `pulldb/infra/mysql.py`
- [ ] All domain models implemented in `pulldb/domain/models.py`
- [ ] 23+ tests passing in `pulldb/tests/test_repositories.py`
- [ ] Zero mypy errors (`mypy pulldb/`)
- [ ] Zero ruff errors (`ruff check pulldb/`)
- [ ] All code formatted (`ruff format pulldb/`)
- [ ] Config module updated to use SettingsRepository
- [ ] Documentation complete (docstrings, inline comments)
- [ ] IMPLEMENTATION-PLAN.md updated with completion status
- [ ] Git commit with descriptive message

## Timeline

**Week 1**:
- Day 1: Domain models (`models.py`) - 2-3 hours
- Day 2: JobRepository - 4-6 hours
- Day 3: UserRepository with user_code generation - 4-6 hours
- Day 4: HostRepository + SettingsRepository - 3-4 hours
- Day 5: Test infrastructure setup - 2-3 hours

**Week 2**:
- Day 1-2: JobRepository tests - 4-6 hours
- Day 2-3: UserRepository tests - 4-6 hours
- Day 4: HostRepository + SettingsRepository tests - 3-4 hours
- Day 5: Integration, documentation, cleanup - 2-4 hours

**Total Effort**: 28-42 hours (1-2 weeks)

## Next Steps After Milestone 2

**Ready for Milestone 3** (CLI Implementation):
- CLI can call JobRepository.enqueue_job() to submit jobs
- CLI can call UserRepository.get_or_create_user() for user validation
- CLI can call JobRepository.get_active_jobs() for status command
- CLI can call HostRepository.get_enabled_hosts() to validate dbhost parameter

**Foundation for Milestone 4** (Daemon Core):
- Worker can call JobRepository.get_next_queued_job() to poll queue
- Worker can call JobRepository.mark_job_running() to lock job
- Worker can call JobRepository.append_job_event() to log progress
- Worker can call HostRepository.get_host_credentials() for target database access

## References

- Schema: `docs/mysql-schema.md` - Complete database schema
- Architecture: `.github/copilot-instructions.md` - Repository pattern guidance
- Standards: `constitution.md` - Python coding standards
- Secrets: `pulldb/infra/secrets.py` - CredentialResolver integration
- Config: `pulldb/domain/config.py` - Configuration pattern

---

**Status**: Ready to begin implementation
**Prerequisites**: Milestone 1 complete ✅
**Next Action**: Implement domain models in `pulldb/domain/models.py`
