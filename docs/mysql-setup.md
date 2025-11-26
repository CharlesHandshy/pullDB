# MySQL Setup and Installation

This document describes the MySQL 8.x installation and configuration for pullDB.

## Quick Start

```bash
# 1. Install and configure MySQL 8.x
sudo scripts/setup-mysql.sh

# 2. Create pulldb coordination database
cat schema/pulldb/*.sql | mysql -u root -p

# 3. Install Python MySQL libraries (in venv)
source venv/bin/activate
pip install mysql-connector-python pymysql
```

## MySQL Configuration

### Data Directory Structure

pullDB uses a custom data directory structure on `/mnt/data` to separate working data from temporary files:

```
/mnt/data/mysql/
├── data/       - Main MySQL data directory
│   ├── Database files (ibdata1, undo logs)
│   ├── System databases (mysql, performance_schema, sys)
│   ├── InnoDB redo logs (#innodb_redo/)
│   └── Binary logs (binlog.*)
└── tmpdir/     - Temporary files directory
```

### Configuration Details

**File**: `/etc/mysql/mysql.conf.d/mysqld.cnf`

```ini
# Data and temporary directories on /mnt/data
datadir         = /mnt/data/mysql/data
tmpdir          = /mnt/data/mysql/tmpdir

# InnoDB settings
innodb_data_home_dir = /mnt/data/mysql/data
innodb_log_group_home_dir = /mnt/data/mysql/data

# Binary log location
log_bin         = /mnt/data/mysql/data/binlog
```

### Why Custom Data Directory?

1. **Performance**: `/mnt/data` is typically on a separate, high-performance volume
2. **Capacity**: Restore operations require significant temporary space
3. **Separation**: Keeps system volume (`/var`) clean and predictable
4. **Backup**: Easier to backup/restore a dedicated data volume

## Installation Scripts

### setup-mysql.sh

Automated MySQL 8.x installation and configuration script.

**Features**:
- Installs MySQL server, client, and development libraries
- Creates custom data directories at `/mnt/data/mysql`
- Migrates existing MySQL data to new location
- Updates MySQL configuration for custom paths
- Configures AppArmor permissions
- Verifies installation and data directory setup

**Usage**:
```bash
sudo scripts/setup-mysql.sh
```

**What it does**:
1. Updates package lists
2. Installs `mysql-server`, `mysql-client`, `libmysqlclient-dev`, `pkg-config`
3. Stops MySQL service
4. Creates `/mnt/data/mysql/data` and `/mnt/data/mysql/tmpdir`
5. Copies existing data from `/var/lib/mysql` to new location
6. Sets ownership (`mysql:mysql`) and permissions (`750`)
7. Updates MySQL configuration in `/etc/mysql/mysql.conf.d/mysqld.cnf`
8. Updates AppArmor permissions in `/etc/apparmor.d/local/usr.sbin.mysqld`
9. Restarts MySQL with new configuration
10. Verifies datadir, tmpdir, and InnoDB paths

**Output**:
- MySQL 8.0.43 installed and running
- Data directory: `/mnt/data/mysql/data/`
- Temp directory: `/mnt/data/mysql/tmpdir`
- Configuration backup: `/etc/mysql/mysql.conf.d/mysqld.cnf.backup`

### Apply schema/pulldb/*.sql

The numbered files under `schema/pulldb/` are the canonical definition of the coordination database. Apply them in lexicographic order to create all tables, views, and seed data.

**Usage**:

```bash
cat schema/pulldb/*.sql | mysql -u root -p
```

**What it provides**:
1. Creates the `pulldb` database (if not present) with UTF-8 encoding
2. Defines all tables (auth_users, jobs, job_events, db_hosts, settings, locks)
3. Establishes indexes, foreign keys, and generated columns (including `active_target_key`)
4. Creates the `active_jobs` view and status-change trigger
5. Seeds default `db_hosts` entries and baseline settings rows

> **Why numbering matters**: Files are prefixed with zero-padded sequence numbers (`000_`, `010_`, ...). MySQL processes them in lexical order when using the `cat schema/pulldb/*.sql` pattern, ensuring dependencies (tables → views → seed data) load correctly.

> **Historical context**: The previous monolithic definition lives at `schema/archived/pulldb.sql` for audit purposes. Do not use it for new environments.

**Historical note**: The earlier `scripts/setup-pulldb-schema.sh` wrapper is now archived under `scripts/archived/` and should not be used for new environments.

## MySQL User Creation

### Create pulldb_app User


After installing MySQL and creating the database, create the `pulldb_app` user for application access and the `pulldb_test` user for integration tests:

```bash
# Connect to MySQL as root
sudo mysql

# Create pulldb_app user with strong password
CREATE USER 'pulldb_app'@'localhost' IDENTIFIED BY 'REPLACE_WITH_STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON pulldb.* TO 'pulldb_app'@'localhost';
GRANT SELECT ON mysql.user TO 'pulldb_app'@'localhost';

# Create pulldb_test user for integration tests
CREATE USER 'pulldb_test'@'localhost' IDENTIFIED BY 'testpass';
GRANT ALL PRIVILEGES ON pulldb.* TO 'pulldb_test'@'localhost';
GRANT SELECT ON mysql.user TO 'pulldb_test'@'localhost';

# Apply privilege changes
FLUSH PRIVILEGES;

# Verify users were created
SELECT user, host FROM mysql.user WHERE user IN ('pulldb_app', 'pulldb_test');

# Exit MySQL
EXIT;
```

**For RDS/Remote Database Servers**:

If connecting to RDS or remote MySQL servers, create users with appropriate host patterns:

```sql
-- For specific host
CREATE USER 'pulldb_app'@'10.0.1.%' IDENTIFIED BY 'STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON *.* TO 'pulldb_app'@'10.0.1.%';

-- Or for any host (less secure, use with caution)
CREATE USER 'pulldb_app'@'%' IDENTIFIED BY 'STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON *.* TO 'pulldb_app'@'%';

FLUSH PRIVILEGES;
```

**Permissions Explained**:
- `ALL PRIVILEGES ON pulldb.*` - Full access to coordination database
- `ALL PRIVILEGES ON *.*` - Full access for target database restores
- `SELECT ON mysql.user` - Optional, for authentication verification queries

**Security Note**: The password used here should match the password stored in AWS Secrets Manager (see `aws-secrets-manager-setup.md`).

### Verify User Connectivity

Test the pulldb_app user can connect:

```bash
# Test local connection
mysql -u pulldb_app -p pulldb

# Test remote connection (if applicable)
mysql -h remote-db-host.example.com \
      -u pulldb_app -p

# Inside MySQL, verify access
SHOW DATABASES;
USE pulldb;
SHOW TABLES;
SELECT * FROM settings;
```

**Expected Output**:
```
+-------------------------+
| Database                |
+-------------------------+
| information_schema      |
| pulldb                  |
+-------------------------+

+----------------+
| Tables_in_pulldb |
+----------------+
| auth_users      |
| db_hosts        |
| job_events      |
| jobs            |
| locks           |
| settings        |
+----------------+
```

## Database Schema
## Database Schema Update Workflow (MANDATORY)

All database structure changes must follow this workflow:

1. Update `docs/mysql-schema.md` to reflect the desired schema changes.
2. Update the numbered files under `schema/pulldb/` and `scripts/setup-tests-dbdata.sh` to match the new schema.
3. Use `sudo` for all database admin tasks (schema changes, migrations, resets) on development databases.
4. Apply changes by running:
   ```bash
   cat schema/pulldb/*.sql | mysql -u root -p
   sudo scripts/setup-tests-dbdata.sh
   ```
5. Verify schema and initial data with:
   ```bash
   sudo mysql -e "USE pulldb; SHOW TABLES;"
   sudo mysql -e "USE pulldb; SELECT * FROM settings;"
   sudo mysql -e "USE pulldb; SELECT * FROM db_hosts;"
   ```
6. Update all documentation and tests to match the new schema and credential patterns.

**MANDATE:**
- Never apply schema changes manually; always use the setup scripts.
- Always use `sudo` for database admin operations in development.
- Keep setup scripts and documentation in sync at all times.



### Core Tables

1. **auth_users** - User authentication and user_code generation
2. **jobs** - Restore job queue with lifecycle tracking
3. **job_events** - Audit log for job status transitions
4. **db_hosts** - Target database server configurations (UUID primary key)
5. **settings** - Runtime configuration (S3 paths, defaults, description column)
6. **locks** - Distributed locking for coordination

## Database Schema Update Workflow (MANDATORY)

All database structure changes must follow this workflow:

1. **Update documentation first**: Edit `docs/mysql-schema.md` to reflect the desired schema changes.
2. **Update schema assets**: Modify the numbered files under `schema/pulldb/` and create/update `scripts/setup-tests-dbdata.sh` to match the new schema.
3. **Use sudo for all admin tasks**: All database schema changes, migrations, and resets on development databases must use `sudo`.
4. **Apply changes by running**:
   ```bash
   cat schema/pulldb/*.sql | mysql -u root -p
   # If test data setup script exists:
   sudo scripts/setup-tests-dbdata.sh
   ```
5. **Verify schema and initial data**:
   ```bash
   sudo mysql -e "USE pulldb; SHOW TABLES;"
   sudo mysql -e "USE pulldb; SELECT * FROM settings;"
   sudo mysql -e "USE pulldb; SELECT * FROM db_hosts;"
   ```
6. **Update tests and documentation**: Ensure all tests and documentation match the new schema and credential patterns.

**CRITICAL MANDATES**:
- Never apply schema changes manually via MySQL client; always use the setup scripts.
- Always use `sudo` for database admin operations in development.
- Keep setup scripts and documentation in sync at all times.
- All tests must use AWS Secrets Manager for database login (see `.github/copilot-instructions.md`).

### Initial Data

**db_hosts**:
```sql
id                                 | hostname             | enabled
------------------------------------|---------------------|--------
550e8400-e29b-41d4-a716-446655440003 | localhost            | TRUE    (local development default)
f869577c-752a-4fbd-b257-4e6f8930d77d | dev-db-01            | TRUE
```

**settings**:
```sql
setting_key                  | setting_value                                   | description
-----------------------------|------------------------------------------------|-----------------------------
default_dbhost               | localhost                                     | Default database host (local sandbox)
s3_bucket_path               | pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod | S3 backup bucket path
work_dir                     | /mnt/data/pulldb/work                          | Working directory for restores
customers_after_sql_dir      | /opt/pulldb.service/customers_after_sql        | Post-restore SQL for customers
qa_template_after_sql_dir    | /opt/pulldb.service/qa_template_after_sql      | Post-restore SQL for QA templates
```

## Python MySQL Libraries

Two MySQL libraries are installed in the virtual environment:

1. **mysql-connector-python** (9.5.0) - Official Oracle MySQL connector
   - Pure Python implementation with C extension
   - Full MySQL 8.x protocol support
   - Recommended for production use

2. **pymysql** (1.4.6) - Pure Python MySQL client
   - Lightweight, pure Python implementation
   - Good for development and testing
   - No C dependencies

**Installation**:
```bash
source venv/bin/activate
pip install mysql-connector-python pymysql
```

**Verification**:
```python
import mysql.connector
import pymysql

# Test connection (mysql-connector-python)
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    database='pulldb'
)

# Test connection (pymysql)
conn = pymysql.connect(
    host='localhost',
    user='root',
    database='pulldb'
)
```

## Manual Installation Steps

If you prefer manual installation instead of using the scripts:

### 1. Install MySQL

```bash
sudo apt update
sudo apt install -y mysql-server mysql-client
sudo apt install -y libmysqlclient-dev pkg-config
```

### 2. Configure Data Directories

```bash
# Stop MySQL
sudo systemctl stop mysql

# Create directories
sudo mkdir -p /mnt/data/mysql/data
sudo mkdir -p /mnt/data/mysql/tmpdir

# Copy existing data
sudo rsync -av /var/lib/mysql/ /mnt/data/mysql/data/

# Set ownership and permissions
sudo chown -R mysql:mysql /mnt/data/mysql
sudo chmod 750 /mnt/data/mysql/data
sudo chmod 750 /mnt/data/mysql/tmpdir
```

### 3. Update MySQL Configuration

Add to `/etc/mysql/mysql.conf.d/mysqld.cnf`:

```ini
# pullDB Custom Configuration
datadir         = /mnt/data/mysql/data
tmpdir          = /mnt/data/mysql/tmpdir
innodb_data_home_dir = /mnt/data/mysql/data
innodb_log_group_home_dir = /mnt/data/mysql/data
log_bin         = /mnt/data/mysql/data/binlog
```

### 4. Update AppArmor

Add to `/etc/apparmor.d/local/usr.sbin.mysqld`:

```
# pullDB custom data directory
/mnt/data/mysql/ r,
/mnt/data/mysql/** rwk,
```

Reload AppArmor:
```bash
sudo systemctl reload apparmor
```

### 5. Start MySQL

```bash
sudo systemctl start mysql
```

### 6. Verify Configuration

```bash
sudo mysql -e "SHOW VARIABLES LIKE 'datadir';"
sudo mysql -e "SHOW VARIABLES LIKE 'tmpdir';"
```

## Troubleshooting

### MySQL won't start after configuration change

1. Check MySQL error log:
   ```bash
   sudo tail -f /var/log/mysql/error.log
   ```

2. Verify directory ownership:
   ```bash
   ls -la /mnt/data/mysql/
   ```

3. Check AppArmor denials:
   ```bash
   sudo dmesg | grep -i apparmor
   sudo aa-status
   ```

### Permission denied errors

Ensure mysql user owns the data directory:
```bash
sudo chown -R mysql:mysql /mnt/data/mysql
```

### AppArmor blocking access

Temporarily disable AppArmor for MySQL to test:
```bash
sudo aa-complain /usr/sbin/mysqld
```

Then re-enable after fixing permissions:
```bash
sudo aa-enforce /usr/sbin/mysqld
```

## Next Steps

After MySQL setup is complete:

1. ✅ MySQL 8.x installed and running
2. ✅ Data directories configured on `/mnt/data/mysql`
3. ✅ Python MySQL libraries installed
4. ⏭️ **Run schema setup**: `cat schema/pulldb/*.sql | mysql -u root -p`
5. ⏭️ **Create pulldb_app and pulldb_test users**: See "MySQL User Creation" section above
6. ⏭️ **Store credentials in Secrets Manager**: See `aws-secrets-manager-setup.md`
7. ⏭️ **Begin Python implementation** (Milestone 1.3 - Configuration Module)

See [IMPLEMENTATION-PLAN.md](../IMPLEMENTATION-PLAN.md) for the complete development roadmap.
