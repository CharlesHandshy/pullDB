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

---

## Nested HCA Boundaries

Some packages implement their own internal HCA structure. These are **isolated subsystems** with their own layer hierarchy.

### Simulation Package (`pulldb/simulation/`)

The simulation package is a self-contained subsystem for testing with mock adapters. It has its own HCA boundary:

```
┌─────────────────────────────────────────────────────────────────┐
│                    pulldb/simulation/                           │
│                   (Isolated HCA Boundary)                       │
├─────────────────────────────────────────────────────────────────┤
│ pages/    │ api/router.py           │ Simulation control API    │
├───────────┼─────────────────────────┼───────────────────────────┤
│ features/ │ core/engine.py          │ Simulation orchestration  │
│           │ core/scenarios.py       │ Chaos scenario logic      │
│           │ core/queue_runner.py    │ Mock worker loop          │
│           │ core/seeding.py         │ Test data generation      │
│           │ core/state.py           │ Global simulation state   │
│           │ core/bus.py             │ Event bus system          │
├───────────┼─────────────────────────┼───────────────────────────┤
│ shared/   │ adapters/mock_mysql.py  │ In-memory repositories    │
│           │ adapters/mock_s3.py     │ Mock S3 client            │
│           │ adapters/mock_exec.py   │ Mock command executor     │
└───────────┴─────────────────────────┴───────────────────────────┘
```

**Boundary Contract:**
- External code imports ONLY through `pulldb/simulation/__init__.py`
- Internal imports stay within boundary (adapters → core → api)
- Adapters implement protocols from `pulldb/domain/interfaces.py`

**Allowed External Access:**
```python
# ✅ GOOD - import through package root
from pulldb.simulation import MockJobRepository, SimulationEngine

# ❌ BAD - reaching into internal structure
from pulldb.simulation.adapters.mock_mysql import MockJobRepository
```

### Web Package (`pulldb/web/`)

The web package follows HCA for UI component organization:

```
┌─────────────────────────────────────────────────────────────────┐
│                       pulldb/web/                               │
│                    (HCA UI Structure)                           │
├─────────────────────────────────────────────────────────────────┤
│ pages/    │ pages/admin/            │ Admin page templates      │
│           │ pages/dashboard/        │ Dashboard templates       │
│           │ pages/error/            │ Error page templates      │
│           │ features/*/routes.py    │ Feature route handlers    │
├───────────┼─────────────────────────┼───────────────────────────┤
│ widgets/  │ widgets/sidebar/        │ Navigation sidebar        │
│           │ widgets/job_table/      │ Job listing table         │
│           │ widgets/filter_bar/     │ Search/filter controls    │
│           │ widgets/stats_cards/    │ Dashboard stat cards      │
├───────────┼─────────────────────────┼───────────────────────────┤
│ features/ │ features/auth/          │ Auth routes & logic       │
│           │ features/dashboard/     │ Dashboard feature         │
│           │ features/jobs/          │ Job management feature    │
│           │ features/admin/         │ Admin feature             │
├───────────┼─────────────────────────┼───────────────────────────┤
│ entities/ │ entities/job/           │ Job HTML components       │
│           │ entities/user/          │ User HTML components      │
│           │ entities/host/          │ Host HTML components      │
├───────────┼─────────────────────────┼───────────────────────────┤
│ shared/   │ shared/layouts/         │ Base layout templates     │
│           │ shared/ui/              │ Reusable UI components    │
│           │ shared/contracts/       │ Type definitions          │
│           │ shared/utils/           │ Utility functions         │
└───────────┴─────────────────────────┴───────────────────────────┘
```

**Web HCA Import Rules:**
- `shared/` → No web-internal imports
- `entities/` → May import from `shared/`
- `features/` → May import from `shared/`, `entities/`
- `widgets/` → May import from `shared/`, `entities/`, `features/`
- `pages/` → May import from all lower layers

### Auth Package (`pulldb/auth/`)

The auth package is **shared layer** infrastructure:

| File | Layer | Purpose |
|------|-------|---------|
| `password.py` | shared | Bcrypt hashing utilities |
| `repository.py` | shared | Auth credential storage |

These are foundational infrastructure, so they belong in the shared layer and can be imported by any higher layer.

---

## HCA Validation

Use the workspace index generator to check for HCA violations:

```bash
# Check for violations
python scripts/generate_workspace_index.py --check

# Regenerate index with current violations as baseline
python scripts/generate_workspace_index.py --set-baseline
```

The CI workflow (`workspace-index-check.yml`) runs on every PR to detect new violations.

---

## See Also

- [Full HCA Methodology](../docs/IngestMe/HCA/hierarchical-containment-architect.md)
- [HCA Agent Activation](../docs/IngestMe/HCA/hca-agent-activation.md)
- [HCA Agent Training](../docs/IngestMe/HCA/hca-agent-training.md)
- [HCA Documentation Audit](../docs/HCA-DOCUMENTATION-AUDIT.md)
