# Development Guide

[← Back to Documentation Index](START-HERE.md)

> **Version**: 0.2.0 | **Last Updated**: January 2026

This guide covers setting up a development environment, coding standards, testing, and contributing to pullDB.

**Related:** [Architecture](architecture.md) · [MySQL Schema](mysql-schema.md)

---

## Table of Contents

1. [Setup](#setup)
2. [Project Structure](#project-structure)
3. [Coding Standards](#coding-standards)
4. [Testing](#testing)
5. [Development Workflow](#development-workflow)
6. [Build & Deploy (Development)](#build--deploy-development)
7. [Common Tasks](#common-tasks)

---

## Setup

### Prerequisites

- Python 3.12+
- MySQL 8.0+
- AWS CLI configured with appropriate profiles
- Git

### Development Installation

```bash
# Clone the repository
git clone https://github.com/your-org/pulldb.git
cd pulldb

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in editable mode with dev dependencies
pip install --upgrade pip
pip install -e .[dev]

# Verify installation
pulldb --version
```

### Environment Setup

Create a `.env` file in the project root:

```bash
# AWS profiles
PULLDB_AWS_PROFILE=pr-dev           # Secrets Manager access
PULLDB_S3_AWS_PROFILE=pr-staging    # S3 backup access

# MySQL (resolved from Secrets Manager)
PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db

# API configuration
PULLDB_API_URL=http://localhost:8080
```

---

## Project Structure

```
pulldb/
├── api/            # HTTP API service (FastAPI)
├── cli/            # CLI entrypoints (Click)
│   ├── main.py     # pulldb commands
│   ├── admin.py    # pulldb-admin commands
│   └── parse.py    # Argument parsing
├── domain/         # Core business logic
│   ├── config.py   # Configuration dataclass
│   ├── models.py   # Job, User models
│   └── errors.py   # Exception hierarchy
├── infra/          # External service adapters
│   ├── mysql.py    # MySQL repository
│   ├── s3.py       # S3 backup discovery
│   ├── secrets.py  # AWS Secrets Manager
│   └── logging.py  # Structured logging
├── worker/         # Background job processor
│   ├── service.py  # Main worker loop
│   ├── downloader.py
│   ├── restore.py
│   └── staging.py
└── tests/          # pytest test suite
```

---

## Coding Standards

### Architecture Standards (HCA)

All new development MUST follow **Hierarchical Containment Architecture (HCA)** principles.
See `docs/IngestMe/HCA/` for detailed guidelines.

- **Structure**: Code must be organized according to HCA layers.
- **Compliance**: New features must be HCA-compliant. Legacy code is exempt until migration.

### FAIL HARD Protocol

Error handling MUST follow the FAIL HARD principle (see `constitution.md`):

- **Never** silently swallow exceptions
- **Always** chain exceptions: `raise DomainError(...) from e`
- **Provide** actionable error messages with Goal/Problem/Solutions
- **Use** specific exception subclasses

```python
try:
    backup = s3_client.get_object(Bucket=bucket, Key=key)
except ClientError as e:
    code = e.response.get("Error", {}).get("Code")
    if code == "AccessDenied":
        raise BackupDownloadError(
            f"Goal: Download backup archive\n"
            f"Problem: AccessDenied for key {key}\n"
            f"Root Cause: IAM role missing s3:GetObject\n"
            f"Solutions:\n"
            f"  1. Attach pulldb-s3-read-access policy\n"
            f"  2. Verify role session: aws sts get-caller-identity"
        ) from e
    raise
```

### Linting with Ruff

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check all files
ruff check .

# Check with auto-fix
ruff check --fix .

# Format code
ruff format .
```

**Configuration** (`pyproject.toml`):
```toml
[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "N", "D", "UP", "B", "C4", "SIM"]

[tool.ruff.lint.pydocstyle]
convention = "google"
```

### Type Hints

All functions must have type annotations:

```python
def process_job(job_id: str, config: Config) -> JobResult:
    """Process a restore job.
    
    Args:
        job_id: The job identifier.
        config: Application configuration.
        
    Returns:
        The result of job processing.
        
    Raises:
        JobNotFoundError: If job doesn't exist.
    """
```

Type checking with mypy:
```bash
mypy pulldb
```

### Docstrings

Use Google-style docstrings:

```python
def download_backup(
    bucket: str, 
    key: str, 
    dest_path: Path
) -> int:
    """Download a backup file from S3.
    
    Args:
        bucket: S3 bucket name.
        key: Object key in the bucket.
        dest_path: Local destination path.
        
    Returns:
        Number of bytes downloaded.
        
    Raises:
        S3DownloadError: If download fails.
    """
```

---

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=pulldb --cov-report=term-missing

# Run specific test file
pytest pulldb/tests/test_mysql.py

# Run tests matching pattern
pytest -k "test_restore"

# Verbose output
pytest -v
```

### Test Architecture

Tests use AWS Secrets Manager for credentials per November 2025 mandate:

1. **No hardcoded credentials** - All resolved from Secrets Manager
2. **FAIL HARD on missing config** - Clear skip messages with remediation
3. **Profile-aware** - Different profiles for Secrets vs S3

### AWS Profile Matrix

| Profile | Use Case | Permissions |
|---------|----------|-------------|
| `(unset)` | EC2 instance | Full access via instance profile |
| `pr-dev` | Off-box development | Secrets Manager + coordination DB |
| `pr-staging` | Staging S3 backups | S3 read-only |
| `pr-prod` | Production S3 backups | S3 read-only (cross-account) |

### Key Fixtures

| Fixture | Purpose |
|---------|---------|
| `mysql_credentials` | Resolves credentials from AWS |
| `mysql_pool` | Shared connection pool |
| `seed_settings` | Ensures required settings exist |
| `verify_secret_residency` | Validates secret in dev account |

### Writing Tests

```python
def test_restore_creates_staging_database(mysql_pool, seed_settings):
    """Test that restore creates a staging database."""
    # Arrange
    job = create_test_job()
    
    # Act
    result = perform_restore(job, mysql_pool)
    
    # Assert
    assert result.status == "complete"
    assert staging_database_exists(result.staging_name)
```

---

## Development Workflow

### Branch Strategy

- `main` - Production-ready code
- `phase-*` - Feature development branches
- Feature branches from phase branches

### Pre-commit Checks

Before committing:

```bash
# Run linter
ruff check .

# Run type checker
mypy pulldb

# Run tests
pytest

# All in one
make check  # if Makefile configured
```

### Making Changes

1. Create feature branch from current phase
2. Write tests first (test-driven development)
3. Implement the feature
4. Ensure all tests pass
5. Run linting and type checking
6. Update documentation if needed
7. Create pull request

### Version Management

Version is set in `pulldb/__init__.py`:

```python
__version__ = "0.2.0"
```

Update when releasing. Also update:
- `CHANGELOG.md`
- Documentation version headers

### Debugging

```bash
# Enable debug logging
export PULLDB_LOG_LEVEL=DEBUG

# Run CLI with debugging
python -m pulldb.cli.main status --help

# Interactive debugging
python -c "from pulldb.domain.config import Config; print(Config.from_env())"
```

---

## Build & Deploy (Development)

> ⚠️ **CRITICAL**: Always deploy to the service venv, never system-wide.

### Building the Package

```bash
cd /home/charleshandshy/Projects/pullDB

# Clean previous build artifacts
rm -rf dist/ build/ pulldb.egg-info/

# Build wheel and sdist
python3 -m build
```

This creates:
- `dist/pulldb-X.X.X-py3-none-any.whl` - Wheel package
- `dist/pulldb-X.X.X.tar.gz` - Source distribution

### Deploying to Service (Development Server)

**ALWAYS use the service venv pip, never system pip:**

```bash
# ✅ CORRECT: Install to service venv
sudo /opt/pulldb.service/venv/bin/pip install /path/to/pulldb-X.X.X-py3-none-any.whl --force-reinstall

# Restart service to pick up changes
sudo systemctl restart pulldb-web

# Verify version
/opt/pulldb.service/venv/bin/pip show pulldb | head -3
```

**NEVER do this:**
```bash
# ❌ WRONG: Installs system-wide, not to venv
sudo pip install dist/pulldb-X.X.X-py3-none-any.whl --break-system-packages
```

### Quick Deploy Script

For convenience during development:

```bash
#!/bin/bash
# scripts/dev-deploy.sh
set -e

cd /home/charleshandshy/Projects/pullDB

# Clean and build
rm -rf dist/ build/ pulldb.egg-info/
python3 -m build

# Deploy to service venv
sudo /opt/pulldb.service/venv/bin/pip install dist/pulldb-*-py3-none-any.whl --force-reinstall

# Restart services
sudo systemctl restart pulldb-web

# Verify
echo "Deployed version:"
/opt/pulldb.service/venv/bin/pip show pulldb | grep Version
sudo systemctl status pulldb-web --no-pager | head -5
```

### Service Paths Reference

| Component | Path |
|-----------|------|
| Service venv | `/opt/pulldb.service/venv/` |
| Service pip | `/opt/pulldb.service/venv/bin/pip` |
| Service python | `/opt/pulldb.service/venv/bin/python` |
| Service config | `/opt/pulldb.service/.env` |
| Systemd unit | `/etc/systemd/system/pulldb-web.service` |

### Verifying Deployment

```bash
# Check installed version
/opt/pulldb.service/venv/bin/pip show pulldb | head -3

# Verify no system-wide installation
pip show pulldb 2>/dev/null && echo "WARNING: System-wide install exists!" || echo "OK: No system-wide install"

# Check service is running
sudo systemctl status pulldb-web --no-pager

# Verify CSS loads (quick smoke test)
curl -s http://localhost:8000/web/auth/login | grep -E 'manifest\.css' && echo "CSS OK"
```

---

## Common Tasks

### Adding a New CLI Command

1. Add command function in `pulldb/cli/main.py`:
   ```python
   @cli.command("newcmd", help="Description")
   @click.argument("arg")
   def newcmd_cmd(arg: str) -> None:
       """Implementation."""
   ```

2. Add tests in `pulldb/tests/test_cli.py`

3. Update `docs/cli-reference.md`

### Adding a New Setting

1. Add to schema migration:
   ```sql
   INSERT IGNORE INTO settings (setting_key, setting_value, description)
   VALUES ('new_setting', 'default', 'Description');
   ```

2. Add to `SettingsRepository.get()` method

3. Document in admin guide

### Adding a Database Migration

```bash
# Create migration
pulldb-migrate new add_new_feature

# Edit the file
vim /opt/pulldb.service/migrations/YYYYMMDDHHMMSS_add_new_feature.sql

# Apply locally
pulldb-migrate up

# Test rollback
pulldb-migrate rollback
pulldb-migrate up
```

---

## Resources

- **Constitution**: `constitution.md` - Project governance and FAIL HARD protocol
- **Architecture**: `docs/architecture.md` - System design
- **CLI Reference**: `docs/cli-reference.md` - Command documentation
- **Admin Guide**: `docs/admin-guide.md` - Operations documentation

---

[← Back to Documentation Index](START-HERE.md) · [MySQL Schema →](mysql-schema.md)
