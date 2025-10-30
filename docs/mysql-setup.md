# MySQL Setup and Installation

This document describes the MySQL 8.x installation and configuration for pullDB.

## Quick Start

```bash
# 1. Install and configure MySQL 8.x
sudo scripts/setup-mysql.sh

# 2. Create pulldb coordination database
sudo scripts/setup-pulldb-schema.sh

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

### setup-pulldb-schema.sh

Creates the `pulldb` coordination database with all tables and initial data.

**Features**:
- Creates `pulldb` database with UTF-8 encoding
- Creates all required tables (auth_users, jobs, job_events, db_hosts, settings, locks)
- Sets up foreign key constraints and indexes
- Creates trigger for automatic job status logging
- Populates initial db_hosts (db3-dev, db4-dev, db5-dev)
- Populates initial settings (default_dbhost, S3 paths, work directories)

**Usage**:
```bash
sudo scripts/setup-pulldb-schema.sh
```

**What it does**:
1. Checks MySQL is running
2. Creates `pulldb` database
3. Executes schema DDL from inline SQL
4. Creates tables with proper constraints
5. Creates indexes for performance
6. Creates trigger for job event logging
7. Inserts initial db_hosts data
8. Inserts initial settings data
9. Verifies table count and shows tables
10. Displays initial configuration

**Output**:
- Database: `pulldb` created
- Tables: 6+ tables (auth_users, jobs, job_events, db_hosts, settings, locks)
- Initial data: 3 db_hosts, 5 settings

## Database Schema

### Core Tables

1. **auth_users** - User authentication and user_code generation
2. **jobs** - Restore job queue with lifecycle tracking
3. **job_events** - Audit log for job status transitions
4. **db_hosts** - Target database server configurations
5. **settings** - Runtime configuration (S3 paths, defaults)
6. **locks** - Distributed locking for coordination

### Initial Data

**db_hosts**:
```sql
hostname             | enabled
---------------------|--------
db-mysql-db3-dev     | TRUE
db-mysql-db4-dev     | TRUE    (SUPPORT default)
db-mysql-db5-dev     | TRUE
```

**settings**:
```sql
setting_key                  | setting_value
-----------------------------|--------------------------------------------------
default_dbhost               | db-mysql-db4-dev
s3_bucket_path               | pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod
work_dir                     | /mnt/data/pulldb/work
customers_after_sql_dir      | /opt/pulldb/customers_after_sql
qa_template_after_sql_dir    | /opt/pulldb/qa_template_after_sql
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
4. ⏭️ **Run schema setup**: `sudo scripts/setup-pulldb-schema.sh`
5. ⏭️ **Begin Python implementation** (Milestone 1.3 - Configuration Module)

See [IMPLEMENTATION-PLAN.md](../IMPLEMENTATION-PLAN.md) for the complete development roadmap.
