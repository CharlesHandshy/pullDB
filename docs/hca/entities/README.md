# Entities Layer Documentation

> Data models, schema definitions, and configuration formats.
> Code location: `pulldb/domain/`

## Documents

| Document | Purpose | Status |
|----------|---------|--------|
| [mysql-schema.md](mysql-schema.md) | Database schema reference | ✅ Active |
| [models.md](models.md) | Domain model definitions | 📝 Planned |
| [config.md](config.md) | Configuration formats | 📝 Planned |
| [errors.md](errors.md) | Error type definitions | 📝 Planned |

## Key Models

### Job Model

```python
@dataclass
class Job:
    job_id: int
    target_id: int
    status: JobStatus
    backup_s3_path: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
```

### Configuration

```python
@dataclass
class WorkerConfig:
    mysql_host: str
    mysql_port: int
    s3_bucket: str
    download_dir: Path
    myloader_path: Path
```

## Schema Invariants

1. **Per-target exclusivity**: Only ONE active job per target
2. **State machine**: Jobs follow defined status transitions
3. **Audit trail**: All state changes logged with timestamps

## Related

- [../shared/](../shared/) - Infrastructure used by entities
- [../features/](../features/) - Features that operate on entities
