# pulldb-migrate Reference

> **Version**: 0.0.4 | **Last Updated**: November 28, 2025

The `pulldb-migrate` tool manages database schema migrations for the pullDB coordination database using [dbmate](https://github.com/amacneil/dbmate).

---

## Quick Start

```bash
# Check migration status
sudo pulldb-migrate status

# Apply pending migrations
sudo pulldb-migrate up

# Verify schema integrity
sudo pulldb-migrate verify

# Rollback last migration
sudo pulldb-migrate rollback
```

---

## Location

```bash
/opt/pulldb.service/scripts/pulldb-migrate.sh
```

Migrations are stored in:
```bash
/opt/pulldb.service/migrations/
```

---

## Commands

### status

Shows which migrations have been applied and which are pending.

**Syntax:**
```bash
sudo pulldb-migrate status
```

**Output:**
```
[INFO] Checking migration status...
[X] 20250101000000_initial_schema.sql
[X] 20250115000000_add_cancel_requested.sql
[X] 20250116000000_add_staging_cleaned.sql
[X] 20250120000000_seed_hosts.sql
[X] 20250121000000_seed_settings.sql
[X] 20250128000000_phase2_concurrency.sql
[X] 20251128051147_repair_missing_columns.sql

Applied: 7
Pending: 0
```

**Legend:**
- `[X]` = Applied
- `[ ]` = Pending

---

### up

Applies all pending migrations.

**Syntax:**
```bash
# Interactive (prompts for confirmation)
sudo pulldb-migrate up

# Non-interactive (for scripts/automation)
sudo pulldb-migrate up --yes
```

**Output:**
```
[INFO] Checking for pending migrations...
[ ] 20251201000000_add_new_feature.sql

Applied: 7
Pending: 1

Apply 1 migration(s)? [y/N]: y
[INFO] Applying migrations...
Applying: 20251201000000_add_new_feature.sql
Applied: 20251201000000_add_new_feature.sql in 125.5ms
[INFO] Migrations applied successfully
```

---

### rollback

Rolls back the last applied migration.

**Syntax:**
```bash
sudo pulldb-migrate rollback
```

**Output:**
```
[INFO] Rolling back last migration...
Rolling back: 20251201000000_add_new_feature.sql
Rolled back: 20251201000000_add_new_feature.sql in 45.2ms
[INFO] Rollback complete
```

**Warning:** Rollbacks may cause data loss. Always backup before rolling back.

---

### verify

Validates that the schema is correct and all expected tables exist.

**Syntax:**
```bash
sudo pulldb-migrate verify
```

**Output (success):**
```
[INFO] Verifying schema...
[INFO] Schema verification passed
[INFO]   - All required tables present
[INFO]   - Applied migrations: 7
[INFO]   - Phase 2 settings: OK
```

**Output (failure):**
```
[ERROR] Schema verification failed
[ERROR]   - Missing table: settings
[ERROR]   - Run: sudo pulldb-migrate up
```

---

### new

Creates a new migration file.

**Syntax:**
```bash
sudo pulldb-migrate new <migration_name>
```

**Examples:**
```bash
sudo pulldb-migrate new add_user_roles
sudo pulldb-migrate new add_job_priority_column
```

**Output:**
```
[INFO] Created new migration:
  /opt/pulldb.service/migrations/20251128120000_add_user_roles.sql

Edit the file and add your SQL changes.
```

**Migration File Template:**
```sql
-- migrate:up
-- Add your forward migration SQL here


-- migrate:down
-- Add your rollback SQL here

```

---

### baseline

Marks all migrations as applied without running them. Used when installing on an existing database.

**Syntax:**
```bash
sudo pulldb-migrate baseline
```

**Output:**
```
[INFO] Baseline: marking existing migrations as applied...
[DEBUG] Recording: 20250101000000_initial_schema.sql
[DEBUG] Recording: 20250115000000_add_cancel_requested.sql
[DEBUG] Already recorded: 20250116000000_add_staging_cleaned.sql
...
[INFO] Baseline complete: 4 migrations recorded
```

**When to Use:**
- Installing pullDB on a database that was set up manually
- After restoring from a backup that didn't include `schema_migrations` table
- Converting from non-migration-managed schema

---

### wait

Waits for the database to become available. Useful in startup scripts.

**Syntax:**
```bash
sudo pulldb-migrate wait [--timeout=N]
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--timeout=` | 60 | Seconds to wait before failing |

**Output:**
```
[INFO] Waiting for database...
[INFO] Database is ready
```

---

## Authentication

The migration tool uses different authentication methods based on context:

### Localhost (Socket Auth)

When running on localhost, the tool uses **Unix socket authentication**:

```bash
# Uses socket auth automatically (no password needed)
sudo pulldb-migrate status
```

**How it works:**
1. Detects localhost connection
2. Finds MySQL socket at `/var/run/mysqld/mysqld.sock`
3. Connects as `root` user via socket (auth_socket plugin)

### Remote Hosts (AWS Secrets Manager)

For remote connections, credentials come from AWS Secrets Manager:

```bash
# Set environment variable
export PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db

sudo pulldb-migrate status
```

### Manual Override

You can override authentication with `DATABASE_URL`:

```bash
export DATABASE_URL="mysql://user:password@host:3306/pulldb_service"
sudo pulldb-migrate status
```

---

## Migration File Format

Migrations use dbmate's format:

```sql
-- migrate:up
-- =============================================================================
-- Description of what this migration does
-- =============================================================================

CREATE TABLE new_table (
    id CHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL
);


-- migrate:down
-- =============================================================================
-- Rollback: Description of rollback
-- =============================================================================

DROP TABLE new_table;
```

### Best Practices

1. **Always include `migrate:down`** - Enable rollbacks
2. **One logical change per migration** - Easier to rollback
3. **Use descriptive names** - `add_user_roles` not `update1`
4. **Test rollbacks** - Ensure they work before deploying
5. **Never modify applied migrations** - Create new ones instead

---

## Current Migrations

| Migration | Description |
|-----------|-------------|
| `20250101000000_initial_schema.sql` | Core tables (jobs, auth_users, etc.) |
| `20250115000000_add_cancel_requested.sql` | Phase 1: Cancellation support |
| `20250116000000_add_staging_cleaned.sql` | Phase 1: Cleanup tracking |
| `20250120000000_seed_hosts.sql` | Seed db_hosts table |
| `20250121000000_seed_settings.sql` | Seed settings table |
| `20250128000000_phase2_concurrency.sql` | Phase 2: Concurrency limits |
| `20251128051147_repair_missing_columns.sql` | Repair schema drift |

---

## Integration with Upgrades

The upgrade script automatically runs migrations:

```bash
sudo /opt/pulldb.service/scripts/upgrade_pulldb.sh
```

This:
1. Stops worker service
2. Runs `pulldb-migrate up --yes`
3. Updates Python packages
4. Restarts worker service

### Manual Upgrade

```bash
# Stop services
sudo systemctl stop pulldb-worker.service

# Apply migrations
sudo pulldb-migrate up --yes

# Verify
sudo pulldb-migrate verify

# Restart services
sudo systemctl start pulldb-worker.service
```

---

## Troubleshooting

### "Database not found"

```bash
# Check MySQL is running
sudo systemctl status mysql

# Verify database exists
sudo mysql -e "SHOW DATABASES LIKE 'pulldb_service'"

# Create if missing (run initial setup)
sudo /opt/pulldb.service/scripts/install_pulldb.sh
```

### "Permission denied"

```bash
# Must run as root for socket auth
sudo pulldb-migrate status

# Or set DATABASE_URL with credentials
export DATABASE_URL="mysql://pulldb_migrate:password@localhost/pulldb_service"
pulldb-migrate status
```

### "Migration failed"

```bash
# Check the error message
sudo pulldb-migrate up

# View migration file
cat /opt/pulldb.service/migrations/<migration>.sql

# Check database state
sudo mysql -e "SELECT * FROM pulldb_service.schema_migrations"

# If partially applied, you may need to fix manually
sudo mysql pulldb_service
```

### "Schema drift detected"

When the database schema doesn't match migrations:

```bash
# Check what's different
sudo pulldb-migrate verify

# If migrations were baselined incorrectly, repair:
# 1. Create repair migration
sudo pulldb-migrate new repair_schema

# 2. Add idempotent fixes (IF NOT EXISTS, etc.)
# 3. Apply
sudo pulldb-migrate up
```

---

## Verbose Mode

For debugging, use `--verbose`:

```bash
sudo pulldb-migrate --verbose status
sudo pulldb-migrate --verbose up
```

**Output:**
```
[DEBUG] Found MySQL socket at: /var/run/mysqld/mysqld.sock
[DEBUG] Using Unix socket authentication at: /var/run/mysqld/mysqld.sock (user: root)
[INFO] Checking migration status...
...
```
