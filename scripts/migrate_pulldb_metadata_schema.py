#!/usr/bin/env python3
"""Migrate old pullDB metadata tables to new schema with ownership columns.

This script finds all databases with old-schema pullDB tables and migrates them
to the new schema that includes owner_user_id, owner_user_code, and custom_target.

Usage:
    # Dry run (default) - shows what would be migrated
    python scripts/migrate_pulldb_metadata_schema.py
    
    # Actually perform migration
    python scripts/migrate_pulldb_metadata_schema.py --execute
    
    # Migrate specific database
    python scripts/migrate_pulldb_metadata_schema.py --database charletanner --execute

The script:
1. Queries pulldb_service.jobs to build job_id -> owner mapping
2. Connects to each configured db_host
3. Finds databases with pullDB tables missing owner columns
4. Adds missing columns and updates with owner info from jobs table
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass

import mysql.connector

# Add parent to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

from pulldb.infra.mysql import MySQLPool
from pulldb.infra.secrets import CredentialResolver


def build_coordination_pool() -> MySQLPool:
    """Build connection pool for pulldb_service coordination database.
    
    Uses subprocess to run mysql command via sudo (auth_socket).
    """
    import subprocess
    
    # Use subprocess with sudo for local MySQL (auth_socket)
    class LocalMySQLPool:
        """Mock pool that uses sudo mysql for local access."""
        
        def __init__(self):
            pass
        
        @contextmanager
        def connection(self):
            """Return a connection-like object using subprocess."""
            yield LocalMySQLConnection()
    
    class LocalMySQLConnection:
        """Connection that executes queries via sudo mysql."""
        
        def cursor(self):
            return LocalMySQLCursor()
    
    class LocalMySQLCursor:
        """Cursor that executes queries via sudo mysql."""
        
        def __init__(self):
            self._results = []
            self._index = 0
        
        def execute(self, query):
            import subprocess
            result = subprocess.run(
                ["sudo", "mysql", "-N", "-e", query, "pulldb_service"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise Exception(f"MySQL error: {result.stderr}")
            
            self._results = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    self._results.append(tuple(line.split("\t")))
            self._index = 0
        
        def fetchall(self):
            return self._results
        
        def fetchone(self):
            if self._index < len(self._results):
                row = self._results[self._index]
                self._index += 1
                return row
            return None
        
        def close(self):
            pass
    
    return LocalMySQLPool()


@dataclass
class JobOwnerInfo:
    """Owner information from jobs table."""
    owner_user_id: str
    owner_user_code: str
    custom_target: bool


def get_job_owner_mapping(pool) -> dict[str, JobOwnerInfo]:
    """Build mapping of job_id -> owner info from pulldb_service.jobs."""
    with pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, owner_user_id, owner_user_code, custom_target
            FROM jobs
            WHERE owner_user_id IS NOT NULL
        """)
        mapping = {}
        for row in cursor.fetchall():
            job_id, owner_user_id, owner_user_code, custom_target = row
            mapping[job_id] = JobOwnerInfo(
                owner_user_id=owner_user_id,
                owner_user_code=owner_user_code,
                custom_target=bool(custom_target),
            )
        cursor.close()
        return mapping


def get_db_hosts(pool) -> list[tuple[str, str]]:
    """Get list of (hostname, credential_ref) from db_hosts."""
    with pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT hostname, credential_ref FROM db_hosts WHERE enabled = 1")
        hosts = cursor.fetchall()
        cursor.close()
        return hosts


def find_databases_with_old_pulldb(
    host: str,
    port: int,
    user: str,
    password: str,
) -> list[str]:
    """Find databases with old-schema pullDB tables (missing owner columns)."""
    conn = mysql.connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        connect_timeout=30,
    )
    cursor = conn.cursor()
    
    # Get all databases
    cursor.execute("SHOW DATABASES")
    databases = [row[0] for row in cursor.fetchall()]
    
    old_schema_dbs = []
    for db in databases:
        if db in ("information_schema", "mysql", "performance_schema", "sys"):
            continue
        
        try:
            cursor.execute(f"USE `{db}`")
            
            # Check if pullDB table exists
            cursor.execute("SHOW TABLES LIKE 'pullDB'")
            if cursor.fetchone() is None:
                continue
            
            # Check if owner_user_id column exists
            cursor.execute("SHOW COLUMNS FROM `pullDB` LIKE 'owner_user_id'")
            if cursor.fetchone() is None:
                old_schema_dbs.append(db)
        except mysql.connector.Error:
            # Skip databases we can't access
            continue
    
    cursor.close()
    conn.close()
    return old_schema_dbs


def migrate_pulldb_table(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    job_owner_mapping: dict[str, JobOwnerInfo],
    dry_run: bool = True,
) -> tuple[bool, str]:
    """Migrate a single pullDB table to new schema.
    
    Returns:
        Tuple of (success, message).
    """
    conn = mysql.connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        connect_timeout=30,
    )
    cursor = conn.cursor()
    
    try:
        # Get existing job_ids from the pullDB table
        cursor.execute("SELECT job_id FROM `pullDB`")
        job_ids = [row[0] for row in cursor.fetchall()]
        
        if not job_ids:
            return (True, "No rows to migrate")
        
        # Check which jobs we have owner info for
        matched = sum(1 for jid in job_ids if jid in job_owner_mapping)
        
        if dry_run:
            return (True, f"Would migrate {len(job_ids)} row(s), {matched} with owner info")
        
        # Step 1: Add missing columns
        alter_sql = """
            ALTER TABLE `pullDB` 
            ADD COLUMN `owner_user_id` CHAR(36) NULL 
                COMMENT 'UUID of database owner' AFTER `job_id`,
            ADD COLUMN `owner_user_code` CHAR(6) NULL 
                COMMENT '6-char owner identifier' AFTER `owner_user_id`,
            ADD COLUMN `custom_target` TINYINT(1) NOT NULL DEFAULT 0 
                COMMENT 'Whether custom target was used' AFTER `restore_duration_seconds`
        """
        cursor.execute(alter_sql)
        
        # Step 2: Add indexes (skip if no INDEX privilege - indexes are optional)
        try:
            cursor.execute("CREATE INDEX `idx_pulldb_owner` ON `pullDB` (`owner_user_id`)")
            cursor.execute("CREATE INDEX `idx_pulldb_user_code` ON `pullDB` (`owner_user_code`)")
        except mysql.connector.Error as e:
            if e.errno not in (1061, 1142):  # 1061=Duplicate key, 1142=INDEX command denied
                raise
            # Skip index creation if no privilege - indexes are for performance only
        
        # Step 3: Update with owner info from jobs mapping
        updated = 0
        for job_id in job_ids:
            if job_id in job_owner_mapping:
                info = job_owner_mapping[job_id]
                cursor.execute(
                    """
                    UPDATE `pullDB` 
                    SET owner_user_id = %s, 
                        owner_user_code = %s, 
                        custom_target = %s 
                    WHERE job_id = %s
                    """,
                    (info.owner_user_id, info.owner_user_code, int(info.custom_target), job_id),
                )
                updated += 1
        
        conn.commit()
        return (True, f"Migrated {len(job_ids)} row(s), updated {updated} with owner info")
        
    except mysql.connector.Error as e:
        conn.rollback()
        return (False, f"MySQL error: {e}")
    finally:
        cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate old pullDB metadata tables to new schema with ownership columns"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the migration (default is dry-run)",
    )
    parser.add_argument(
        "--database",
        help="Migrate only this specific database (on all hosts)",
    )
    parser.add_argument(
        "--host",
        help="Migrate only databases on this specific host",
    )
    args = parser.parse_args()
    
    dry_run = not args.execute
    
    if dry_run:
        print("=== DRY RUN MODE (use --execute to apply changes) ===\n")
    else:
        print("=== EXECUTING MIGRATION ===\n")
    
    # Connect to coordination database
    print("Connecting to pulldb_service...")
    pool = build_coordination_pool()
    
    # Build job -> owner mapping
    print("Building job owner mapping...")
    job_owner_mapping = get_job_owner_mapping(pool)
    print(f"  Found {len(job_owner_mapping)} jobs with owner info\n")
    
    # Get database hosts
    print("Getting database hosts...")
    hosts = get_db_hosts(pool)
    print(f"  Found {len(hosts)} enabled host(s)\n")
    
    resolver = CredentialResolver()
    total_migrated = 0
    total_failed = 0
    
    for hostname, credential_ref in hosts:
        if args.host and args.host not in hostname:
            continue
            
        print(f"Host: {hostname}")
        
        try:
            creds = resolver.resolve(credential_ref)
        except Exception as e:
            print(f"  ERROR: Could not resolve credentials: {e}")
            continue
        
        # Find databases with old schema
        try:
            old_dbs = find_databases_with_old_pulldb(
                creds.host, creds.port, creds.username, creds.password
            )
        except Exception as e:
            print(f"  ERROR: Could not scan host: {e}")
            continue
        
        if args.database:
            old_dbs = [db for db in old_dbs if db == args.database]
        
        if not old_dbs:
            print("  No databases with old-schema pullDB tables found\n")
            continue
        
        print(f"  Found {len(old_dbs)} database(s) with old pullDB schema:")
        
        for db in old_dbs:
            success, message = migrate_pulldb_table(
                creds.host,
                creds.port,
                creds.username,
                creds.password,
                db,
                job_owner_mapping,
                dry_run=dry_run,
            )
            
            status = "✓" if success else "✗"
            print(f"    {status} {db}: {message}")
            
            if success:
                total_migrated += 1
            else:
                total_failed += 1
        
        print()
    
    # Summary
    print("=" * 50)
    if dry_run:
        print(f"DRY RUN COMPLETE: {total_migrated} database(s) would be migrated")
    else:
        print(f"MIGRATION COMPLETE: {total_migrated} succeeded, {total_failed} failed")
    
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
