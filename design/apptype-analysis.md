# appType Analysis and Design Mapping

## Legacy `pullDB-auth` appType Behavior

### What is appType?

In the legacy `pullDB-auth` PHP implementation, `appType` is a CLI parameter (`--type=<TYPE>`) that determines which MySQL development database server to restore databases to. It acts as a **database host selector** based on team/department affiliation.

### Supported appType Values

```php
public static function getHostByAppType($appType="dev"){
    switch($appType){
        case "DEV":
            $host = "legacy-dev-host.example.com";
            break;
            
        case "SUPPORT":
            $host = "legacy-support-host.example.com";
            break;
            
        case "IMPLEMENTATION":
            $host = "legacy-impl-host.example.com";
            break;
            
        default:
            $host = "legacy-support-host.example.com"; // SUPPORT
    }
    return $host;
}
```

### Purpose

- **DEV**: Development team's dedicated database server (db3)
- **SUPPORT**: Support team's dedicated database server (db4 - default)
- **IMPLEMENTATION**: Implementation team's dedicated database server (db5)

This segregation provides:
1. **Resource isolation**: Each team has dedicated database capacity
2. **Namespace separation**: Prevents database name conflicts between teams
3. **Performance isolation**: Heavy restores by one team don't impact others

### Usage in Legacy Tool

```bash
# Support team (default)
pullDB --db=customerdb --user=jsmith --localDb=jsmithcustomerdev

# Development team
pullDB --db=customerdb --user=jsmith --localDb=jsmithcustomerdev --type=DEV

# Implementation team
pullDB --db=customerdb --user=jsmith --localDb=jsmithcustomerdev --type=IMPLEMENTATION
```

## New pullDB Design Mapping

### Direct Equivalent: `dbhost=` Parameter

The new pullDB design **fully supports** this functionality through the **`dbhost=` CLI parameter**:

```bash
# Support team (using configured default)
pullDB user=jsmith customer=customerdb

# Development team (explicit override)
pullDB user=jsmith customer=customerdb dbhost=legacy-dev-host

# Implementation team (explicit override)
pullDB user=jsmith customer=customerdb dbhost=legacy-impl-host
```

### Architecture Implementation

#### 1. MySQL `db_hosts` Table

Pre-register all database servers with their credentials and capacity limits:

```sql
CREATE TABLE db_hosts (
    dbhost VARCHAR(255) PRIMARY KEY,
    credential_ref TEXT NOT NULL,
    max_db_count INT UNSIGNED NOT NULL DEFAULT 1000,
    last_known_db_count INT UNSIGNED DEFAULT 0,
    disabled_at TIMESTAMP(6)
);

-- Example registrations
INSERT INTO db_hosts (dbhost, credential_ref, max_db_count) VALUES
    ('localhost', 
     'ssm:///pulldb/db-local-dev/creds', 1000),
    ('legacy-dev-host.example.com', 
     'ssm:///pulldb/legacy-dev-host/creds', 1000),
    ('legacy-support-host.example.com', 
     'ssm:///pulldb/legacy-support-host/creds', 1000),
    ('legacy-impl-host.example.com', 
     'ssm:///pulldb/legacy-impl-host/creds', 1000);
```

#### 2. Default Host Configuration

Set default in `settings` table to the new local sandbox host while keeping legacy SUPPORT available via explicit override:

```sql
INSERT INTO settings (`key`, `value`) VALUES
    ('default_dbhost', 'localhost');
```

#### 3. CLI Validation

```python
# CLI validates dbhost parameter
def validate_dbhost(dbhost: str) -> str:
    """Verify dbhost is registered in coordination database."""
    cursor.execute("SELECT dbhost FROM db_hosts WHERE dbhost = %s AND disabled_at IS NULL", (dbhost,))
    if not cursor.fetchone():
        raise ValidationException(f"Unknown or disabled dbhost: {dbhost}")
    return dbhost

# If not provided, use default from settings
if not dbhost:
    cursor.execute("SELECT value FROM settings WHERE key = 'default_dbhost'")
    dbhost = cursor.fetchone()['value']
```

#### 4. Job Tracking

The `jobs` table includes `dbhost` to track which server hosts each restore:

```sql
CREATE TABLE jobs (
    job_id CHAR(36) PRIMARY KEY,
    target VARCHAR(128) NOT NULL,
    dbhost VARCHAR(255) NOT NULL,
    -- ... other columns
    FOREIGN KEY (dbhost) REFERENCES db_hosts(dbhost)
);
```

### Benefits Over Legacy Approach

1. **Dynamic Registration**: Add/remove hosts without code changes
2. **Capacity Tracking**: `max_db_count` prevents over-allocation
3. **Credential Management**: Centralized via `credential_ref` (AWS Secrets Manager/SSM)
4. **Audit Trail**: Every job records which host was used
5. **Graceful Degradation**: Can disable hosts temporarily without removing configuration
6. **Explicit Over Implicit**: `dbhost=` is clearer than `--type=SUPPORT`

### Migration Path

For users accustomed to `--type=`, you could optionally add CLI aliases:

```python
# Optional convenience mapping (not in prototype)
APP_TYPE_ALIASES = {
    'DEV': 'legacy-dev-host.example.com',
    'SUPPORT': 'legacy-support-host.example.com',
    'IMPLEMENTATION': 'legacy-impl-host.example.com',
}

# In CLI parsing
if 'type' in options:
    if options['type'] in APP_TYPE_ALIASES:
        options['dbhost'] = APP_TYPE_ALIASES[options['type']]
    else:
        raise ValidationException(f"Unknown type: {options['type']}")
```

However, **the prototype should use `dbhost=` directly** for clarity and to avoid maintaining legacy syntax.

## Design Documentation Status

✅ **Fully Supported** - The new pullDB design addresses appType functionality through:

- `dbhost=` CLI parameter (README.md § CLI Options)
- `db_hosts` table registration (docs/mysql-schema.md)
- `default_dbhost` setting (design/configuration-map.md)
- Host validation in CLI (design/system-overview.md)
- Capacity checking in daemon (design/system-overview.md)

## Recommendations

1. **Pre-populate `db_hosts`** table during deployment with all three existing hosts
2. **Set `default_dbhost`** to db4 (SUPPORT) to match legacy default behavior
3. **Document migration** in deployment notes: "Legacy `--type=SUPPORT` becomes `dbhost=legacy-support-host`"
4. **Consider short aliases** in future (Phase 2+): `dbhost=dev-db-01` instead of full hostname
5. **Monitor capacity** via `last_known_db_count` to prevent resource exhaustion

## Conclusion

The new pullDB design **completely supports** the legacy appType functionality through the more flexible `dbhost=` parameter pattern. The database-driven host registration approach provides better operational control, audit trails, and capacity management compared to the hardcoded switch statement in the legacy implementation.
