# Schema Migration Guide

pullDB uses **dbmate** for database schema migrations, providing reliable, version-tracked schema changes with rollback capability.

## Overview

### Why dbmate?

- **Zero dependencies**: Single Go binary, no runtime required
- **Plain SQL**: Migrations are standard SQL files, easy to review
- **Atomic**: Each migration runs in a transaction
- **Bidirectional**: Every `up` has a corresponding `down`
- **Idempotent**: Safe to run multiple times

### Migration File Format

```sql
-- migrate:up
CREATE TABLE example (...);

-- migrate:down
DROP TABLE example;
```

Files are named with timestamps: `YYYYMMDDHHMMSS_description.sql`

## Quick Start

### Check Migration Status

```bash
pulldb-migrate status
```

Shows which migrations are applied vs pending.

### Apply Migrations

```bash
# Interactive (prompts for confirmation)
pulldb-migrate up

# Non-interactive (for automation/upgrades)
pulldb-migrate up --yes
```

### Rollback Last Migration

```bash
pulldb-migrate rollback
```

### Create New Migration

```bash
pulldb-migrate new add_new_feature
# Creates: migrations/20250128123456_add_new_feature.sql
```

## Migration History

| Migration | Description | Version |
|-----------|-------------|---------|
| `20250101000000_initial_schema.sql` | Core tables: auth_users, jobs, job_events, db_hosts, locks, settings | v0.0.1 |
| `20250115000000_add_cancel_requested.sql` | Job cancellation support | v0.0.2 |
| `20250116000000_add_staging_cleaned.sql` | Staging cleanup tracking | v0.0.3 |
| `20250120000000_seed_hosts.sql` | Default localhost entry | v0.0.1 |
| `20250121000000_seed_settings.sql` | Initial settings | v0.0.1 |
| `20250128000000_phase2_concurrency.sql` | Per-user and global job caps | v0.0.4 |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PULLDB_INSTALL_PREFIX` | `/opt/pulldb.service` | Installation directory |
| `PULLDB_MIGRATIONS_DIR` | `$INSTALL_PREFIX/migrations` | Migrations location |
| `PULLDB_COORDINATION_SECRET` | `aws-secretsmanager:/pulldb/mysql/coordination-db` | DB credentials secret |
| `PULLDB_AWS_PROFILE` | (none) | AWS CLI profile |
| `PULLDB_MYSQL_DATABASE` | `pulldb_service` | Database name |
| `PULLDB_MIGRATION_MYSQL_USER` | `root` | MySQL user for migrations |
| `DATABASE_URL` | (constructed) | Override: `mysql://user:pass@host:port/db` |

### Credential Resolution

The migration tool loads credentials in this order:

1. **`DATABASE_URL`** environment variable (if set)
2. **AWS Secrets Manager** via `PULLDB_COORDINATION_SECRET`

For AWS Secrets Manager, the secret must contain:
```json
{
  "host": "db-host.example.com",
  "port": 3306,
  "password": "secret-password"
}
```

## Writing Migrations

### Best Practices

1. **One change per migration**: Easier to rollback and understand
2. **Always write the down**: Future you will thank you
3. **Use `IF NOT EXISTS`/`IF EXISTS`**: Make migrations idempotent where possible
4. **Test rollbacks locally**: Run `up`, then `down`, then `up` again
5. **Add comments**: Explain *why*, not just *what*

### Example: Adding a Column

```sql
-- migrate:up
-- =============================================================================
-- Add priority column for job scheduling
-- Default to 'normal' for backward compatibility
-- =============================================================================

ALTER TABLE jobs 
ADD COLUMN priority ENUM('low', 'normal', 'high') DEFAULT 'normal' 
AFTER target_db;

CREATE INDEX idx_jobs_priority ON jobs(priority, status, created_at);

-- migrate:down
DROP INDEX idx_jobs_priority ON jobs;
ALTER TABLE jobs DROP COLUMN priority;
```

### Example: Adding a Setting

```sql
-- migrate:up
INSERT IGNORE INTO settings (setting_key, setting_value, description)
VALUES ('new_setting', 'default_value', 'Description of setting');

-- migrate:down
DELETE FROM settings WHERE setting_key = 'new_setting';
```

## Upgrade Workflow

### Production Upgrade

```bash
# 1. Stop services (optional but recommended for major changes)
sudo systemctl stop pulldb-worker

# 2. Apply migrations
sudo pulldb-migrate up --yes

# 3. Verify schema
sudo pulldb-migrate verify

# 4. Restart services
sudo systemctl start pulldb-worker
```

### Zero-Downtime Migrations

For changes that don't break running code:

```bash
# Apply while services are running
sudo pulldb-migrate up --yes

# Restart services to pick up changes
sudo systemctl restart pulldb-worker pulldb-api
```

## Troubleshooting

### Migration Fails Midway

Migrations run in transactions. If a migration fails:
1. The transaction is rolled back
2. The `schema_migrations` table is NOT updated
3. Fix the issue and re-run `pulldb-migrate up`

### Checking Applied Migrations

```sql
SELECT * FROM schema_migrations ORDER BY version;
```

### Manual Recovery

If you need to mark a migration as applied without running it:

```sql
-- DANGER: Only do this if you're certain the schema is correct
INSERT INTO schema_migrations (version) VALUES ('20250128000000');
```

### Version Mismatch

If `pulldb-migrate verify` fails:
1. Check `pulldb-migrate status` for pending migrations
2. Review the migration files in `/opt/pulldb.service/migrations/`
3. Apply any missing migrations with `pulldb-migrate up`

## Development

### Local Testing

```bash
# Set up local DATABASE_URL
export DATABASE_URL="mysql://root:password@localhost:3306/pulldb_test"

# Run migrations
./scripts/pulldb-migrate.sh up

# Test rollback
./scripts/pulldb-migrate.sh rollback

# Re-apply
./scripts/pulldb-migrate.sh up
```

### Creating Schema Changes

1. Create migration: `pulldb-migrate new descriptive_name`
2. Edit the generated file in `migrations/`
3. Test locally: `pulldb-migrate up`, then `down`, then `up`
4. Commit with related code changes
5. Update `CHANGELOG.md` and version

## Schema Tracking Table

dbmate creates and manages `schema_migrations`:

```sql
CREATE TABLE schema_migrations (
    version VARCHAR(128) PRIMARY KEY
);
```

This table tracks which migrations have been applied. Never modify it manually unless recovering from a failure.
