# MySQL User Separation Design

> **Status**: Implemented
> **Created**: 2025-11-26
> **Author**: AI Assistant

## Overview

Separate MySQL users for each pullDB service component to implement least-privilege access control.

## New Naming Conventions

| Component | Current | New |
|-----------|---------|-----|
| Database | `pulldb` | `pulldb_service` |
| API MySQL user | `pulldb` | `pulldb_api` |
| Worker MySQL user | `pulldb` | `pulldb_worker` |
| Loader MySQL user | N/A | `pulldb_loader` |
| System user | `pulldb_service` | `pulldb_service` (unchanged) |

## Service Descriptions

### API Service (`pulldb_api`)
- Handles HTTP requests from CLI and web interface
- Creates users, submits jobs to queue
- Read-heavy with limited writes to coordination database

### Worker Service (`pulldb_worker`)
- Polls job queue, orchestrates restore workflow
- Updates job status, appends events
- Manages settings and distributed locks
- Connects to coordination database only

### Loader Service (`pulldb_loader`)
- Executes myloader against **target databases** (not coordination DB)
- Needs full database creation/restoration privileges on target hosts
- Used by worker when connecting to restore targets (dev-db-01, etc.)

## MySQL Permission Matrix

### Coordination Database (`pulldb_service`)

#### `pulldb_api` - API Service User

| Table | SELECT | INSERT | UPDATE | DELETE | Notes |
|-------|--------|--------|--------|--------|-------|
| `auth_users` | ✅ | ✅ | ❌ | ❌ | Creates users via `get_or_create_user()` |
| `jobs` | ✅ | ✅ | ❌ | ❌ | Submits jobs via `enqueue_job()` |
| `job_events` | ✅ | ❌ | ❌ | ❌ | Reads job history only |
| `db_hosts` | ✅ | ❌ | ❌ | ❌ | Reads host config for validation |
| `settings` | ✅ | ❌ | ❌ | ❌ | Reads settings for config |
| `locks` | ❌ | ❌ | ❌ | ❌ | Not used by API |
| `active_jobs` (view) | ✅ | N/A | N/A | N/A | Read-only view |

```sql
-- API Service User Grants
GRANT SELECT, INSERT ON pulldb_service.auth_users TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.jobs TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.job_events TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.db_hosts TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.settings TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.active_jobs TO 'pulldb_api'@'localhost';
```

#### `pulldb_worker` - Worker Service User

| Table | SELECT | INSERT | UPDATE | DELETE | Notes |
|-------|--------|--------|--------|--------|-------|
| `auth_users` | ✅ | ❌ | ❌ | ❌ | Reads only (user created by API) |
| `jobs` | ✅ | ❌ | ✅ | ❌ | Updates status (`mark_job_*`) |
| `job_events` | ✅ | ✅ | ❌ | ❌ | Appends events |
| `db_hosts` | ✅ | ❌ | ❌ | ❌ | Reads host config |
| `settings` | ✅ | ✅ | ✅ | ✅ | Full access via CLI |
| `locks` | ✅ | ✅ | ✅ | ✅ | Distributed locking |
| `active_jobs` (view) | ✅ | N/A | N/A | N/A | Read-only view |

```sql
-- Worker Service User Grants
GRANT SELECT ON pulldb_service.auth_users TO 'pulldb_worker'@'localhost';
GRANT SELECT, UPDATE ON pulldb_service.jobs TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.job_events TO 'pulldb_worker'@'localhost';
GRANT SELECT ON pulldb_service.db_hosts TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.settings TO 'pulldb_worker'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.locks TO 'pulldb_worker'@'localhost';
GRANT SELECT ON pulldb_service.active_jobs TO 'pulldb_worker'@'localhost';
```

### Target Databases (dev-db-01, etc.)

#### `pulldb_loader` - Loader/Restore User

This user exists on **target database hosts**, not the coordination database.
Used by myloader to restore backups.

| Permission | Scope | Notes |
|------------|-------|-------|
| `CREATE` | `*.*` | Create restored databases |
| `DROP` | `*.*` | Drop staging databases, overwrite tables |
| `ALTER` | `*.*` | Modify table structures during restore |
| `INDEX` | `*.*` | Create indexes |
| `INSERT` | `*.*` | Insert restored data |
| `UPDATE` | `*.*` | Update data (triggers, post-SQL) |
| `DELETE` | `*.*` | Delete data (post-SQL sanitization) |
| `SELECT` | `*.*` | Read data for verification |
| `LOCK TABLES` | `*.*` | Required by myloader |
| `TRIGGER` | `*.*` | Restore triggers |
| `CREATE VIEW` | `*.*` | Restore views |
| `CREATE ROUTINE` | `*.*` | Restore procedures/functions |
| `ALTER ROUTINE` | `*.*` | Modify procedures |
| `REFERENCES` | `*.*` | Foreign key management |
| `EVENT` | `*.*` | Restore events (if any) |

```sql
-- Loader User Grants (on TARGET database hosts)
-- This is a privileged user for restore operations
GRANT CREATE, DROP, ALTER, INDEX, INSERT, UPDATE, DELETE, SELECT,
      LOCK TABLES, TRIGGER, CREATE VIEW, CREATE ROUTINE, ALTER ROUTINE,
      REFERENCES, EVENT
ON *.* TO 'pulldb_loader'@'%';

-- Alternative: Restrict to specific database patterns
-- GRANT ... ON `______%`.* TO 'pulldb_loader'@'%';  -- user_code prefixed DBs
-- GRANT ... ON `qatemplate`.* TO 'pulldb_loader'@'%';
```

## AWS Secrets Manager Structure

### Option A: Separate Secrets Per Service (Recommended)

```
/pulldb/mysql/api-coordination
  └── { "host": "localhost", "password": "..." }

/pulldb/mysql/worker-coordination  
  └── { "host": "localhost", "password": "..." }

/pulldb/mysql/dev-db-01           (existing, for loader)
  └── { "host": "dev-db-01.example.com", "password": "..." }
```

### Option B: Single Coordination Secret + Env Override

```
/pulldb/mysql/coordination-db
  └── { "host": "localhost", "password": "..." }

# .env overrides username per service
PULLDB_API_MYSQL_USER=pulldb_api
PULLDB_WORKER_MYSQL_USER=pulldb_worker
```

**Note**: The loader credentials are already handled separately via `db_hosts.credential_ref`.

## Environment Variables

### Current Structure
```bash
PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db
PULLDB_MYSQL_USER=pulldb
PULLDB_MYSQL_DATABASE=pulldb
```

### New Structure
```bash
# Common coordination database settings
PULLDB_MYSQL_DATABASE=pulldb_service
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_PORT=3306

# API Service (used by pulldb-api.service)
PULLDB_API_MYSQL_USER=pulldb_api
PULLDB_API_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/api-coordination

# Worker Service (used by pulldb-worker.service)  
PULLDB_WORKER_MYSQL_USER=pulldb_worker
PULLDB_WORKER_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/worker-coordination

# Loader credentials are stored in db_hosts table, not .env
# Each target host has its own credential_ref pointing to Secrets Manager
```

## Files Requiring Changes

### Phase 1: Schema & Documentation
- [x] Rename `schema/pulldb/` → `schema/pulldb_service/`
- [x] Create `schema/pulldb_service/300_mysql_users.sql`
- [x] Update `docs/mysql-schema.md`
- [ ] Update `docs/AWS-SETUP.md`

### Phase 2: Configuration
- [x] Update `packaging/env.example`
- [x] Update `scripts/configure-pulldb.sh`
- [x] Update systemd unit files if needed

### Phase 3: Code Changes
- [x] `pulldb/api/main.py` - Read `PULLDB_API_MYSQL_USER` (required)
- [x] `pulldb/worker/service.py` - Read `PULLDB_WORKER_MYSQL_USER` (required)
- [x] Remove `PULLDB_MYSQL_USER` fallback - service-specific users required
- [x] Update `pulldb/infra/secrets.py` - Remove username requirement from resolver

### Phase 4: AWS Secrets
- [x] Create `/pulldb/mysql/api` secret
- [x] Create `/pulldb/mysql/worker` secret
- [x] Create `/pulldb/mysql/loader` secret

## db_hosts Table & Loader Credentials

The loader credentials are already managed separately via the `db_hosts` table:

```sql
-- Example db_hosts entries
INSERT INTO db_hosts (hostname, credential_ref, ...) VALUES
  ('localhost', 'aws-secretsmanager:/pulldb/mysql/localhost-loader', ...),
  ('dev-db-01', 'aws-secretsmanager:/pulldb/mysql/dev-db-01', ...);
```

Each target host has its own secret containing the `pulldb_loader` password for that host.
The worker service resolves these credentials when executing restores.

## Migration Path

### For Existing Installations

```bash
# 1. Create new database
mysql -e "CREATE DATABASE pulldb_service;"

# 2. Copy existing data
mysqldump pulldb | mysql pulldb_service

# 3. Create new users
mysql < schema/pulldb_service/300_mysql_users.sql

# 4. Create secrets in AWS Secrets Manager
aws secretsmanager create-secret \
  --name /pulldb/mysql/api-coordination \
  --secret-string '{"host":"localhost","password":"API_PASSWORD"}'

aws secretsmanager create-secret \
  --name /pulldb/mysql/worker-coordination \
  --secret-string '{"host":"localhost","password":"WORKER_PASSWORD"}'

# 5. Update .env
sed -i 's/PULLDB_MYSQL_DATABASE=pulldb/PULLDB_MYSQL_DATABASE=pulldb_service/' /opt/pulldb.service/.env
# Add new user variables...

# 6. Restart services
systemctl restart pulldb-api pulldb-worker

# 7. Verify, then optionally drop old database
mysql -e "DROP DATABASE pulldb;"
```

## Security Benefits

1. **Least Privilege**: Each service only has permissions it needs
2. **Audit Trail**: Easier to track which service performed which operations
3. **Blast Radius**: Compromised API credentials can't modify job status
4. **Separation of Concerns**: Loader has different trust level than coordination access

## Implementation Decisions

1. **Option B (single secret + env override for user)** - Simpler, allows sharing password if desired
2. **No backward compatibility** - `PULLDB_MYSQL_USER` removed; service-specific users are required
3. **AWS Secrets created**: `/pulldb/mysql/api`, `/pulldb/mysql/worker`, `/pulldb/mysql/loader`
4. Loader user on target hosts - manual setup per host via `db_hosts.credential_ref`

## References

- `docs/mysql-schema.md` - Current schema documentation
- `design/two-service-architecture.md` - Service architecture
- `docs/AWS-SETUP.md` - AWS configuration
- `pulldb/infra/mysql.py` - Repository implementations
