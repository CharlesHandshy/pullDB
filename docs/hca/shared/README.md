# Shared Layer Documentation

> Infrastructure patterns used by ALL other layers.
> Code location: `pulldb/infra/`

## Documents

| Document | Purpose | Status |
|----------|---------|--------|
| [configuration.md](configuration.md) | **All configurable variables** | ✅ Active |
| [FAIL-HARD.md](FAIL-HARD.md) | Error handling philosophy | ✅ Active |
| [mysql.md](mysql.md) | MySQL client patterns | 📝 Planned |
| [s3.md](s3.md) | S3 access patterns | 📝 Planned |
| [secrets.md](secrets.md) | Secrets Manager patterns | 📝 Planned |
| [logging.md](logging.md) | Logging configuration | 📝 Planned |

## Key Patterns

### FAIL HARD Protocol

Every shared component follows FAIL HARD:
1. **Never silently degrade** - Raise explicit exceptions
2. **Context in errors** - Include what, why, solutions
3. **No fallback behaviors** - Fail clearly, fix correctly

### Infrastructure Boundaries

```python
# pulldb/infra/ exports clean interfaces
from pulldb.infra import MySQLClient, S3Client, SecretsManager

# Upper layers never touch internals
# ✅ GOOD
client = MySQLClient()
# ❌ BAD  
from pulldb.infra.mysql import _internal_connection_pool
```

## Related

- [../entities/](../entities/) - Data models that use infra
- [../../.pulldb/standards/hca.md](../../../.pulldb/standards/hca.md) - Layer rules
