# myloader Subprocess Standards

> **EXTENDS**: engineering-dna/standards/ai-agent-code-generation.md (subprocess patterns)

---

## myloader Invocation Pattern

### Binary Configuration (v1.0.8+)

**Single Binary Strategy**: pullDB uses only `myloader-0.21.1-1` for all backups.

- Legacy backups (mydumper 0.9.x format) are supported via **metadata synthesis**
- No binary selection logic needed at runtime
- Binary path: `/opt/pulldb.service/bin/myloader-0.21.1-1`

```python
# Default myloader arguments (pulldb/domain/config.py)
myloader_default_args: tuple[str, ...] = (
    "--max-threads-for-post-actions=1",
    "--rows=100000",
    "--queries-per-transaction=5000",
    "--optimize-keys=AFTER_IMPORT_PER_TABLE",
    "--checksum=warn",
    "--retry-count=20",
    "--local-infile=TRUE",
    "--ignore-errors=1146",
    "--drop-table",          # Was --overwrite-tables in myloader <0.20
    "--verbose=3",
    "--max-threads-per-table=1",
)
myloader_timeout_seconds: float = 86400.0  # 24 hours
myloader_threads: int = 4
```

### MyLoaderSpec Model

```python
from pulldb.domain.restore_models import MyLoaderSpec, build_configured_myloader_spec

# Build spec using config defaults
spec = build_configured_myloader_spec(
    config=config,
    job_id=job.job_id,
    staging_db=staging_name,
    backup_dir=str(backup_dir),
    mysql_host=host,
    mysql_port=port,
    mysql_user=user,
    mysql_password=password,
)
```

### Subprocess Execution

```python
def run_myloader(
    myloader_spec: MyLoaderSpec,
    *,
    timeout: float = 86400.0,  # 24 hours max
) -> MyLoaderResult:
    """Execute myloader restore with full error capture.
    
    FAIL HARD: Any non-zero exit code raises MyLoaderError.
    
    Args:
        myloader_spec: Full restore specification (host, user, db, etc.)
        timeout: Maximum execution time in seconds (default 24 hours)
        
    Returns:
        MyLoaderResult with stdout/stderr and timing
        
    Raises:
        MyLoaderError: On any myloader failure (preserves stderr)
    """
    cmd = [
        myloader_spec.binary_path,
        f"--host={myloader_spec.mysql_host}",
        f"--port={myloader_spec.mysql_port}",
        f"--user={myloader_spec.mysql_user}",
        f"--password={myloader_spec.mysql_password}",
        f"--database={myloader_spec.staging_db}",
        f"--directory={myloader_spec.backup_dir}",
        *myloader_spec.extra_args,
    ]
    
    # ... execution via run_command_streaming() ...
```

---

## Metadata Parsing (myloader 0.19)

myloader 0.19 uses a `metadata` file with INI-like structure.

### Key Sections

```ini
[config]
rows = 1000000
threads = 4
compress-protocol = 1

[myloader_session_variables]
sql_log_bin = 0
foreign_key_checks = 0
time_zone = '+00:00'

["database"."table"]
real_table_name = actual_name
rows = 50000
```

### Parsing Pattern

```python
import configparser
from pathlib import Path

def parse_myloader_metadata(metadata_path: Path) -> dict[str, Any]:
    """Parse myloader metadata file for restore configuration.
    
    Args:
        metadata_path: Path to extracted backup's metadata file
        
    Returns:
        Parsed configuration including table row counts
        
    Raises:
        BackupFormatError: If metadata is malformed or unreadable
    """
    if not metadata_path.exists():
        raise BackupFormatError(
            f"Metadata file not found at {metadata_path}. "
            f"Solutions: (1) Verify extraction completed, (2) Check backup integrity"
        )
    
    parser = configparser.ConfigParser()
    parser.read(metadata_path)
    
    config = {}
    
    if parser.has_section("config"):
        config["threads"] = parser.getint("config", "threads", fallback=4)
        config["rows"] = parser.getint("config", "rows", fallback=1000000)
    
    # Extract table row counts for progress estimation
    config["tables"] = {}
    for section in parser.sections():
        if section.startswith('"') and section.endswith('"'):
            # Table section: ["database"."table"]
            if parser.has_option(section, "rows"):
                config["tables"][section] = parser.getint(section, "rows")
    
    return config
```

---

## Backup Format Detection

```python
def detect_backup_format(backup_dir: Path) -> str:
    """Detect mydumper backup format from directory structure.
    
    Args:
        backup_dir: Path to extracted backup directory
        
    Returns:
        Either "legacy" (0.9.x) or "modern" (0.19.x)
        
    Raises:
        BackupFormatError: If format cannot be determined
    """
    metadata = backup_dir / "metadata"
    
    if not metadata.exists():
        # Search subdirectories for metadata
        for subdir in backup_dir.iterdir():
            if subdir.is_dir() and (subdir / "metadata").exists():
                metadata = subdir / "metadata"
                break
    
    if not metadata.exists():
        raise BackupFormatError(
            f"Cannot locate metadata file in {backup_dir}. "
            f"Expected: {backup_dir}/metadata or {backup_dir}/*/metadata"
        )
    
    content = metadata.read_text()
    
    # Modern format has [myloader_session_variables] section
    if "[myloader_session_variables]" in content:
        return "modern"
    
    # Legacy format has simpler structure
    return "legacy"
```

---

## Progress Estimation

myloader doesn't provide native progress reporting. Use row counts from metadata:

```python
def estimate_progress(
    metadata: dict[str, Any],
    restored_tables: set[str],
) -> float:
    """Estimate restore progress based on table completion.
    
    Args:
        metadata: Parsed metadata with table row counts
        restored_tables: Set of completed table names
        
    Returns:
        Progress percentage (0.0 to 100.0)
    """
    total_rows = sum(metadata.get("tables", {}).values())
    if total_rows == 0:
        return 0.0
    
    restored_rows = sum(
        metadata["tables"].get(table, 0)
        for table in restored_tables
    )
    
    return (restored_rows / total_rows) * 100
```

---

## Error Patterns

| Error Pattern | Root Cause | Solution |
|---------------|------------|----------|
| `Access denied for user` | Insufficient MySQL privileges | GRANT ALL on target database |
| `Unknown database` | Staging DB not created | Create database before restore |
| `Got a packet bigger than` | Large blob/text data | Increase max_allowed_packet |
| `Lock wait timeout` | Concurrent access | Exclusive lock during restore |
| `Disk full` | Insufficient space | Verify disk preflight passed |

---

## Integration with Worker Service

```python
# In pulldb/worker/restore.py

from pulldb.domain.config import Config
from pulldb.domain.restore_models import build_configured_myloader_spec
from pulldb.worker.restore import run_restore_workflow, RestoreWorkflowSpec

def execute_restore(job: Job, backup_dir: Path, config: Config) -> None:
    """Orchestrate full restore operation.
    
    FAIL HARD: Any step failure stops the restore immediately.
    """
    # Build myloader spec from config (applies all defaults)
    myloader_spec = build_configured_myloader_spec(
        config=config,
        job_id=job.job_id,
        staging_db=job.staging_database,
        backup_dir=str(backup_dir),
        mysql_host=config.mysql_host,
        mysql_port=config.mysql_port,
        mysql_user=config.mysql_user,
        mysql_password=config.mysql_password,
    )
    
    # Execute via workflow spec
    workflow_spec = RestoreWorkflowSpec(
        job=job,
        backup_filename=backup_filename,
        staging_conn=staging_conn,
        post_sql_conn=post_sql_conn,
        myloader_spec=myloader_spec,
        timeout=config.myloader_timeout_seconds,
    )
    
    run_restore_workflow(workflow_spec)
```

---

## Key Files

| File | Purpose |
|------|---------|
| `pulldb/domain/restore_models.py` | `MyLoaderSpec`, `build_configured_myloader_spec()` |
| `pulldb/domain/config.py` | Default args, binary path, timeout |
| `pulldb/worker/restore.py` | Execution wrapper, error translation |
| `pulldb/worker/backup_metadata.py` | Metadata synthesis for legacy backups |

---

## Related

- [engineering-dna/standards/ai-agent-code-generation.md](../../engineering-dna/standards/ai-agent-code-generation.md) - Base subprocess patterns
- [engineering-dna/protocols/fail-hard.md](../../engineering-dna/protocols/fail-hard.md) - Error handling requirements
- [docs/KNOWLEDGE-POOL.md](../../docs/KNOWLEDGE-POOL.md) - myloader binary locations, metadata format details
