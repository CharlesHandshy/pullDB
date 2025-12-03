# HCA Standard for pullDB

> **Hierarchical Containment Architecture** applied to pullDB development.
> This document ensures all development follows HCA's 6 Laws.

## Quick Reference

```
LAW 1: Flat Locality      → No deeply nested folders
LAW 2: Explicit Naming    → Names include parent context  
LAW 3: Single Parent      → Each file has ONE owner
LAW 4: Layer Isolation    → Layers only import downward
LAW 5: Cross-Layer Bridge → widgets/ bridges features
LAW 6: Plugin Escape      → External code in plugins/
```

## pullDB Layer Model

```
┌─────────────────────────────────────────────────────────┐
│                     plugins/                            │ External integrations
├─────────────────────────────────────────────────────────┤
│                      pages/                             │ CLI commands, web routes
├─────────────────────────────────────────────────────────┤
│                     widgets/                            │ Composed features (job orchestration)
├─────────────────────────────────────────────────────────┤
│                    features/                            │ Business logic (restore, download)
├─────────────────────────────────────────────────────────┤
│                    entities/                            │ Domain models (Job, Config, Backup)
├─────────────────────────────────────────────────────────┤
│                     shared/                             │ Infra (mysql, s3, secrets, logging)
└─────────────────────────────────────────────────────────┘
```

## Layer-to-Directory Mapping

| HCA Layer | pullDB Directory | Contents |
|-----------|------------------|----------|
| **shared** | `pulldb/infra/` | mysql.py, s3.py, secrets.py, logging.py |
| **entities** | `pulldb/domain/` | models.py, config.py, errors.py |
| **features** | `pulldb/worker/` | restore_job.py, downloader.py, staging.py |
| **widgets** | `pulldb/worker/service.py` | Job orchestration combining features |
| **pages** | `pulldb/cli/`, `pulldb/web/` | User-facing entry points |
| **plugins** | `pulldb/binaries/` | myloader, external tools |

## Import Rules (Law 4: Layer Isolation)

```python
# ✅ ALLOWED - importing from lower layer
from pulldb.infra.mysql import MySQLClient      # shared → feature
from pulldb.domain.models import Job            # entities → feature
from pulldb.worker.restore_job import RestoreJob # features → widget

# ❌ FORBIDDEN - importing from higher layer
from pulldb.cli.commands import restore_cmd     # pages → feature (VIOLATION)
from pulldb.worker.service import WorkerService # widgets → feature (VIOLATION)
```

## Naming Convention (Law 2: Explicit Naming)

Files should include parent context in their name:

```
# ✅ GOOD - explicit naming
pulldb/infra/mysql_client.py       # Layer + purpose
pulldb/worker/restore_job.py       # Feature + job type
pulldb/cli/restore_command.py      # CLI + action

# ❌ BAD - ambiguous naming
pulldb/infra/client.py             # What kind of client?
pulldb/worker/job.py               # What does it restore?
pulldb/cli/command.py              # What command?
```

## File Placement Decision Tree

```
┌─ Does it interact with external systems (S3, MySQL, secrets)?
│  └─ YES → pulldb/infra/ (shared layer)
│
├─ Is it a data model, config, or error definition?
│  └─ YES → pulldb/domain/ (entities layer)
│
├─ Is it a single business operation (download, restore, stage)?
│  └─ YES → pulldb/worker/*.py (features layer)
│
├─ Does it orchestrate multiple features?
│  └─ YES → pulldb/worker/service.py (widgets layer)
│
├─ Is it a user entry point (CLI, API, web)?
│  └─ YES → pulldb/cli/, pulldb/api/, pulldb/web/ (pages layer)
│
└─ Is it an external binary or third-party integration?
   └─ YES → pulldb/binaries/ (plugins layer)
```

## HCA Enforcement Checklist

Before committing code, verify:

- [ ] **Single Parent**: File lives in exactly ONE directory
- [ ] **Downward Imports**: Only imports from same or lower layers
- [ ] **Explicit Naming**: File name includes layer context
- [ ] **No Deep Nesting**: Maximum 2 directory levels from layer root
- [ ] **No Circular Dependencies**: Features don't import from widgets/pages

## Common Violations & Fixes

### Violation: Feature importing from Widget

```python
# ❌ restore_job.py importing from service.py
from pulldb.worker.service import get_worker_config

# ✅ FIX: Extract shared config to domain layer
from pulldb.domain.config import get_worker_config
```

### Violation: Shared importing from Feature

```python
# ❌ mysql.py importing from restore_job.py
from pulldb.worker.restore_job import JobStatus

# ✅ FIX: Move JobStatus to domain layer
from pulldb.domain.models import JobStatus
```

### Violation: Ambiguous File Location

```python
# ❌ utils.py floating in root
pulldb/utils.py  # WHERE DOES THIS GO?

# ✅ FIX: Split by layer purpose
pulldb/infra/logging_utils.py    # If logging-related
pulldb/domain/validation.py      # If domain validation
```

## Documentation HCA Alignment

Documentation follows same layer model:

```
docs/
├── shared/          # Universal patterns (logging, errors)
├── entities/        # Data models, schema, config formats
├── features/        # Individual feature docs (restore, download)
├── widgets/         # Integration guides (worker setup)
├── pages/           # User guides (CLI reference, web UI)
└── plugins/         # External tool docs (myloader, terraform)
```

## Integration with Copilot Instructions

When Copilot creates new files, it MUST:

1. **Determine the HCA layer** using the decision tree above
2. **Place file in correct directory** per layer mapping
3. **Name file explicitly** with layer context
4. **Validate imports** follow downward-only rule
5. **Add to test coverage** in corresponding `tests/` subdirectory

## See Also

- [Full HCA Methodology](../docs/IngestMe/HCA/hierarchical-containment-architect.md)
- [HCA Agent Activation](../docs/IngestMe/HCA/hca-agent-activation.md)
- [HCA Agent Training](../docs/IngestMe/HCA/hca-agent-training.md)
- [HCA Documentation Audit](../docs/HCA-DOCUMENTATION-AUDIT.md)
