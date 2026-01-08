# Aurora MySQL Compatibility Notes

[← Back to Features](README.md)

> **Version**: 1.0.0 | **Updated**: January 2025

This document describes AWS Aurora MySQL compatibility considerations and workarounds implemented in pullDB.

---

## Overview

AWS Aurora MySQL is wire-protocol compatible with MySQL but has behavioral differences that affect stored procedure deployment and management.

---

## Key Differences

### 1. Comment Stripping in Stored Procedures

**Issue**: Aurora MySQL strips comments from stored procedure bodies when storing them in `information_schema.ROUTINES`.

**Impact**: Version verification by comparing procedure body text fails because comments (including version headers) are removed.

**Workaround**: 
- Store procedure deployment history in `procedure_deployments` table
- Verify procedure existence only, not body content
- Track versions via deployment metadata, not procedure comments

**Implementation**: See [pulldb/worker/atomic_rename.py](../../../pulldb/worker/atomic_rename.py#L) `ensure_atomic_rename_procedure()`

**Schema**: See [schema/pulldb_service/00800_procedure_deployments.sql](../../../schema/pulldb_service/00800_procedure_deployments.sql)

### 2. DELIMITER Statement Handling

**Issue**: Aurora MySQL's programmatic SQL execution doesn't support `DELIMITER` statements like the CLI does.

**Impact**: SQL files containing `DELIMITER $$` cannot be executed line-by-line using `cursor.execute()`.

**Workaround**:
```python
# Strip DELIMITER lines and split on the actual delimiter
sql_content = re.sub(r'^\s*DELIMITER\s+\S+\s*$', '', sql_content, flags=re.MULTILINE)
statements = [s.strip() for s in sql_content.split('$$') if s.strip()]
for statement in statements:
    cursor.execute(statement)
```

**Implementation**: See [pulldb/worker/atomic_rename.py](../../../pulldb/worker/atomic_rename.py#L) `ensure_atomic_rename_procedure()`

**Reference**: This approach is proven and used successfully in [pulldb/infra/mysql_provisioning.py](../../../pulldb/infra/mysql_provisioning.py#L) `deploy_atomic_rename_procedure()`

---

## Required Privileges

### Background

Atomic rename operations use stored procedures to perform transactional database renames. The `pulldb_loader` user must be able to:
1. Deploy stored procedures (`CREATE ROUTINE`, `ALTER ROUTINE`)
2. Execute stored procedures (`EXECUTE`)
3. View other sessions for advisory lock management (`PROCESS`)

### Minimum Required Grants

```sql
GRANT CREATE, DROP, ALTER, INDEX, INSERT, UPDATE, DELETE, SELECT,
      LOCK TABLES, TRIGGER, CREATE VIEW, CREATE ROUTINE, ALTER ROUTINE,
      REFERENCES, EVENT, EXECUTE, PROCESS
ON *.* TO 'pulldb_loader'@'%';
```

### Privilege Descriptions

| Privilege | Purpose |
|-----------|---------|
| `CREATE ROUTINE` | Deploy new stored procedures |
| `ALTER ROUTINE` | Modify existing stored procedures |
| `EXECUTE` | Run stored procedures (atomic rename) |
| `PROCESS` | View other sessions for advisory lock coordination |
| Other privileges | Standard restore operations (DDL/DML) |

### Privilege Setup

Privileges are automatically granted when provisioning target hosts via [pulldb/infra/mysql_provisioning.py](../../../pulldb/infra/mysql_provisioning.py).

For manual setup, see:
- [docs/hca/entities/mysql-schema.md](../entities/mysql-schema.md) - Loader user documentation
- [schema/pulldb_service/03000_mysql_users.sql](../../../schema/pulldb_service/03000_mysql_users.sql) - SQL reference

---

## Version Tracking

### procedure_deployments Table

Created by [schema/pulldb_service/00800_procedure_deployments.sql](../../../schema/pulldb_service/00800_procedure_deployments.sql)

```sql
CREATE TABLE IF NOT EXISTS procedure_deployments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    host VARCHAR(255) NOT NULL,
    procedure_name VARCHAR(255) NOT NULL,
    version_deployed VARCHAR(50) NOT NULL,
    deployed_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    deployed_by VARCHAR(255) NULL,
    deployment_reason TEXT NULL,
    job_id CHAR(36) NULL,
    UNIQUE KEY idx_host_procedure_version (host, procedure_name, version_deployed)
);
```

**Purpose**: Track which procedure versions have been deployed to which hosts, since procedure body comments are stripped by Aurora.

**Usage**: Before deploying a procedure, check if the version is already deployed to avoid unnecessary deployments.

---

## Testing Notes

### Aurora-Specific Testing

Test on actual Aurora MySQL instances when possible. Behavioral differences may not be evident in standard MySQL.

**Test Coverage**:
- ✅ Procedure deployment with version tracking
- ✅ Procedure execution with streaming progress
- ✅ Advisory lock management with long hostnames (>40 chars)
- ✅ Pre/post validation of atomic rename operations
- ✅ Error handling for missing staging, empty staging, target conflicts

### Known Working Configuration

```
Aurora MySQL 8.0.mysql_aurora.3.10.1
Python 3.12
mysql-connector-python 9.5.0
```

---

## Related Documentation

- [atomic_rename_procedure.sql](atomic_rename_procedure.sql) - Stored procedure definition
- [mysql-schema.md](../entities/mysql-schema.md) - User privileges
- [security.md](../widgets/security.md) - Security model
- [ATOMIC-RENAME-FIX-PLAN.md](../../../ATOMIC-RENAME-FIX-PLAN.md) - Implementation plan

---

## Troubleshooting

### Procedure Deployment Fails

**Symptom**: `CREATE PROCEDURE` statement fails with syntax error

**Cause**: SQL file contains `DELIMITER` statements not supported programmatically

**Solution**: Ensure `ensure_atomic_rename_procedure()` uses the proven parsing approach:
```python
sql_content = re.sub(r'^\s*DELIMITER\s+\S+\s*$', '', sql_content, flags=re.MULTILINE)
statements = [s.strip() for s in sql_content.split('$$') if s.strip()]
```

### Version Verification Fails

**Symptom**: Procedure deploys repeatedly even though it exists

**Cause**: Version comment not found in procedure body (Aurora strips comments)

**Solution**: Check `procedure_deployments` table, not procedure body:
```python
cursor.execute(
    "SELECT version_deployed FROM procedure_deployments "
    "WHERE host = %s AND procedure_name = %s "
    "ORDER BY deployed_at DESC LIMIT 1",
    (host, procedure_name)
)
```

### Lock Name Too Long

**Symptom**: `Error 1059: Identifier name 'pulldb_atomic_rename_<very-long-hostname>' is too long`

**Cause**: Aurora hostnames can exceed 40 characters, pushing lock names over 64-char limit

**Solution**: Hash long hostnames (already implemented):
```python
if len(hostname) > 40:
    # Use MD5 hash to keep lock name under 64 chars
    hostname_hash = hashlib.md5(hostname.encode()).hexdigest()[:8]
    lock_name = f"pulldb_atomic_rename_{hostname_hash}"
```

---

## Future Considerations

### Procedure Versioning Strategy

Current approach uses `procedure_deployments` table to track versions. Alternative approaches:

1. **Procedure parameters**: Add version as input parameter (visible in SHOW CREATE PROCEDURE)
2. **Separate version table per procedure**: More granular tracking
3. **Checksum verification**: Hash procedure body and compare

For now, deployment table is sufficient and simple.

### Multi-Region Aurora

If pullDB expands to multi-region Aurora clusters, consider:
- Region-aware deployment tracking
- Procedure replication verification
- Failover procedure re-deployment

---

**Last Updated**: January 2025 by Charles Handshy  
**Related Issues**: Job 380a026a silent failure investigation
