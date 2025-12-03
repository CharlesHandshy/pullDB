# Plugins Layer Documentation

> External integrations and third-party tools.
> Code location: `pulldb/binaries/`

## Documents

| Document | Purpose | Status |
|----------|---------|--------|
| [myloader.md](myloader.md) | myloader usage & patterns | ✅ Active |
| [policies/](policies/) | IAM policy templates | ✅ Active |
| [terraform/](terraform/) | Infrastructure as code | ✅ Active |

## External Tools

### myloader

mydumper/myloader suite for MySQL backup/restore:
- Location: `/usr/bin/myloader` or `pulldb/binaries/`
- Purpose: Fast parallel restore of MySQL dumps
- Wrapper: `pulldb/worker/myloader_wrapper.py`

### Terraform

Infrastructure provisioning:
- Location: `docs/terraform/`
- Purpose: AWS resource management
- Templates: IAM, S3, RDS policies

## Plugin Pattern

Plugins are wrapped, never called directly:

```python
# ✅ GOOD - wrapped plugin
from pulldb.worker.myloader_wrapper import MyloaderWrapper
wrapper = MyloaderWrapper()
wrapper.restore(backup_dir, database)

# ❌ BAD - direct subprocess
import subprocess
subprocess.run(['myloader', '--directory', backup_dir])
```

## Isolation Rules

Plugins have special escape hatch (HCA Law 6):
- Can access external filesystems
- Can execute subprocesses
- Must be wrapped with error handling
- FAIL HARD on subprocess errors

## Related

- [../../.pulldb/standards/myloader.md](../../../.pulldb/standards/myloader.md) - myloader patterns
- [../features/](../features/) - Features that use plugins
