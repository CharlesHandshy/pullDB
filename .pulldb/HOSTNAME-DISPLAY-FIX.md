# Hostname Display Enhancement

**Date**: 2026-01-08  
**Issue**: CLI shows db_hosts.hostname instead of actual database endpoint from credentials

## Problem

The `pulldb hosts` command was displaying the `db_hosts.hostname` field directly, which could be:
- The actual endpoint (desired)
- A short alias value (confusing)
- Different from the actual connection target in AWS Secrets Manager

Example confusion:
```bash
$ pulldb hosts
ALIAS            HOSTNAME
aurora-test *    aurora-test    # ← Same value in both columns!
```

Users need to see the **actual database endpoint** to understand where restores will occur.

## Solution

### 1. Fix Database Records
Ensure `hostname` contains the full endpoint and `host_alias` contains the short name:

```bash
chmod +x scripts/apply_hostname_fix.sh
./scripts/apply_hostname_fix.sh
```

This updates:
```sql
-- Before
hostname: aurora-test
host_alias: NULL

-- After  
hostname: db-mysql-db4-clone-pulldb-test-cluster.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com
host_alias: aurora-test
```

### 2. Enhanced API Endpoint
Updated `/api/hosts` to resolve the actual database endpoint from AWS Secrets Manager credentials:

```python
# For each host, resolve credentials and show the real endpoint
creds = state.host_repo.get_host_credentials(h.hostname)
display_hostname = creds.host  # Actual endpoint from secret
```

This ensures users always see the **real connection target**, even if the database hostname field is inconsistent.

### 3. Backward Compatibility
The `resolve_hostname()` function allows users to reference hosts by either:
- **Alias**: `dbhost=aurora-test` (short, friendly)
- **Full hostname**: `dbhost=db-mysql-db4-clone-pulldb-test-cluster...` (explicit)

Existing jobs with `dbhost='aurora-test'` continue working because `resolve_hostname()` checks both fields.

## After the Fix

```bash
$ pulldb hosts

Available Database Hosts
==================================================
ALIAS            HOSTNAME
---------------- --------------------------------
aurora-test *    db-mysql-db4-clone-pulldb-test-cluster.cluster-c68atgvskclk.us-east-1.rds.amazonaws.com
---------------- --------------------------------

Use alias or hostname with: pulldb restore <customer> dbhost=<alias>
```

Now users see:
- **ALIAS**: Short friendly name (`aurora-test`)
- **HOSTNAME**: Actual RDS endpoint for restore target

## Benefits

1. ✅ **Clarity**: Users know exactly where their restore will occur
2. ✅ **Accuracy**: Display matches actual connection target from AWS
3. ✅ **Flexibility**: Users can use short alias or full hostname
4. ✅ **No Breaking Changes**: Existing references continue to work via `resolve_hostname()`

## Implementation Files

- [scripts/apply_hostname_fix.sh](../scripts/apply_hostname_fix.sh) - Database fix script
- [pulldb/api/main.py](../pulldb/api/main.py#L847-L896) - Enhanced API endpoint
- [pulldb/infra/mysql_hosts.py](../pulldb/infra/mysql_hosts.py) - resolve_hostname() function (HostRepository)
