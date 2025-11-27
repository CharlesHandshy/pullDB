# myloader Subprocess Standards

> **EXTENDS**: engineering-dna/standards/ai-agent-code-generation.md (subprocess patterns)

---

## myloader Invocation Pattern

### Binary Selection

```python
MYLOADER_BINARIES = {
    "0.9.5": "/opt/pulldb.service/bin/myloader-0.9.5",    # Older mydumper format
    "0.19.3": "/opt/pulldb.service/bin/myloader-0.19.3-3", # Newer mydumper format
}

def select_myloader(backup_format: str) -> Path:
    """Select appropriate myloader binary based on backup format.
    
    Args:
        backup_format: Either "legacy" or "modern" (detected from metadata)
    
    Returns:
        Path to the correct myloader binary
        
    Raises:
        RestoreConfigError: If binary not found or format unknown
    """
    version = "0.9.5" if backup_format == "legacy" else "0.19.3"
    binary = Path(MYLOADER_BINARIES[version])
    
    if not binary.exists():
        raise RestoreConfigError(
            f"myloader binary not found at {binary}. "
            f"Install with: make install-myloader"
        )
    
    return binary
```

### Subprocess Execution

```python
def run_myloader(
    binary: Path,
    directory: Path,
    host: str,
    user: str,
    password: str,
    database: str,
    threads: int = 4,
    *,
    job_id: str,
) -> subprocess.CompletedProcess:
    """Execute myloader restore with full error capture.
    
    FAIL HARD: Any non-zero exit code raises RestoreExecutionError.
    
    Args:
        binary: Path to myloader binary
        directory: Extracted backup directory containing SQL files
        host: Target MySQL host
        user: MySQL user with restore privileges
        password: MySQL password
        database: Target database name
        threads: Parallel restore threads (default 4)
        job_id: Job ID for logging context
        
    Returns:
        CompletedProcess on success
        
    Raises:
        RestoreExecutionError: On any myloader failure (preserves stderr)
    """
    cmd = [
        str(binary),
        f"--host={host}",
        f"--user={user}",
        f"--password={password}",
        f"--database={database}",
        f"--directory={directory}",
        f"--threads={threads}",
        "--overwrite-tables",
        "--verbose=3",
    ]
    
    logger.info("myloader_start", job_id=job_id, database=database, threads=threads)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max
            check=False,   # We handle errors ourselves
        )
    except subprocess.TimeoutExpired as e:
        raise RestoreExecutionError(
            f"myloader timed out after 3600s. "
            f"Job: {job_id}, Database: {database}. "
            f"Solutions: (1) Increase timeout, (2) Check disk I/O, (3) Reduce data size"
        ) from e
    
    if result.returncode != 0:
        # Parse stderr for specific error patterns
        stderr = result.stderr or ""
        
        if "Access denied" in stderr:
            raise RestoreExecutionError(
                f"MySQL access denied during restore. "
                f"User: {user}, Host: {host}, Database: {database}. "
                f"Solutions: (1) Verify GRANT privileges, (2) Check password, (3) Verify host allowlist"
            )
        elif "doesn't exist" in stderr and "database" in stderr.lower():
            raise RestoreExecutionError(
                f"Target database does not exist. "
                f"Database: {database}. "
                f"Solutions: (1) Create database first, (2) Check staging name generation"
            )
        else:
            raise RestoreExecutionError(
                f"myloader failed with exit code {result.returncode}. "
                f"Job: {job_id}, Database: {database}. "
                f"stderr: {stderr[:500]}..."
            )
    
    logger.info("myloader_complete", job_id=job_id, database=database)
    return result
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
# In worker/restore.py

from pulldb.infra.exec import run_myloader, select_myloader, detect_backup_format

def execute_restore(job: Job, backup_dir: Path, credentials: MySQLCredentials) -> None:
    """Orchestrate full restore operation.
    
    FAIL HARD: Any step failure stops the restore immediately.
    """
    # 1. Detect format
    format_type = detect_backup_format(backup_dir)
    logger.info("backup_format_detected", job_id=job.job_id, format=format_type)
    
    # 2. Select binary
    binary = select_myloader(format_type)
    
    # 3. Execute restore
    run_myloader(
        binary=binary,
        directory=backup_dir,
        host=credentials.host,
        user=credentials.username,
        password=credentials.password,
        database=job.staging_database,
        job_id=job.job_id,
    )
```

---

## Related

- [engineering-dna/standards/ai-agent-code-generation.md](../../engineering-dna/standards/ai-agent-code-generation.md) - Base subprocess patterns
- [engineering-dna/protocols/fail-hard.md](../../engineering-dna/protocols/fail-hard.md) - Error handling requirements
- [docs/KNOWLEDGE-POOL.md](../../docs/KNOWLEDGE-POOL.md) - myloader binary locations, metadata format details
