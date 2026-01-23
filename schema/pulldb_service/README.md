# pullDB Database Schema

**Clean CREATE TABLE scripts for new installations.**

No ALTER statements - all columns and indexes are included in the base table definitions.

## Directory Structure

```
schema/pulldb_service/
├── 00_tables/          # CREATE TABLE statements (run in order)
│   ├── 001_auth_users.sql
│   ├── 002_auth_credentials.sql
│   ├── 003_sessions.sql
│   ├── 004_api_keys.sql
│   ├── 010_db_hosts.sql
│   ├── 011_user_hosts.sql
│   ├── 020_jobs.sql
│   ├── 021_job_events.sql
│   ├── 022_job_history_summary.sql
│   ├── 030_locks.sql
│   ├── 031_settings.sql
│   ├── 040_admin_tasks.sql
│   ├── 041_audit_logs.sql
│   ├── 042_procedure_deployments.sql
│   ├── 050_disallowed_users.sql
│   ├── 060_feature_requests.sql
│   └── 099_schema_migrations.sql
├── 01_views/           # CREATE VIEW statements
│   └── 001_active_jobs_view.sql
├── 02_seed/            # Initial data (INSERT statements)
│   ├── 001_seed_db_hosts.sql
│   ├── 002_seed_admin_account.sql
│   ├── 003_seed_service_account.sql
│   ├── 004_seed_settings.sql
│   └── 005_seed_disallowed_users.sql
└── 03_users/           # MySQL user grants
    └── 001_mysql_users.sql
```

## New Installation Steps

1. **Create the database:**
   ```sql
   CREATE DATABASE pulldb_service CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   USE pulldb_service;
   ```

2. **Run scripts in order:**
   ```bash
   # Tables
   for f in schema/pulldb_service/00_tables/*.sql; do
     mysql -u root -p pulldb_service < "$f"
   done
   
   # Views
   for f in schema/pulldb_service/01_views/*.sql; do
     mysql -u root -p pulldb_service < "$f"
   done
   
   # Seed data
   for f in schema/pulldb_service/02_seed/*.sql; do
     mysql -u root -p pulldb_service < "$f"
   done
   
   # MySQL users (edit passwords first!)
   # IMPORTANT: Edit 001_mysql_users.sql to set real passwords
   mysql -u root -p < schema/pulldb_service/03_users/001_mysql_users.sql
   ```

## Numbering Convention

- `00x` - Authentication & user management
- `01x` - Database host configuration
- `02x` - Jobs and job events (core workflow)
- `03x` - System state (locks, settings)
- `04x` - Administrative (tasks, audit, deployments)
- `05x` - Access control (disallowed users)
- `06x` - Feature requests
- `09x` - Infrastructure (schema_migrations)

## Key Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `auth_users` | User accounts | role ENUM, manager_id, locked_at |
| `jobs` | Restore job queue | status ENUM (11 states), all retention columns |
| `job_history_summary` | Historical job metrics | isolated, no FK, manual retention |
| `api_keys` | CLI authentication | approval workflow, host tracking |
| `admin_tasks` | Background tasks | task_type ENUM (4 types) |
| `feature_requests` | User feedback | status ENUM, voting, notes |

## Schema Upgrades

**Note:** Schema upgrades are not supported automatically. For schema changes
on existing installations, manual migration is required.

New installations should always use these clean CREATE TABLE scripts.
