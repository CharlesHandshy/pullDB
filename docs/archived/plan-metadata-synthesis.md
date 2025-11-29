# Plan: Metadata Synthesis for Legacy Backup Support

## Context
We are unifying the restore architecture on `myloader` v0.19 to leverage its advanced features (per-table threading, better resource management). However, we must support legacy backups created by `mydumper` v0.9.

## The Problem
`myloader` v0.19 requires a `metadata` file in a specific INI-like format to identify tables and manage parallel execution.
- **v0.9 Metadata**: Simple text file with timestamps and binlog coordinates. No table listing.
- **v0.19 Metadata**: INI format listing every table, row counts, and config.

Without this file, `myloader` v0.19 may fail or fall back to single-threaded mode (or simply not know what to load if it relies on the metadata for the table list).

## Solution: Metadata Synthesis
We will implement a "Metadata Synthesizer" step in the restore workflow. Before invoking `myloader`, the system will:
1.  Check if the backup is "legacy" (missing valid INI metadata).
2.  If legacy, scan the directory for data files.
3.  Generate a v0.19-compatible `metadata` file.

## Technical Implementation

### 1. File Naming Conventions
`mydumper` produces files in the format:
- Schema: `database-schema-create.sql.gz`
- Tables: `database.table-schema.sql.gz`
- Data: `database.table.sql.gz` or `database.table.00001.sql.gz` (chunked)

We need to parse these filenames to extract `database` and `table` names.

### 2. Metadata Format (v0.19)
The target format is:

```ini
[config]
quote-character = BACKTICK
local-infile = 1

[myloader_session_variables]
SQL_MODE='NO_AUTO_VALUE_ON_ZERO,' /*!40101

[source]
File = mysql-bin.000001  # Optional, extracted from legacy metadata if possible
Position = 123           # Optional

[`database`.`table`]
real_table_name=table
rows = 0                 # Can default to 0 if unknown
```

### 3. Synthesis Logic
The synthesizer will be a Python function in `pulldb/worker/restore.py` (or a utility module).

**Steps:**
1.  **Scan Directory**: List all files matching `*.sql.gz` (and `.sql`, `.zst`).
2.  **Parse Filenames**:
    *   Ignore `-schema.sql.gz` and `-schema-create.sql.gz`.
    *   Extract `db` and `table` from `db.table.sql.gz`.
    *   Handle chunked files (deduplicate tables).
3.  **Read Legacy Metadata (Optional)**:
    *   If a `metadata` file exists but is not INI (check first line/structure), parse it to get `Started dump at` and binlog info.
4.  **Generate Content**:
    *   Write `[config]` and `[myloader_session_variables]` with safe defaults.
    *   Write `[source]` using parsed legacy metadata or defaults.
    *   Iterate through identified tables and write `[db.table]` sections.
5.  **Write File**: Overwrite (or create) the `metadata` file.

### 4. Integration Point
In `pulldb/worker/restore.py`:
```python
def prepare_backup_for_restore(backup_dir: str):
    if is_legacy_backup(backup_dir):
        logger.info("Detected legacy backup. Synthesizing metadata...")
        synthesize_metadata(backup_dir)
```

This should be called after download and before `myloader` execution.

## Verification Plan
1.  **Prototype**: Create a script `scripts/synthesize_metadata.py` to test against a mock directory of empty files.
2.  **Integration Test**: Update `manual_integration_test_09.py` to use this synthesizer and verify `myloader` 0.19 accepts the result.

## Open Questions
- **Row Counts**: Does `myloader` use `rows` for progress calculation only, or for load balancing?
    - *Assumption*: It's for progress. `0` is safe but might break progress bars (acceptable for legacy).
- **Compression**: Does `myloader` auto-detect `.gz` vs `.zst` regardless of metadata?
    - *Assumption*: Yes, based on file extension.

## Next Steps
1.  Implement `scripts/synthesize_metadata.py`.
2.  Verify it generates a file matching the structure of `appalachian/metadata`.
