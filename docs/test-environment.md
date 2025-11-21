# Test Environment Management

**Quick Reference**: Procedures for creating, using, and destroying the pullDB test environment.

---

## Overview

The test environment provides an isolated space for validating the v0.0.1 release package before broader deployment. It includes:

- Dedicated MySQL test database (`pulldb_test_coordination`)
- Python virtual environment with pullDB installed
- Pinned test dependencies preinstalled (pytest, pytest-timeout, httpx, moto, responses)
- Configuration files with random credentials
- Smoke tests for basic validation
- Convenience scripts for easy activation
- AWS default profile configured to assume the staging cross-account read-only role via EC2 Instance Metadata

**Location**: `test-env/` directory in project root
**Setup Script**: `scripts/setup-test-environment.sh`
**Documentation**: See `engineering-dna/protocols/test-environment-setup.md` for complete protocol

---

## Quick Commands

### Create Test Environment

```bash
# Fresh setup (first time)
sudo bash scripts/setup-test-environment.sh

# Recreate from scratch (cleanup + setup)
sudo bash scripts/setup-test-environment.sh --clean

# Preview without changes (dry-run mode)
bash scripts/setup-test-environment.sh --dry-run

# Skip MySQL setup (use existing database)
sudo bash scripts/setup-test-environment.sh --skip-mysql

# Skip AWS verification (offline testing)
sudo bash scripts/setup-test-environment.sh --skip-aws

# Only install dependencies (already provisioned DB/AWS)
sudo bash scripts/setup-test-environment.sh --skip-mysql --skip-aws
```

### Activate Environment

```bash
# Activate test environment (loads config + venv)
source test-env/activate-test-env.sh

# Run smoke tests (also executed automatically at the end of setup)
bash test-env/run-quick-test.sh

# Verify AWS identity (optional; requires metadata-backed default profile)
aws sts get-caller-identity --profile default
```

### Use Environment

```bash
# Activate first
source test-env/activate-test-env.sh

# Test CLI commands
pulldb --help
pulldb status
pulldb restore --help

# Check configuration
cat test-env/.env
cat test-env/config/mysql-credentials.txt

# Connect to test database
# (password in test-env/config/mysql-credentials.txt)
mysql -u pulldb_usability_test -p pulldb_test_coordination
```

### Destroy Environment

```bash
# Remove test environment directory
rm -rf test-env/

# Drop test database and user
mysql -u root -p <<SQL
DROP DATABASE IF EXISTS pulldb_test_coordination;
DROP USER IF EXISTS 'pulldb_usability_test'@'localhost';
SQL

# Or use cleanup flag on next setup
sudo bash scripts/setup-test-environment.sh --clean
```

---

## Directory Structure

```
test-env/
├── .env                    # Environment variables (database, AWS, paths)
├── activate-test-env.sh    # Source this to activate environment
├── run-quick-test.sh       # Smoke tests script
├── venv/                   # Python virtual environment
│   ├── bin/
│   │   ├── activate        # Venv activation
│   │   ├── pulldb          # CLI entry point
│   │   ├── pulldb-api      # API service entry point
│   │   └── pulldb-worker   # Worker service entry point
│   └── lib/                # Installed packages
├── config/
│   └── mysql-credentials.txt  # Database credentials (random password)
├── logs/                   # Application logs (empty until used)
├── work/                   # Working directory for restores
├── backups/                # Backup storage area
└── opt/
    └── pulldb/
        └── scripts/        # Service files from package
```

---

## Configuration Files

### test-env/.env

Environment variables loaded by activation script:

```bash
# MySQL Configuration
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_PORT=3306
PULLDB_MYSQL_USER=pulldb_usability_test
PULLDB_MYSQL_PASSWORD=<random_20_char_password>
PULLDB_MYSQL_DATABASE=pulldb_test_coordination

# AWS Configuration
PULLDB_AWS_PROFILE=default
PULLDB_AWS_REGION=us-east-1

# S3 Configuration
PULLDB_S3_BUCKET=pestroutes-rds-backup-prod-vpc-us-east-1-s3
PULLDB_S3_PREFIX=daily/prod/

# Application Configuration
PULLDB_WORK_DIR=/home/user/Projects/.../pullDB/test-env/work
PULLDB_LOG_LEVEL=INFO
```

### AWS Profile Expectations

The setup assumes the **default** AWS CLI profile can assume the staging read-only role:

```
[default]
role_arn = arn:aws:iam::333204494849:role/pulldb-staging-cross-account-readonly
credential_source = Ec2InstanceMetadata
external_id = pulldb-dev-access-2025
region = us-east-1
```

- **On EC2**: Instance metadata provides credentials automatically—no extra steps required.
- **Local workstations**: Either mirror the metadata configuration using a profile that can assume the role, or run the setup with `--skip-aws` and treat S3 restores as unsupported until credentials are provisioned.
- The smoke test reports a warning (but still passes) when the profile cannot authenticate; this is expected when developing offline.

### test-env/config/mysql-credentials.txt

Human-readable credentials for manual testing:

```
MySQL Test Database Credentials
================================
Host: localhost
Database: pulldb_test_coordination
User: pulldb_usability_test
Password: <random_password>

Connection String:
mysql -u pulldb_usability_test -p'<password>' pulldb_test_coordination
```

---

## Smoke Tests

The `run-quick-test.sh` script validates:

1. **CLI Help**: `pulldb --help` command works
2. **Database Connectivity**: Can connect to test database
3. **AWS Credentials**: AWS profile configured (optional)
4. **Python Imports**: All modules import successfully

Expected output:

```
Running quick smoke tests...

✓ Testing CLI help...
✓ Testing database connectivity...
  MySQL version: 8.0.43-0ubuntu0.24.04.2
✓ Testing AWS credentials...
  Account: 333204494849 (role pulldb-staging-cross-account-readonly)
✓ Testing Python imports...
  All imports successful

All smoke tests passed! ✓
```


## Full Functionality Test (End-to-End Restore)

The script `test-env/run-full-functionality-test.sh` performs a real restore
using the packaged CLI, API service, worker, downloader, myloader, and
post-restore logic. Run it when you need to verify the complete workflow
without mocks.

### Prerequisites

- Test environment created via `scripts/setup-test-environment.sh` (venv,
  schema, config files, etc.).
- AWS profile from `test-env/.env` can describe Secrets Manager entries and
  read from `s3://pestroutesrdsdbs/daily/stg/`.
- Secrets referenced in `db_hosts.credential_ref` exist (default host uses
  `/pulldb/mysql/localhost-test`).
- `myloader` installed on the host (worker requirement).
- Known backup for the target (default script run targets the documented
  `qatemplate` backups under `daily/stg/qatemplate/`).

### Running the Script

```bash
# Default QA template restore (recommended starting point)
bash test-env/run-full-functionality-test.sh --user qaengineer --qatemplate

# Customer restore with explicit dbhost and overwrite flag
---

## Common Issues

### Issue: Permission denied on .env file

```

Key behaviors:

- Sources `test-env/activate-test-env.sh`, exports `PULLDB_API_URL`, and
  derives `PULLDB_S3_BUCKET_PATH` when only bucket/prefix values exist.
- Verifies Secrets Manager/SSM references for the effective `dbhost` before
  starting the worker so missing secrets fail fast.
- Launches `pulldb-api` and `pulldb-worker` from the test environment venv,
  then submits the restore via the CLI using the provided options.
- Polls the `jobs` table until the job reaches `complete`/`failed`, honoring
  the configurable `--timeout` and `--poll` intervals.
- Captures diagnostics to `test-env/logs/`:
  - API log: `full-test-api.log`
  - Worker log: `full-test-worker.log`
  - Job events: `full-test-events.log`
  - CLI submission output: `full-test-restore-output.log`

Use `--keep-processes` to leave the API and worker running for manual testing
after the scripted run completes.

---
**Symptom**: `grep: test-env/.env: Permission denied`

**Solution**:
```bash
sudo chmod 644 test-env/.env
```

### Issue: Cannot install packages in venv

**Symptom**: `ERROR: Could not install packages due to an OSError: [Errno 13] Permission denied`

**Solution**:
```bash
sudo chown -R $USER:$USER test-env/venv
```

> When metadata credentials are present the setup reports the assumed account. If both explicit and metadata providers fail, the script logs a warning and continues so offline development remains possible.
### Issue: AWS profile unavailable

**Symptom**: `The config profile (default) could not be found` or `Unable to locate credentials`

**Solution**:
1. Ensure `~/.aws/config` contains the metadata-based default profile snippet shown above.
2. If working off-instance, configure a source profile with `sts:AssumeRole` permissions and map it to `default`, or rerun setup with `--skip-aws`.

### Issue: Module not found errors

**Symptom**: `ModuleNotFoundError: No module named 'httpx'`

**Solution**:
```bash
# Re-run setup to reinstall pinned dependencies
sudo bash scripts/setup-test-environment.sh --skip-mysql --skip-aws

# Or repair in-place
source test-env/activate-test-env.sh
pip install -r requirements-test.txt
```

### Issue: CLI command not found

**Symptom**: `pulldb: command not found`

**Solution**: Ensure venv is activated
```bash
source test-env/activate-test-env.sh
which pulldb  # Should show test-env/venv/bin/pulldb
```

### Issue: Database connection failed

**Symptom**: `Access denied for user` or `Unknown database`

**Solution**: Verify credentials and database exist
```bash
cat test-env/config/mysql-credentials.txt
mysql -u root -p -e "SHOW DATABASES LIKE 'pulldb_test%';"
```

### Issue: Schema tables missing

**Symptom**: Database exists but has no tables

**Solution**: Deploy schema manually
```bash
cat test-env/config/mysql-credentials.txt
cat schema/pulldb/*.sql | mysql -u pulldb_usability_test -p pulldb_test_coordination
```

---

## Troubleshooting

### Verify Environment State

```bash
# Check directory exists
ls -la test-env/

# Check venv exists
ls -la test-env/venv/bin/

# Check database exists
mysql -u root -p -e "SHOW DATABASES LIKE 'pulldb_test%';"

# Check user exists
mysql -u root -p -e "SELECT User, Host FROM mysql.user WHERE User LIKE 'pulldb%';"

# Check schema deployed
mysql -u root -p pulldb_test_coordination -e "SHOW TABLES;"
```

### Reset Everything

```bash
# Nuclear option: destroy and recreate
sudo bash scripts/setup-test-environment.sh --clean
```

---

## Usability Testing Workflow

### 1. Setup Phase

```bash
# Create environment
sudo bash scripts/setup-test-environment.sh --clean

# Verify smoke tests pass
source test-env/activate-test-env.sh
bash test-env/run-quick-test.sh
```

### 2. Testing Phase

```bash
# Activate environment
source test-env/activate-test-env.sh

# Test CLI help
pulldb --help

# Test status command (should show no jobs)
pulldb status

# Test restore validation (should fail without args)
pulldb restore

# Test invalid options
pulldb restore user=abc  # Should fail: user too short

# Test restore dry-run (if supported)
pulldb restore user=testuser customer=acme --dry-run
```

### 3. Validation Phase

```bash
# Check database state
mysql -u pulldb_usability_test -p pulldb_test_coordination <<SQL
SELECT * FROM auth_users;
SELECT * FROM jobs;
SELECT * FROM job_events;
SQL

# Review logs
ls -la test-env/logs/
cat test-env/logs/*.log
```

### 4. Cleanup Phase

```bash
# Deactivate environment
deactivate

# Remove test environment
rm -rf test-env/

# Drop database
mysql -u root -p -e "DROP DATABASE IF EXISTS pulldb_test_coordination;"
mysql -u root -p -e "DROP USER IF EXISTS 'pulldb_usability_test'@'localhost';"
```

---

## Integration with Release Process

### Pre-Release Validation

1. Build release package: `./packaging/build-package.sh`
2. Create test environment: `sudo bash scripts/setup-test-environment.sh --clean`
3. Run smoke tests: `bash test-env/run-quick-test.sh`
4. Manual usability testing
5. Document issues found
6. Fix bugs (follow RELEASE-FREEZE.md)
7. Rebuild and retest

### Post-Release Verification

1. Install released package: `sudo dpkg -i pulldb_0.0.1_amd64.deb`
2. Verify systemd service: `systemctl status pulldb-worker`
3. Test CLI from system: `/usr/bin/pulldb --help`
4. Compare behavior with test environment

---

## Related Documentation

- **Protocol**: `engineering-dna/protocols/test-environment-setup.md` - Complete protocol with lessons learned
- **Release**: `RELEASE-FREEZE.md` - Release stabilization process
- **Testing**: `docs/testing.md` - Comprehensive testing guide
- **Setup**: `scripts/setup-test-environment.sh` - Automated setup script

---

**Last Updated**: November 14, 2025
**Version**: v0.0.1
**Maintainer**: PestRoutes Engineering
