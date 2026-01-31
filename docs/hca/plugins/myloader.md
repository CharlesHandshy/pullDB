# myloader Subprocess Standards

> ⚠️ **REDIRECTED**: This file has been consolidated.

**Authoritative Source:** [.pulldb/standards/myloader.md](../../../.pulldb/standards/myloader.md)

---

## Quick Reference (v1.0.8)

| Setting | Value |
|---------|-------|
| Binary | `/opt/pulldb.service/bin/myloader-0.21.1-1` |
| Timeout | 86400 seconds (24 hours) |
| Threads | 4 (configurable) |
| Drop mode | `--drop-table` (was `--overwrite-tables` in <0.20) |

## Key Files

| File | Purpose |
|------|---------|
| `pulldb/domain/restore_models.py` | `MyLoaderSpec`, `build_configured_myloader_spec()` |
| `pulldb/domain/config.py` | Default args, binary path, timeout |
| `pulldb/worker/restore.py` | Execution wrapper, error translation |
| `pulldb/worker/backup_metadata.py` | Metadata synthesis for legacy backups |

For complete documentation, see [.pulldb/standards/myloader.md](../../../.pulldb/standards/myloader.md).
