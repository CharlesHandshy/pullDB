# pullDB Testing Guide

## Overview

pullDB follows a **test-first** development approach with comprehensive unit and integration tests. All tests use AWS Secrets Manager for database credentials per the November 2025 mandate.

**FAIL HARD Principle**: Tests must fail loudly with diagnostic messages when preconditions aren't met. Silent degradation and masked failures are prohibited. See `constitution.md` for complete FAIL HARD philosophy.

## Test Architecture

### FAIL HARD in Tests

Tests implement FAIL HARD by:

1. **Explicit Failures**: When AWS credentials missing or secrets unreachable, tests skip with clear diagnostic messages explaining:
   - What precondition failed
   - Why it failed (root cause)
   - How to fix it (specific commands/configuration)

2. **No Silent Fallbacks**: Tests never silently fall back to hardcoded credentials or empty results
   - ✅ `pytest.skip("AWS credentials not configured. Set AWS_PROFILE=...")`
   - ❌ `return MySQLCredentials("localhost", "root", "")  # Silent fallback`

3. **Actionable Skip Messages**: Every skip includes remediation steps
   - Command to run
   - Configuration to set
   - Documentation link

### Credential Resolution Hierarchy

Tests resolve MySQL credentials in the following order:

1. **AWS Secrets Manager** (preferred): Resolves `/pulldb/mysql/coordination-db` secret
2. **Local Override** (development only): Falls back to environment variables when AWS unavailable
   - Used only when explicitly set by developer
   - Triggers clear skip message for secret residency check
   - Never used in CI or production

### AWS Profile Matrix (Updated Nov 14 2025)

| Profile / Context | Primary Use | Permissions Expected | Notes |
|-------------------|-------------|----------------------|-------|
| *(unset)* (EC2 instance profile) | Default when running directly on the dev EC2 host | `secretsmanager:GetSecretValue`, `DescribeSecret`, `kms:Decrypt`, S3 read scoped via attached policies | **Preferred** for on-box testing. Leave `AWS_PROFILE` unset so boto3 uses the instance metadata credentials automatically. |
| `pr-dev` | Local/off-box development that still needs dev-account secrets | Same as instance profile (Secrets Manager + coordination DB access) | Use for `pytest ... test_secrets.py`, repository/worker/api suites, and any CLI/API run that touches MySQL credentials. |
| `pr-staging` | Access to staging backups in `s3://pestroutesrdsdbs/daily/stg/` | `s3:ListBucket`, `s3:GetObject` on staging bucket | Use only for S3 discovery or manual staging backup inspection. Does **not** have Secrets Manager access. |
| `pr-prod` | Access to production backups in `s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/` | `s3:ListBucket`, `s3:GetObject` on prod bucket via cross-account assume-role | Same pattern as `pr-staging`, but against the production bucket. Never use for dev Secrets Manager operations. |

**Key rules**:

- Secrets (coordination DB credentials, MySQL repositories, etc.) always come from the dev account. Use the instance profile or `pr-dev` only; `pr-staging`/`pr-prod` lack the necessary IAM permissions.
- The optional real S3 listing pytest (`pulldb/tests/test_s3_real_listing_optional.py`) can be run with `AWS_PROFILE=pr-staging` *after* setting `PULLDB_TEST_MYSQL_*` overrides to bypass Secrets Manager fixtures.
- When switching between profiles locally, always reset `AWS_PROFILE`/`PULLDB_AWS_PROFILE` before returning to Secrets Manager-backed tests to avoid AccessDenied skips.

### Test Fixtures

- `aws_region`: Ensures AWS region is set (default: us-east-1)
- `aws_profile`: Determines AWS profile for credential resolution
- `coordination_db_secret`: Secret ID for coordination database
- `verify_secret_residency`: **Validates secret exists only in dev account (345321506926)**
- `mysql_credentials`: Resolves credentials from AWS or local override
- `mysql_pool`: Creates shared connection pool for tests
- `seed_settings`: Ensures required settings rows exist
- `mysql_network_credentials`: Returns (host, user, password) tuple for network login

## Test Environment Setup

### Automated Virtual Environment Creation

pullDB provides `scripts/setup_test_env.sh` for reproducible test environment setup. This script creates a virtual environment with all required testing dependencies.

#### Basic Usage

```bash
# Create default virtual environment (./venv)
bash scripts/setup_test_env.sh

# Create named virtual environment
bash scripts/setup_test_env.sh --venv .venv-test

# Use specific Python version
bash scripts/setup_test_env.sh --python python3.12

# Preview without making changes
bash scripts/setup_test_env.sh --dry-run
```

#### Options Reference

| Option | Description | Default |
|--------|-------------|---------|
| `--venv PATH` | Virtual environment directory | `./venv` |
| `--python INTERPRETER` | Python interpreter to use | `python3` |
| `--refresh` | Delete and recreate if exists | `false` |
| `--dry-run` | Show what would be done | `false` |
| `--freeze` | Generate requirements lockfile | `false` (creates venv) |

#### Dependency Locking for CI

The `--freeze` option generates `requirements-test.txt` with pinned versions for reproducible CI builds:

```bash
# Generate locked requirements
bash scripts/setup_test_env.sh --venv .venv-lock --freeze

# The lockfile is created at: requirements-test.txt
# Use in CI: pip install -r requirements-test.txt
```

#### Package List (17 core + transitive dependencies)

The script installs these packages (see `setup_test_env.sh` for complete list):

- **Type checking**: mypy, mypy-boto3-* (S3, Secrets Manager, SSM)
- **Testing**: pytest, pytest-timeout
- **Linting**: ruff
- **Database**: mysql-connector-python
- **AWS**: boto3, moto (S3 mocking)
- **CLI**: click
- **API**: fastapi, uvicorn
- **Validation**: jsonschema

#### Workflow Examples

**Local development setup**:
```bash
# Initial setup
bash scripts/setup_test_env.sh
source venv/bin/activate

# Run tests
pytest -q --timeout=60 --timeout-method=thread

# Deactivate when done
deactivate
```

**Refresh environment** (after dependency changes):
```bash
bash scripts/setup_test_env.sh --refresh
source venv/bin/activate
```

**CI lockfile update** (when adding/upgrading dependencies):
```bash
# Update setup_test_env.sh with new package
# Regenerate lockfile
bash scripts/setup_test_env.sh --venv .venv-lock --freeze

# Verify lockfile
git diff requirements-test.txt

# Commit if changes are correct
git add requirements-test.txt scripts/setup_test_env.sh
git commit -m "pullDB: dependencies: Update test dependencies"
```

## Running Tests

### Quick Start (Local Development)

When AWS credentials are not configured or secrets are unreachable, tests gracefully skip with informative messages:

```bash
# Run all tests (will skip if AWS not available)
venv/bin/python -m pytest pulldb/tests/

# Run specific test file
venv/bin/python -m pytest pulldb/tests/test_secrets.py -v

# Run with coverage
venv/bin/python -m pytest pulldb/tests/ --cov=pulldb --cov-report=term-missing
```

### Full Integration Tests (AWS Credentials Required)

To run tests with AWS Secrets Manager integration (exercises secret residency check):

```bash
# Option 1: Use instance profile (when running on EC2)
venv/bin/python -m pytest pulldb/tests/ -v

# Option 2: Set AWS profile environment variable
export AWS_PROFILE=default  # or your configured profile
export AWS_DEFAULT_REGION=us-east-1
venv/bin/python -m pytest pulldb/tests/ -v

# Option 3: Set pullDB-specific profile
export PULLDB_AWS_PROFILE=dev-admin
export AWS_DEFAULT_REGION=us-east-1
venv/bin/python -m pytest pulldb/tests/ -v
```

### Local Development Override (Skip AWS)

For completely offline development, set local override variables:

```bash
export PULLDB_TEST_MYSQL_HOST=localhost
export PULLDB_TEST_MYSQL_USER=pulldb_app
export PULLDB_TEST_MYSQL_PASSWORD=toenails-finch-derby-ting
export PULLDB_TEST_MYSQL_DATABASE=pulldb

venv/bin/python -m pytest pulldb/tests/ -v
```

**Note**: The secret residency check will be skipped when local overrides are active.

## Test Behaviors

### Secret Residency Verification (FAIL HARD)

The `verify_secret_residency` fixture (new as of Nov 2025) validates that all pullDB secrets exist in the development account (345321506926) and not in staging (333204494849) or production (448509429610).

**FAIL HARD Implementation**:
- **With AWS Credentials**: Describes secret and **fails hard** if ARN contains wrong account ID
- **Without AWS Credentials**: **Skips with diagnostic message** explaining how to configure AWS access
- **With Local Override**: **Skips with notice** that residency check bypassed (dev-only mode)
- **Wrong Account**: **Raises AssertionError** with specific remediation guidance

**Example Skip Messages** (diagnostic, not silent):
```
SKIPPED (Cannot verify secret residency: Secrets Manager can't find the specified secret.
         Create secret: aws secretsmanager create-secret --name /pulldb/mysql/coordination-db ...)

SKIPPED (Skipping secret residency check - using local overrides.
         Unset PULLDB_TEST_MYSQL_* to use AWS Secrets Manager path.)

SKIPPED (boto3 not available - cannot verify secret residency.
         Install AWS SDK: pip install boto3)
```

**Example Failure** (hard fail with context):
```
AssertionError: Secret /pulldb/mysql/coordination-db must exist in development account (345321506926),
                but found in account 333204494849.

This violates the dev-only secret residency requirement.

Solutions:
  1. Delete secret from staging account: aws secretsmanager delete-secret --secret-id /pulldb/mysql/coordination-db --region us-east-1 --profile pr-staging
  2. Recreate secret in dev account: aws secretsmanager create-secret --name /pulldb/mysql/coordination-db --secret-string '{"username":"..."}' --profile default
  3. Update secret replication settings if replication was unintentional

Staging=333204494849, Prod=448509429610, Dev=345321506926
```

### Settings Seeding

The `seed_settings` fixture (autouse, scope=session) ensures MySQL settings table has required rows:
- `default_dbhost`: Default MySQL host for restored databases
- `s3_bucket_path`: S3 path for backup discovery

Uses `INSERT ... ON DUPLICATE KEY UPDATE` to be idempotent.

### Test Database State

- **Temporary Data**: Tests create temporary users, jobs, events during execution
- **Cleanup**: Each test uses transactions where possible; some tests may leave residual data
- **Schema**: Tests assume MySQL schema is deployed (see `docs/mysql-schema.md`)

## Test Organization

```
pulldb/tests/
├── conftest.py              # Shared fixtures (credentials, pool, settings)
├── test_secrets.py          # Credential resolution (14 tests)
├── test_config.py           # Configuration loading (7 tests)
├── test_config_integration.py  # Real MySQL integration (3 tests)
├── test_user_repository.py  # User code generation (8 tests)
├── test_job_repository.py   # Job lifecycle (6 tests)
├── test_host_repository.py  # Host registration (4 tests)
├── test_settings_repository.py # Settings CRUD (4 tests)
└── test_imports.py          # Smoke tests (4 tests)
```

**Total**: 50 tests covering foundation phase (Milestone 1)

## Common Issues

### Issue: All tests skipped with "Cannot verify secret residency"

**FAIL HARD Diagnosis**:

**Goal**: Run test suite with AWS Secrets Manager integration

**Problem**: All tests skipped with message "Cannot verify secret residency: Secrets Manager can't find the specified secret"

**Root Cause**: AWS credentials not available OR secret doesn't exist in Secrets Manager

**Solutions** (ranked):
1. **Verify secret exists** (most likely):
   ```bash
   aws secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db
   ```
   If not found, create it:
   ```bash
   aws secretsmanager create-secret \
     --name /pulldb/mysql/coordination-db \
     --secret-string '{"username":"pulldb_app","password":"...","host":"localhost","port":3306,"database":"pulldb"}'
   ```

2. **Check AWS credentials**:
   ```bash
   aws sts get-caller-identity
   ```
   If fails, configure AWS profile:
   ```bash
   aws configure --profile default
   # OR set environment variable
   export AWS_PROFILE=default
   export AWS_DEFAULT_REGION=us-east-1
   ```

3. **Use local override** (dev-only workaround):
   ```bash
   export PULLDB_TEST_MYSQL_HOST=localhost
   export PULLDB_TEST_MYSQL_USER=pulldb_app
   export PULLDB_TEST_MYSQL_PASSWORD=your-password
   ```
   **Note**: This bypasses AWS integration checks and residency verification

### Issue: "AccessDenied when calling DescribeSecret"

**FAIL HARD Diagnosis**:

**Goal**: Verify secret residency during test setup

**Problem**: AWS API returns AccessDenied when describing secret

**Root Cause**: AWS credentials lack `secretsmanager:DescribeSecret` permission

**Solutions** (ranked):
1. **Verify IAM policy attached** (most likely):
   ```bash
   aws iam list-attached-role-policies --role-name pulldb-ec2-service-role \
     --query 'AttachedPolicies[?PolicyName==`pulldb-secrets-manager-access`]'
   ```
   If not attached, attach policy:
   ```bash
   aws iam attach-role-policy \
     --role-name pulldb-ec2-service-role \
     --policy-arn arn:aws:iam::345321506926:policy/pulldb-secrets-manager-access
   ```
   See `docs/aws-authentication-setup.md` for complete setup

2. **Use admin profile temporarily**:
   ```bash
   export AWS_PROFILE=dev-admin  # Profile with broader permissions
   pytest pulldb/tests/ -v
   ```

3. **Run verification script** to diagnose IAM issues:
   ```bash
   ./scripts/verify-secrets-perms.sh --profile dev-admin
   ```

### Issue: Tests pass locally but fail in CI

**FAIL HARD Diagnosis**:

**Goal**: Tests pass in both local and CI environments

**Problem**: Tests succeed locally but fail/skip in CI pipeline

**Root Cause** (most common):
- CI environment has different AWS credentials or none at all
- CI cannot reach MySQL host due to network restrictions
- CI environment variables not matching local setup

**Solutions** (ranked):
1. **Ensure CI has AWS credentials** (most likely):
   - Configure instance profile for EC2-based CI runners
   - Set service role for container-based CI (ECS, Lambda)
   - Add AWS_PROFILE or AWS credentials as CI secrets (GitHub Actions, etc.)
   - Verify: Add step to CI that runs `aws sts get-caller-identity`

2. **Verify CI network access**:
   - Check CI runner can reach MySQL host (RDS endpoint, localhost, etc.)
   - Ensure security groups allow inbound from CI runner IPs
   - Test: Add CI step running `mysql -h <host> -u <user> -p<pass> -e "SELECT 1"`

3. **Check CI environment variables**:
   - Compare `env` output between local and CI
   - Ensure AWS_PROFILE, AWS_DEFAULT_REGION, and any PULLDB_* vars set
   - Review CI configuration file (.github/workflows/*.yml, .gitlab-ci.yml, etc.)

4. **Review CI logs** for specific error messages:
   - Look for pytest skip reasons (will explain what's missing)
   - Check for AWS API errors (AccessDenied, NoCredentials, etc.)
   - Verify MySQL connection errors vs secret resolution errors

### Issue: Secret residency check fails with wrong account

**FAIL HARD Diagnosis**:

**Goal**: Validate secrets exist only in development account (345321506926)

**Problem**: AssertionError stating secret found in wrong account

**Root Cause**: Secret was created in staging/prod account or unintentionally replicated

**Solutions** (ranked):
1. **Verify secret location** (diagnostic step):
   ```bash
   aws secretsmanager describe-secret \
     --secret-id /pulldb/mysql/coordination-db \
     --query 'ARN' --output text
   ```
   Expected pattern: `arn:aws:secretsmanager:us-east-1:345321506926:secret:...`

2. **Delete secret from wrong account** (if in staging/prod):
   ```bash
   # Determine which account (check ARN from step 1)
   aws secretsmanager delete-secret \
     --secret-id /pulldb/mysql/coordination-db \
     --region us-east-1 \
     --profile pr-staging  # or pr-prod
   ```

3. **Recreate secret in dev account**:
   ```bash
   aws secretsmanager create-secret \
     --name /pulldb/mysql/coordination-db \
     --secret-string '{"username":"pulldb_app","password":"...","host":"localhost","port":3306,"database":"pulldb"}' \
     --profile default  # or dev-admin
   ```

4. **Check for replication misconfiguration**:
   ```bash
   aws secretsmanager describe-secret \
     --secret-id /pulldb/mysql/coordination-db \
     --query 'ReplicationStatus' \
     --profile default
   ```
   If replication enabled, remove replica regions:
   ```bash
   aws secretsmanager remove-regions-from-replication \
     --secret-id /pulldb/mysql/coordination-db \
     --remove-replica-regions <region> \
     --profile default
   ```

5. **Update documentation** if architecture changed:
   - If cross-account secret access is now required, update `.github/copilot-instructions.md`
   - Modify `verify_secret_residency` fixture to accept multiple valid accounts
   - Document new architecture in `docs/aws-authentication-setup.md`

## Test Development Guidelines

### Writing New Tests

1. **Use Fixtures**: Leverage `mysql_pool`, `mysql_credentials` for database access
2. **Isolation**: Tests should not depend on execution order
3. **Cleanup**: Use transactions or explicit cleanup in teardown
4. **Assertions**: Use descriptive assertion messages
5. **Docstrings**: Document what each test validates

### Test Naming Convention

- Test files: `test_<module_name>.py`
- Test classes: `Test<FeatureName>` (optional, for grouping)
- Test functions: `test_<behavior_being_validated>`

### Test Structure

```python
def test_feature_behavior(mysql_pool: MySQLPool) -> None:
    """Validate that feature behaves correctly under condition.

    Covers:
    - Specific scenario A
    - Edge case B
    - Error condition C
    """
    # Arrange: Set up test data
    repository = SomeRepository(mysql_pool)

    # Act: Execute the behavior
    result = repository.some_method()

    # Assert: Verify expected outcome
    assert result == expected_value
    assert some_condition_is_true
```

### Mocking AWS Services

Use `moto` library for mocking AWS services in unit tests:

```python
from moto import mock_aws

@mock_aws
def test_s3_operation() -> None:
    # Create mock S3 bucket
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    # Test code that uses S3
    ...
```

### Testing Error Conditions

Always test both success and failure paths following FAIL HARD:

```python
def test_operation_success(mysql_pool: MySQLPool) -> None:
    """Validate operation succeeds with valid input."""
    repository = SomeRepository(mysql_pool)
    result = repository.operation("valid_input")
    assert result.success is True

def test_operation_invalid_input(mysql_pool: MySQLPool) -> None:
    """Validate operation fails hard with actionable error for invalid input.

    FAIL HARD: Must raise specific exception with diagnostic message.
    """
    repository = SomeRepository(mysql_pool)

    with pytest.raises(ValueError, match="Invalid input 'bad_value'.*Expected format.*") as exc_info:
        repository.operation("bad_value")

    # Verify error message provides remediation
    error_msg = str(exc_info.value)
    assert "Expected format" in error_msg
    assert "Example:" in error_msg

def test_operation_aws_failure(mysql_pool: MySQLPool) -> None:
    """Validate operation fails hard when AWS credentials missing.

    FAIL HARD: Must raise exception, not return empty result.
    """
    repository = SomeRepository(mysql_pool)

    # Mock AWS credential failure
    with patch("boto3.Session") as mock_session:
        mock_session.side_effect = NoCredentialsError()

        with pytest.raises(CredentialError, match="AWS credentials not configured.*") as exc_info:
            repository.aws_operation()

        # Verify error includes remediation steps
        error_msg = str(exc_info.value)
        assert "aws configure" in error_msg or "AWS_PROFILE" in error_msg
```

**FAIL HARD Test Principles**:
- ✅ Test that errors are raised (not swallowed)
- ✅ Test that error messages contain diagnostic information
- ✅ Test that error messages provide remediation steps
- ✅ Test that exceptions preserve stack traces (`from e`)
- ❌ Don't test for silent failures or None returns on error
- ❌ Don't mock errors without verifying error message content

## Continuous Integration

### Pre-Commit Hooks

Tests run automatically via pre-commit hooks:

```bash
# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

### GitHub Actions (Future)

Once CI is configured:
- Tests run on every push and pull request
- Coverage reports generated automatically
- Test results visible in PR checks

## Performance Considerations

- **Session-scoped fixtures**: Connection pool created once per test session
- **Fast unit tests**: Mock external dependencies (S3, subprocess calls)
- **Slower integration tests**: Exercise real MySQL and AWS (when available)
- **Parallel execution**: Tests are isolated and can run in parallel (future)

## Debugging Tests

### Run with debugging output

```bash
# Show print statements
venv/bin/python -m pytest pulldb/tests/ -v -s

# Show full tracebacks
venv/bin/python -m pytest pulldb/tests/ -v --tb=long

# Stop at first failure
venv/bin/python -m pytest pulldb/tests/ -v -x

# Run specific test
venv/bin/python -m pytest pulldb/tests/test_secrets.py::TestCredentialResolver::test_init_default -v
```

### Use pytest debugger

```bash
# Drop into pdb on failure
venv/bin/python -m pytest pulldb/tests/ --pdb

# Drop into pdb on first failure
venv/bin/python -m pytest pulldb/tests/ -x --pdb
```

### VS Code Debugging

1. Set breakpoint in test file
2. Right-click test function → "Debug Test"
3. VS Code will launch debugger and stop at breakpoint

## Related Documentation

- `docs/aws-authentication-setup.md`: AWS credential setup and verification
- `docs/aws-secrets-manager-setup.md`: Secrets Manager configuration
- `docs/mysql-schema.md`: Database schema required by tests
- `.github/copilot-instructions.md`: Testing mandate and rationale
- `constitution.md`: Development workflow and quality standards
