# Widgets Layer Documentation

> Service orchestration combining multiple features.
> Code location: `pulldb/worker/service.py`

## Documents

| Document | Purpose | Status |
|----------|---------|--------|
| [deployment.md](deployment.md) | Service deployment guide | ✅ Active |
| [worker-service.md](worker-service.md) | Worker service architecture | 📝 Planned |
| [api-service.md](api-service.md) | API service architecture | 📝 Planned |
| [architecture.md](architecture.md) | System architecture | ✅ Active |

## Widget Role

Widgets **orchestrate** features but don't contain business logic:

```python
class WorkerService:
    """Widget: orchestrates download → restore → post-sql features."""
    
    def __init__(self):
        self.downloader = Downloader()    # feature
        self.restore = RestoreJob()       # feature
        self.post_sql = PostSQLRunner()   # feature
    
    def process_job(self, job: Job):
        # Orchestration only - no business logic here
        backup = self.downloader.download(job.backup_s3_path)
        self.restore.execute(backup, job.target_database)
        self.post_sql.run(job.target_database)
```

## Integration Points

```
┌─────────────────────────────────────────────────────┐
│                    WorkerService                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │Downloader│→ │RestoreJob│→ │PostSQLRunner     │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
│       ↓             ↓              ↓               │
│  ┌─────────────────────────────────────────────┐   │
│  │              MySQL Queue                     │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

## Related

- [../features/](../features/) - Features composed by widgets
- [../pages/](../pages/) - User interfaces that invoke widgets
