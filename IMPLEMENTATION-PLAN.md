# pullDB Implementation Plan

> **Status**: Ready to begin Phase 0 (Prototype) implementation
> **Start Date**: October 30, 2025
> **Target**: Minimum viable prototype with core restore functionality

## Current State Assessment

### Documentation (Complete ✅)
- [x] `.github/copilot-instructions.md` - AI agent guidance and architecture overview
- [x] `constitution.md` - Coding standards, tooling, KISS principles
- [x] `README.md` - Complete API reference and usage patterns
- [x] `design/system-overview.md` - Component responsibilities
- [x] `design/implementation-notes.md` - Python project structure
- [x] `design/configuration-map.md` - Configuration sources
- [x] `design/roadmap.md` - Phased feature rollout (0-5)
- [x] `design/apptype-analysis.md` - Legacy appType migration
- [x] `design/staging-rename-pattern.md` - Staging database pattern (MANDATORY)
- [x] `docs/mysql-schema.md` - Complete database schema with initialization
- [x] `customers_after_sql/` - 12 post-restore SQL scripts (010-120)
- [x] `qa_template_after_sql/` - README explaining no scripts needed
- [x] `reference/` - Legacy PHP implementations (gitignored, local only)

### Code (In Progress 🚧)
- [x] Python virtual environment created (Python 3.12.3)
- [x] MySQL setup script created (`scripts/setup-mysql.sh`)
- [x] Schema setup script created (`scripts/setup-pulldb-schema.sh`)
- [x] AWS installation script created (`scripts/setup-aws.sh`)
- [x] Dependency manifests added (`requirements.txt`, `requirements-dev.txt`, `requirements.lock`)
- [x] Python project structure (initial scaffolding complete)
- [ ] Python tests (awaiting Milestone 9)

### Infrastructure (Partially Provisioned ⚙️)
- [x] MySQL 8.0.43 server installed and running
- [x] MySQL data directory configured at `/mnt/data/mysql/data`
- [x] MySQL tmpdir configured at `/mnt/data/mysql/tmpdir`
- [x] Python MySQL libraries installed (mysql-connector-python 9.5.0, pymysql 1.4.6)
- [x] AWS CLI v2 installed (script-driven)
- [x] AWS Python libraries installed (boto3 1.40.63, botocore 1.40.63, s3transfer 0.14.0)
- [ ] AWS profile/role configuration (pending environment decision)
- [ ] pulldb coordination database (run `scripts/setup-pulldb-schema.sh`)
- [ ] EC2 instance for daemon
- [ ] AWS credentials and IAM roles
- [ ] Database host registrations

## Phase 0 Goals (Prototype)

**Objective**: Deliver minimal viable restore loop that proves the architecture.

**Success Criteria**:
1. User can submit restore job via CLI
2. Daemon picks up job, downloads from S3, restores to staging, executes post-restore SQL, performs atomic rename
3. Job status visible via `pullDB status` command
4. All operations logged to files and structured for Datadog ingestion
5. Metrics emitted: queue depth, disk capacity failures

**Out of Scope for Phase 0**:
- Job cancellation
- Job history queries
- User management commands
- Web interface
- Multi-daemon support
- Concurrency limits beyond per-target exclusivity

## Implementation Order

### Milestone 1: Foundation (Week 1)

#### 1.1 Project Structure Setup
```bash
pulldb/
├── pyproject.toml          # Poetry/setuptools configuration
├── setup.py                # Installation script
├── requirements.txt        # Direct dependencies
├── requirements-dev.txt    # Development dependencies
├── .python-version         # Python 3.11+
├── pulldb/
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py         # Entry point: pullDB command
│   │   ├── validator.py    # Option validation
│   │   └── formatter.py    # Output formatting
│   ├── daemon/
│   │   ├── __init__.py
│   │   ├── main.py         # Entry point: pulldb-daemon
│   │   ├── worker.py       # Job execution loop
│   │   ├── downloader.py   # S3 operations
│   │   ├── restorer.py     # myloader wrapper + staging pattern
│   │   └── cleaner.py      # Post-restore SQL + metadata
│   ├── infra/
│   │   ├── __init__.py
│   │   ├── mysql.py        # MySQL connection pool + queries
│   │   ├── s3.py           # S3 client wrapper
│   │   └── logging.py      # Structured JSON logging
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── job.py          # Job dataclass
│   │   ├── user.py         # User dataclass
│   │   └── config.py       # Configuration dataclass
│   └── tests/
│       ├── __init__.py
│       ├── test_cli/
│       ├── test_daemon/
│       ├── test_infra/
│       └── fixtures/
└── scripts/
    ├── setup-mysql.sh               # MySQL 8.x installation script
    ├── setup-pulldb-schema.sh       # pulldb database creation script
    └── deploy-daemon.sh             # Deployment helper (future)
```

**Tasks**:
- [x] Initialize Python virtual environment (Python 3.12.3)
- [x] Create MySQL installation script with custom data directory setup
- [x] Create pulldb schema deployment script
-- [x] Initialize Python project with setuptools (PEP 621 metadata)
-- [x] Create directory structure (`pulldb/` package scaffolding)
- [ ] Set up pytest configuration
- [ ] Configure linting (ruff/black) and type checking (mypy)
- [ ] Create basic `__init__.py` files

**Dependencies**:
```python
# requirements.txt
mysql-connector-python>=8.0.0
boto3>=1.28.0
click>=8.1.0  # CLI framework
pydantic>=2.0.0  # Data validation
python-dotenv>=1.0.0  # .env file support
```

#### 1.2 MySQL Schema Deployment

**Scripts Created**:
- `scripts/setup-mysql.sh` - Installs MySQL 8.x, configures data directories on `/mnt/data/mysql`
- `scripts/setup-pulldb-schema.sh` - Creates `pulldb` database with all tables and initial data

**Tasks**:
- [x] Create MySQL installation script with automated setup
- [x] Configure MySQL data directory: `/mnt/data/mysql/data` (working data)
- [x] Configure MySQL tmpdir: `/mnt/data/mysql/tmpdir` (temporary files)
- [x] Update AppArmor permissions for custom data directory
- [x] Create schema deployment script with trigger and initial data
- [ ] Run `sudo scripts/setup-mysql.sh` (if not already done)
- [ ] Run `sudo scripts/setup-pulldb-schema.sh` to create pulldb database
- [ ] Test schema deployment on local/dev MySQL instance
- [ ] Document connection parameters and credential setup

**Verification**:
```sql
-- Verify schema
SHOW TABLES;
SELECT * FROM settings;
SELECT * FROM db_hosts;

-- Test user insertion
INSERT INTO auth_users (user_id, username, user_code) 
VALUES (UUID(), 'testuser', 'testus');
```

#### 1.3 Configuration Module

**File**: `pulldb/domain/config.py`

**Tasks**:
- [ ] Implement Configuration dataclass
- [ ] Load from environment variables (PULLDB_*)
- [ ] Load from MySQL settings table
- [ ] Support AWS Secrets Manager references
- [ ] Validate required settings on startup
- [ ] Implement credential resolution for db_hosts

**Example**:
```python
@dataclass
class Config:
    mysql_host: str
    mysql_user: str
    mysql_password: str
    mysql_database: str = "pulldb"
    
    s3_bucket_path: str
    aws_profile: str = "pr-prod"
    
    default_dbhost: str
    work_dir: Path
    
    customers_after_sql_dir: Path
    qa_template_after_sql_dir: Path
    
    @classmethod
    def from_env_and_mysql(cls, mysql_conn) -> 'Config':
        # Load from environment
        # Override with MySQL settings table
        # Validate and return
        pass
```

### Milestone 2: MySQL Infrastructure (Week 1-2)

#### 2.1 MySQL Repository Layer

**File**: `pulldb/infra/mysql.py`

**Tasks**:
- [ ] Implement connection pool with context managers
- [ ] Create JobRepository class:
  - [ ] `enqueue_job(job: Job) -> str` (returns job_id)
  - [ ] `get_next_queued_job() -> Optional[Job]`
  - [ ] `mark_job_running(job_id: str)`
  - [ ] `mark_job_complete(job_id: str)`
  - [ ] `mark_job_failed(job_id: str, error: str)`
  - [ ] `append_job_event(job_id: str, event_type: str, detail: str)`
  - [ ] `get_active_jobs() -> List[Job]`
  - [ ] `check_target_exclusivity(target: str, dbhost: str) -> bool`
- [ ] Create UserRepository class:
  - [ ] `get_or_create_user(username: str) -> User`
  - [ ] `generate_user_code(username: str) -> str` (collision handling)
- [ ] Create HostRepository class:
  - [ ] `get_host_config(dbhost: str) -> HostConfig`
  - [ ] `check_host_capacity(dbhost: str) -> bool`
- [ ] Create SettingsRepository class:
  - [ ] `get_setting(key: str) -> str`
  - [ ] `set_setting(key: str, value: str)`
- [ ] Unit tests with in-memory/test MySQL instance

**Example**:
```python
class JobRepository:
    def __init__(self, connection_pool):
        self.pool = connection_pool
    
    def enqueue_job(self, job: Job) -> str:
        """Insert job into MySQL, return job_id."""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO jobs 
                (id, owner_user_id, target, staging_name, dbhost, status, options_json)
                VALUES (%s, %s, %s, %s, %s, 'queued', %s)
            """, (job.id, job.owner_user_id, job.target, job.staging_name, 
                  job.dbhost, json.dumps(job.options)))
            conn.commit()
            return job.id
```

### Milestone 3: CLI Implementation (Week 2)

#### 3.1 CLI Parser and Validator

**File**: `pulldb/cli/main.py`

**Tasks**:
- [ ] Implement Click-based CLI with subcommands
- [ ] Parse `user=`, `customer=`, `qatemplate`, `dbhost=`, `overwrite` options
- [ ] Validate mutually exclusive options (customer/qatemplate)
- [ ] Validate user parameter (6+ alphabetic characters)
- [ ] Generate user_code with collision detection
- [ ] Sanitize customer ID (lowercase, letters only)
- [ ] Generate target name (user_code + customer/qatemplate)
- [ ] Validate target name length (max 51 chars for staging suffix)
- [ ] Check per-target exclusivity before enqueue
- [ ] Handle `overwrite` flag for existing targets
- [ ] Implement `status` command
- [ ] Implement `--help` and error messages

**CLI Interface**:
```bash
# Main restore command
pulldb user=jdoe customer=acme dbhost=db-mysql-db4-dev overwrite

# Status command
pulldb status

# Help
pulldb --help
```

**Example Implementation**:
```python
import click

@click.group()
def cli():
    """pullDB - Database restore tool"""
    pass

@cli.command()
@click.argument('options', nargs=-1)
def restore(options):
    """Submit a restore job"""
    # Parse key=value options
    # Validate
    # Generate job
    # Enqueue via JobRepository
    # Print job_id
    pass

@cli.command()
def status():
    """Show queue status"""
    # Query active jobs
    # Format output
    pass
```

#### 3.2 Output Formatting

**File**: `pulldb/cli/formatter.py`

**Tasks**:
- [ ] Format job submission confirmation
- [ ] Format status output (table of active jobs)
- [ ] Format error messages
- [ ] Support quiet mode for scripting

### Milestone 4: Daemon Core (Week 2-3)

#### 4.1 Daemon Main Loop

**File**: `pulldb/daemon/main.py`

**Tasks**:
- [ ] Implement daemon startup and configuration loading
- [ ] Create infinite polling loop with sleep interval
- [ ] Query for next queued job
- [ ] Lock job by marking status=running
- [ ] Delegate to worker
- [ ] Handle daemon shutdown signals (SIGTERM, SIGINT)
- [ ] Implement heartbeat logging
- [ ] Emit queue depth metric

**Example**:
```python
def main():
    config = Config.from_env_and_mysql()
    logger = setup_logger(config)
    job_repo = JobRepository(config.mysql_pool)
    
    while True:
        try:
            job = job_repo.get_next_queued_job()
            if job:
                worker = Worker(config, job_repo, logger)
                worker.execute(job)
            else:
                time.sleep(5)  # Poll interval
                emit_metric('queue_depth', job_repo.count_queued())
        except KeyboardInterrupt:
            logger.info("Daemon shutdown requested")
            break
        except Exception as e:
            logger.error(f"Daemon error: {e}")
```

#### 4.2 Worker Job Execution

**File**: `pulldb/daemon/worker.py`

**Tasks**:
- [ ] Implement complete job execution flow:
  1. [ ] Cleanup orphaned staging databases for target
  2. [ ] Generate staging database name
  3. [ ] Validate staging name uniqueness
  4. [ ] Download backup from S3
  5. [ ] Extract tarball
  6. [ ] Restore to staging database via myloader
  7. [ ] Execute post-restore SQL scripts
  8. [ ] Add pullDB metadata table
  9. [ ] Atomic rename staging → target
  10. [ ] Cleanup staging database and temp files
  11. [ ] Mark job complete
- [ ] Error handling at each phase
- [ ] Job event logging for each phase
- [ ] Rollback on failure (preserve staging database)

**Example Structure**:
```python
class Worker:
    def execute(self, job: Job):
        try:
            self.job_repo.append_job_event(job.id, 'started', '')
            
            # Phase 1: Cleanup
            self.cleanup_orphaned_staging(job.target, job.dbhost)
            
            # Phase 2: Download
            backup_file = self.downloader.find_latest_backup(job.customer_id)
            local_path = self.downloader.download(backup_file)
            
            # Phase 3: Restore
            staging_name = self.generate_staging_name(job.target, job.id)
            self.restorer.restore_to_staging(local_path, staging_name, job.dbhost)
            
            # Phase 4: Post-SQL
            self.cleaner.execute_post_sql(staging_name, job.customer_type, job.dbhost)
            
            # Phase 5: Metadata
            self.cleaner.add_metadata_table(staging_name, job, backup_file)
            
            # Phase 6: Rename
            self.restorer.atomic_rename(staging_name, job.target, job.dbhost)
            
            # Phase 7: Cleanup
            self.cleanup_temp_files(local_path)
            
            self.job_repo.mark_job_complete(job.id)
            
        except Exception as e:
            logger.error(f"Job {job.id} failed: {e}")
            self.job_repo.mark_job_failed(job.id, str(e))
```

### Milestone 5: S3 Integration (Week 3)

#### 5.1 S3 Downloader

**File**: `pulldb/daemon/downloader.py`

**Tasks**:
- [ ] Implement boto3 S3 client wrapper
- [ ] List files in S3 bucket with pagination
- [ ] Find latest backup for customer/qatemplate
- [ ] Validate backup has required files (*-schema-create.sql.zst)
- [ ] Check available disk space before download
- [ ] Download with progress tracking
- [ ] Verify download integrity
- [ ] Extract tarball

**Example**:
```python
class S3Downloader:
    def find_latest_backup(self, customer_id: str) -> str:
        """Find most recent backup file for customer."""
        prefix = f"daily/prod/{customer_id}/"
        response = self.s3_client.list_objects_v2(
            Bucket=self.bucket,
            Prefix=prefix
        )
        # Parse filenames, sort by date, return latest
        pass
    
    def download(self, s3_key: str, local_path: Path) -> Path:
        """Download and extract backup."""
        # Check disk space
        # Download with boto3
        # Extract tarball
        # Return extracted directory path
        pass
```

### Milestone 6: MySQL Restore (Week 3-4)

#### 6.1 Restorer with Staging Pattern

**File**: `pulldb/daemon/restorer.py`

**Tasks**:
- [ ] Implement staging database name generation (target + "_" + job_id[:12])
- [ ] Implement orphaned staging database cleanup
- [ ] Wrap myloader subprocess execution
- [ ] Parse myloader output for progress
- [ ] Implement atomic rename with stored procedure
- [ ] Handle myloader errors
- [ ] Verify restore completion

**Critical Implementation**:
```python
class MySQLRestorer:
    def cleanup_orphaned_staging(self, target: str, dbhost: str):
        """Drop old staging databases matching target_[0-9a-f]{12} pattern."""
        conn = self.get_host_connection(dbhost)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SCHEMA_NAME 
            FROM information_schema.SCHEMATA 
            WHERE SCHEMA_NAME REGEXP %s
        """, (f"^{target}_[0-9a-f]{{12}}$",))
        
        for row in cursor.fetchall():
            staging_db = row['SCHEMA_NAME']
            logger.info(f"Dropping orphaned staging: {staging_db}")
            cursor.execute(f"DROP DATABASE IF EXISTS `{staging_db}`")
            self.job_repo.append_job_event(
                job.id, 'staging_auto_cleanup', 
                f"Dropped: {staging_db}"
            )
    
    def restore_to_staging(self, backup_dir: Path, staging_name: str, dbhost: str):
        """Execute myloader to restore into staging database."""
        host_config = self.host_repo.get_host_config(dbhost)
        
        cmd = [
            'myloader',
            f'--directory={backup_dir}',
            f'--database={staging_name}',
            f'--host={host_config.host}',
            f'--user={host_config.user}',
            f'--password={host_config.password}',
            '--overwrite-tables',
            '--threads=4',
            '--verbose=3'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"myloader failed: {result.stderr}")
    
    def atomic_rename(self, staging_name: str, target: str, dbhost: str):
        """Atomically rename staging → target using stored procedure."""
        conn = self.get_host_connection(dbhost)
        cursor = conn.cursor()
        
        # Drop existing target
        cursor.execute(f"DROP DATABASE IF EXISTS `{target}`")
        cursor.execute(f"CREATE DATABASE `{target}`")
        
        # Create rename procedure
        cursor.execute("DROP PROCEDURE IF EXISTS RenameDatabase")
        cursor.execute(RENAME_PROCEDURE_SQL)  # From staging-rename-pattern.md
        
        # Execute rename
        cursor.execute(f"CALL RenameDatabase('{staging_name}', '{target}')")
        
        # Drop empty staging database
        cursor.execute(f"DROP DATABASE IF EXISTS `{staging_name}`")
        
        conn.commit()
```

### Milestone 7: Post-Restore SQL (Week 4)

#### 7.1 Post-SQL Executor

**File**: `pulldb/daemon/cleaner.py`

**Tasks**:
- [ ] Load SQL files from `customers_after_sql/` or `qa_template_after_sql/`
- [ ] Execute in lexicographic order (010, 020, 030...)
- [ ] Track execution status (success/failed)
- [ ] Handle SQL execution errors
- [ ] Return JSON status report
- [ ] Add pullDB metadata table to staging database
- [ ] Log execution in job_events

**Example**:
```python
class PostRestoreCleaner:
    def execute_post_sql(self, staging_name: str, customer_type: str, dbhost: str) -> dict:
        """Execute post-restore SQL scripts."""
        if customer_type == 'customer':
            sql_dir = self.config.customers_after_sql_dir
        else:
            sql_dir = self.config.qa_template_after_sql_dir
        
        conn = self.get_host_connection(dbhost)
        results = {}
        
        sql_files = sorted(Path(sql_dir).glob('*.sql'))
        for sql_file in sql_files:
            try:
                with open(sql_file) as f:
                    sql = f.read()
                
                cursor = conn.cursor()
                for statement in sql.split(';'):
                    if statement.strip():
                        cursor.execute(statement)
                conn.commit()
                results[sql_file.name] = 'success'
                
            except Exception as e:
                conn.rollback()
                results[sql_file.name] = f'failed: {str(e)}'
                raise  # Abort job on SQL failure
        
        return results
    
    def add_metadata_table(self, staging_name: str, job: Job, 
                          backup_file: str, post_sql_results: dict, dbhost: str):
        """Create pullDB metadata table in staging database."""
        conn = self.get_host_connection(dbhost)
        cursor = conn.cursor()
        
        cursor.execute(f"USE `{staging_name}`")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pullDB (
                job_id CHAR(36) PRIMARY KEY,
                restored_by VARCHAR(255) NOT NULL,
                restored_at TIMESTAMP(6) NOT NULL,
                backup_file VARCHAR(512) NOT NULL,
                post_restore_sql_status JSON NOT NULL,
                restore_completed_at TIMESTAMP(6) NOT NULL
            )
        """)
        
        cursor.execute("""
            INSERT INTO pullDB VALUES (%s, %s, UTC_TIMESTAMP(6), %s, %s, UTC_TIMESTAMP(6))
        """, (job.id, job.owner_username, backup_file, json.dumps(post_sql_results)))
        
        conn.commit()
```

### Milestone 8: Logging & Metrics (Week 4)

#### 8.1 Structured Logging

**File**: `pulldb/infra/logging.py`

**Tasks**:
- [ ] Implement JSON structured logging
- [ ] Include standard fields: timestamp, level, job_id, phase, message
- [ ] Configure file rotation
- [ ] Configure log levels per environment
- [ ] Prepare for Datadog ingestion

**Example**:
```python
import logging
import json

class StructuredLogger:
    def __init__(self, name: str, log_file: Path):
        self.logger = logging.getLogger(name)
        handler = logging.FileHandler(log_file)
        handler.setFormatter(self.JSONFormatter())
        self.logger.addHandler(handler)
    
    class JSONFormatter(logging.Formatter):
        def format(self, record):
            log_obj = {
                'timestamp': self.formatTime(record),
                'level': record.levelname,
                'message': record.getMessage(),
                'logger': record.name
            }
            if hasattr(record, 'job_id'):
                log_obj['job_id'] = record.job_id
            if hasattr(record, 'phase'):
                log_obj['phase'] = record.phase
            return json.dumps(log_obj)
```

#### 8.2 Metrics Emission

**Tasks**:
- [ ] Implement Datadog metric emission (StatsD protocol)
- [ ] Emit queue depth metric
- [ ] Emit disk capacity failure metric
- [ ] Track job duration
- [ ] Track phase durations

### Milestone 9: Testing (Week 5)

#### 9.1 Unit Tests

**Tasks**:
- [ ] Test user_code generation with collision handling
- [ ] Test target name sanitization
- [ ] Test staging name generation
- [ ] Test MySQL repositories with test database
- [ ] Test configuration loading
- [ ] Mock S3 operations with moto
- [ ] Mock subprocess calls for myloader

#### 9.2 Integration Tests

**Tasks**:
- [ ] Test complete restore flow end-to-end
- [ ] Test orphaned staging database cleanup
- [ ] Test atomic rename pattern
- [ ] Test post-restore SQL execution
- [ ] Test error handling and rollback
- [ ] Test per-target exclusivity

### Milestone 10: Deployment (Week 5-6)

#### 10.1 Deployment Package

**Tasks**:
- [ ] Create systemd service file for daemon
- [ ] Create deployment script
- [ ] Document IAM role requirements
- [ ] Document MySQL credentials setup
- [ ] Create monitoring dashboard template
- [ ] Write operational runbook

**Example systemd service**:
```ini
[Unit]
Description=pullDB Daemon
After=network.target

[Service]
Type=simple
User=pulldb
WorkingDirectory=/opt/pulldb
ExecStart=/opt/pulldb/venv/bin/pulldb-daemon
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### 10.2 Initial Deployment

**Tasks**:
- [ ] Deploy MySQL coordination database
- [ ] Populate db_hosts table with db3, db4, db5
- [ ] Populate settings table with defaults
- [ ] Deploy daemon to EC2 instance
- [ ] Configure AWS credentials and IAM
- [ ] Deploy CLI to jump box / developer machines
- [ ] Test end-to-end restore with real backup
- [ ] Monitor metrics in Datadog

## Testing Strategy

### Pre-Production Testing

1. **Local Development Testing**:
   - Use local MySQL instance
   - Mock S3 with moto
   - Test against small synthetic backups
   - Verify all unit tests pass

2. **Staging Environment Testing**:
   - Use dedicated staging MySQL coordination database
   - Use staging S3 bucket with test backups
   - Restore to isolated database server
   - Verify metrics emission
   - Test failure scenarios

3. **Production Verification**:
   - Deploy daemon to production EC2
   - Test with single real customer backup
   - Verify post-restore SQL execution
   - Verify atomic rename
   - Verify cleanup
   - Monitor logs and metrics

### Acceptance Criteria

- [ ] User can submit restore job: `pullDB user=testuser customer=testcust`
- [ ] Daemon processes job successfully
- [ ] Staging database created with pattern `testusertestcust_<job_id_short>`
- [ ] Orphaned staging databases auto-cleaned before restore
- [ ] Post-restore SQL scripts execute (verify with `SELECT * FROM pullDB`)
- [ ] Atomic rename completes without downtime
- [ ] Target database contains all expected tables and data
- [ ] Job status visible: `pullDB status`
- [ ] Logs contain structured JSON with all phases
- [ ] Metrics visible in Datadog: queue_depth, disk_failures
- [ ] Error handling preserves staging database for inspection
- [ ] Per-target exclusivity prevents concurrent restores

## Risk Mitigation

### Technical Risks

1. **myloader Compatibility**:
   - Risk: myloader version incompatibility
   - Mitigation: Pin mydumper 0.9.5, test in staging first

2. **Disk Space Exhaustion**:
   - Risk: Large backups fill disk during extraction
   - Mitigation: Pre-check available space (tar_size * 2.8), emit metrics

3. **Atomic Rename Failure**:
   - Risk: Stored procedure fails mid-rename
   - Mitigation: Preserve staging database, document manual recovery in runbook

4. **Network Interruptions**:
   - Risk: S3 download interrupted
   - Mitigation: Retry logic with exponential backoff, cleanup partial downloads

### Operational Risks

1. **Daemon Crashes**:
   - Risk: Daemon dies mid-restore
   - Mitigation: Systemd auto-restart, job stays in 'running' status for investigation

2. **Database Credentials Rotation**:
   - Risk: Credentials expire mid-restore
   - Mitigation: Use AWS Secrets Manager with auto-refresh

3. **Per-Target Lock Deadlock**:
   - Risk: Job stuck in 'running' status forever
   - Mitigation: Manual intervention documented in runbook, add watchdog in Phase 1

## Timeline

| Week | Milestone | Deliverable |
|------|-----------|-------------|
| 1 | Foundation + MySQL | Project structure, schema deployed, config module |
| 2 | CLI + Daemon Core | Working CLI, daemon polling loop |
| 3 | S3 + Restore | S3 download, myloader integration, staging pattern |
| 4 | Post-SQL + Logging | Post-restore scripts, metadata table, structured logs |
| 5 | Testing | Unit tests, integration tests passing |
| 6 | Deployment | Daemon running in production, first successful restore |

**Total**: 6 weeks to production-ready prototype

## Success Metrics

### Week 6 Goals
- [ ] 10 successful restores completed
- [ ] Zero unhandled exceptions in daemon logs
- [ ] Average job duration < 30 minutes for typical customer database
- [ ] Queue depth metric accurate in Datadog
- [ ] All 12 post-restore SQL scripts executing successfully
- [ ] Staging database auto-cleanup working (verified via manual inspection)

### Phase 0 Exit Criteria
- [ ] Prototype stable for 2 weeks in production
- [ ] No critical bugs reported
- [ ] Documentation updated with any design changes
- [ ] Operational runbook tested and validated
- [ ] Ready to begin Phase 1 (cancellation, history, scheduled cleanup)

## Next Steps

1. **Immediate**: Create GitHub project board with tasks from this plan
2. **Day 1**: Set up Python project structure and dependencies
3. **Day 2**: Deploy MySQL schema to dev environment
4. **Day 3**: Begin CLI implementation
5. **Week 2**: Begin daemon implementation
6. **Week 4**: Begin end-to-end testing
7. **Week 6**: Production deployment

## References

- Primary: `.github/copilot-instructions.md` - Architecture and constraints
- Standards: `constitution.md` - KISS principles, tooling, workflow
- API: `README.md` - Complete usage patterns and examples
- Schema: `docs/mysql-schema.md` - Database design and initialization
- Staging: `design/staging-rename-pattern.md` - MANDATORY restore pattern
- Legacy: `design/apptype-analysis.md` - appType → dbhost mapping

---

**Status**: Ready to begin implementation  
**Approval Required**: Review and approve this plan before starting  
**Questions**: Document any questions or concerns before proceeding
