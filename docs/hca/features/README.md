# Features Layer Documentation

> Individual business operations (restore, download, staging).
> Code location: `pulldb/worker/*.py`

## Documents

| Document | Purpose | Status |
|----------|---------|--------|
| [staging.md](staging.md) | Staging database lifecycle | ✅ Active |
| [atomic_rename_procedure.sql](atomic_rename_procedure.sql) | Atomic rename stored procedure | ✅ Active |
| [restore.md](restore.md) | Restore workflow | 📝 Planned |
| [download.md](download.md) | S3 download patterns | 📝 Planned |
| [post-sql.md](post-sql.md) | Post-restore SQL execution | 📝 Planned |

## Feature Boundaries

Each feature is **self-contained**:
- Downloads from S3
- Creates staging database
- Runs myloader restore
- Executes post-SQL scripts
- Performs atomic rename

## Feature Dependencies

```
download.py     → infra/s3.py, domain/models.py
staging.py      → infra/mysql.py, domain/config.py
restore_job.py  → staging.py, download.py, domain/models.py
post_sql.py     → infra/mysql.py, domain/config.py
```

## Key Patterns

### Feature Isolation

Features import ONLY from lower layers:
```python
# ✅ ALLOWED
from pulldb.infra.mysql import MySQLClient
from pulldb.domain.models import Job

# ❌ FORBIDDEN - importing from widgets
from pulldb.worker.service import WorkerService
```

### Feature Composition

Features are composed in `service.py` (widgets layer), not within features:
```python
# service.py (widget) composes features
class WorkerService:
    def process_job(self):
        self.downloader.download()      # feature
        self.restore.execute()          # feature
        self.post_sql.run()             # feature
```

## Related

- [../entities/](../entities/) - Data models used by features
- [../widgets/](../widgets/) - Service that composes features
