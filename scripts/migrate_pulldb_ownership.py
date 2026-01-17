#!/usr/bin/env python3
"""Migrate existing pullDB metadata tables to include ownership information.

This script updates pullDB metadata tables in active databases to include
the new ownership columns (owner_user_id, owner_user_code, custom_target).

This is required for the Custom Target feature's safety checks, which verify
database ownership via the pullDB metadata table (AUTHORITATIVE source).

Usage:
    # Dry run - show what would be migrated
    python scripts/migrate_pulldb_ownership.py --dry-run
    
    # Execute migration
    python scripts/migrate_pulldb_ownership.py --execute
    
    # Verify migration completed
    python scripts/migrate_pulldb_ownership.py --verify

Requirements:
    - Service must be running (accesses job database)
    - MySQL credentials for target hosts must be available
    - Should be run during maintenance window for safety
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import mysql.connector

from pulldb.domain.config import get_config
from pulldb.domain.models import JobStatus
from pulldb.infra.factory import create_job_repository, create_host_repository
from pulldb.infra.logging import get_logger

logger = get_logger("migrate_pulldb_ownership")


@dataclass
class MigrationResult:
    """Result of migrating a single database."""
    target: str
    dbhost: str
    job_id: str
    owner_user_code: str
    status: str  # 'migrated', 'already_migrated', 'skipped', 'error'
    error: str | None = None


@dataclass
class MigrationReport:
    """Overall migration report."""
    migrated: list[MigrationResult]
    already_migrated: list[MigrationResult]
    skipped: list[MigrationResult]
    errors: list[MigrationResult]
    
    def __init__(self) -> None:
        self.migrated = []
        self.already_migrated = []
        self.skipped = []
        self.errors = []
    
    def summary(self) -> str:
        """Generate summary string."""
        return (
            f"Migration Report:\n"
            f"  Migrated:         {len(self.migrated)}\n"
            f"  Already migrated: {len(self.already_migrated)}\n"
            f"  Skipped:          {len(self.skipped)}\n"
            f"  Errors:           {len(self.errors)}"
        )


def has_pulldb_table(conn: mysql.connector.MySQLConnection, db_name: str) -> bool:
    """Check if database has pullDB metadata table."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SHOW TABLES IN `{db_name}` LIKE 'pullDB'")
        return cursor.fetchone() is not None
    except mysql.connector.Error:
        return False
    finally:
        cursor.close()


def has_ownership_columns(conn: mysql.connector.MySQLConnection, db_name: str) -> bool:
    """Check if pullDB table has the new ownership columns."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SHOW COLUMNS FROM `{db_name}`.pullDB LIKE 'owner_user_code'")
        return cursor.fetchone() is not None
    except mysql.connector.Error:
        return False
    finally:
        cursor.close()


def add_ownership_columns(conn: mysql.connector.MySQLConnection, db_name: str) -> None:
    """Add ownership columns to existing pullDB table."""
    cursor = conn.cursor()
    try:
        # Check which columns need to be added
        cursor.execute(f"SHOW COLUMNS FROM `{db_name}`.pullDB")
        existing_columns = {row[0] for row in cursor.fetchall()}
        
        alterations = []
        
        if "owner_user_id" not in existing_columns:
            alterations.append(
                "ADD COLUMN owner_user_id CHAR(36) NULL "
                "COMMENT 'UUID of database owner' AFTER job_id"
            )
        
        if "owner_user_code" not in existing_columns:
            alterations.append(
                "ADD COLUMN owner_user_code CHAR(6) NULL "
                "COMMENT '6-char owner identifier' AFTER owner_user_id"
            )
        
        if "custom_target" not in existing_columns:
            alterations.append(
                "ADD COLUMN custom_target TINYINT(1) NOT NULL DEFAULT 0 "
                "COMMENT 'Whether custom target was used' AFTER restore_duration_seconds"
            )
        
        if alterations:
            sql = f"ALTER TABLE `{db_name}`.pullDB " + ", ".join(alterations)
            cursor.execute(sql)
            conn.commit()
            
            # Add indexes if columns were added
            if "owner_user_id" not in existing_columns:
                try:
                    cursor.execute(
                        f"CREATE INDEX idx_pulldb_owner ON `{db_name}`.pullDB (owner_user_id)"
                    )
                except mysql.connector.Error:
                    pass  # Index may already exist
            
            if "owner_user_code" not in existing_columns:
                try:
                    cursor.execute(
                        f"CREATE INDEX idx_pulldb_user_code ON `{db_name}`.pullDB (owner_user_code)"
                    )
                except mysql.connector.Error:
                    pass  # Index may already exist
            
            conn.commit()
    finally:
        cursor.close()


def update_ownership_data(
    conn: mysql.connector.MySQLConnection,
    db_name: str,
    owner_user_id: str,
    owner_user_code: str,
    custom_target: bool = False,
) -> None:
    """Update pullDB table with ownership data from job record."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            UPDATE `{db_name}`.pullDB
            SET owner_user_id = %s,
                owner_user_code = %s,
                custom_target = %s
            WHERE owner_user_id IS NULL OR owner_user_code IS NULL
            """,
            (owner_user_id, owner_user_code, 1 if custom_target else 0),
        )
        conn.commit()
    finally:
        cursor.close()


def migrate_database(
    job: dict,
    host_repo: any,
    dry_run: bool,
) -> MigrationResult:
    """Migrate a single database's pullDB table."""
    target = job["target"]
    dbhost = job["dbhost"]
    job_id = job["id"]
    owner_user_id = job["owner_user_id"]
    owner_user_code = job["owner_user_code"]
    
    # Get custom_target from options_json
    options_json = job.get("options_json")
    custom_target = False
    if options_json:
        if isinstance(options_json, str):
            import json
            try:
                options_json = json.loads(options_json)
            except json.JSONDecodeError:
                options_json = {}
        if isinstance(options_json, dict):
            custom_target = options_json.get("custom_target_used") == "true"
    
    try:
        creds = host_repo.get_host_credentials(dbhost)
    except Exception as e:
        return MigrationResult(
            target=target,
            dbhost=dbhost,
            job_id=job_id,
            owner_user_code=owner_user_code,
            status="error",
            error=f"Cannot get credentials for host: {e}",
        )
    
    try:
        conn = mysql.connector.connect(
            host=creds.host,
            port=creds.port,
            user=creds.user,
            password=creds.password,
            connect_timeout=30,
        )
    except mysql.connector.Error as e:
        return MigrationResult(
            target=target,
            dbhost=dbhost,
            job_id=job_id,
            owner_user_code=owner_user_code,
            status="error",
            error=f"Cannot connect to host: {e}",
        )
    
    try:
        # Check if database exists
        cursor = conn.cursor()
        cursor.execute("SHOW DATABASES LIKE %s", (target,))
        if cursor.fetchone() is None:
            cursor.close()
            return MigrationResult(
                target=target,
                dbhost=dbhost,
                job_id=job_id,
                owner_user_code=owner_user_code,
                status="skipped",
                error="Database does not exist on host",
            )
        cursor.close()
        
        # Check if pullDB table exists
        if not has_pulldb_table(conn, target):
            return MigrationResult(
                target=target,
                dbhost=dbhost,
                job_id=job_id,
                owner_user_code=owner_user_code,
                status="skipped",
                error="No pullDB metadata table found",
            )
        
        # Check if already migrated
        if has_ownership_columns(conn, target):
            return MigrationResult(
                target=target,
                dbhost=dbhost,
                job_id=job_id,
                owner_user_code=owner_user_code,
                status="already_migrated",
            )
        
        if dry_run:
            return MigrationResult(
                target=target,
                dbhost=dbhost,
                job_id=job_id,
                owner_user_code=owner_user_code,
                status="migrated",  # Would be migrated
            )
        
        # Perform migration
        add_ownership_columns(conn, target)
        update_ownership_data(conn, target, owner_user_id, owner_user_code, custom_target)
        
        return MigrationResult(
            target=target,
            dbhost=dbhost,
            job_id=job_id,
            owner_user_code=owner_user_code,
            status="migrated",
        )
        
    except Exception as e:
        return MigrationResult(
            target=target,
            dbhost=dbhost,
            job_id=job_id,
            owner_user_code=owner_user_code,
            status="error",
            error=str(e),
        )
    finally:
        conn.close()


def get_active_jobs(job_repo: any) -> list[dict]:
    """Get all deployed and locked jobs (active databases)."""
    jobs = []
    
    # Query deployed jobs
    with job_repo.pool.connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, target, dbhost, owner_user_id, owner_user_code, options_json
            FROM jobs
            WHERE status IN ('deployed', 'complete')
            AND db_dropped_at IS NULL
            ORDER BY submitted_at DESC
            """
        )
        for row in cursor.fetchall():
            # De-duplicate by target+dbhost (keep most recent)
            key = f"{row['target']}@@{row['dbhost']}"
            if not any(f"{j['target']}@@{j['dbhost']}" == key for j in jobs):
                jobs.append(row)
        cursor.close()
    
    return jobs


def run_migration(dry_run: bool = True, verify_only: bool = False) -> MigrationReport:
    """Run the migration process."""
    config = get_config()
    job_repo = create_job_repository(config)
    host_repo = create_host_repository(config)
    
    report = MigrationReport()
    
    logger.info("Fetching active jobs...")
    jobs = get_active_jobs(job_repo)
    logger.info(f"Found {len(jobs)} active databases to check")
    
    for i, job in enumerate(jobs, 1):
        target = job["target"]
        dbhost = job["dbhost"]
        
        if verify_only:
            # Just check if migrated
            result = migrate_database(job, host_repo, dry_run=True)
            if result.status == "already_migrated":
                report.already_migrated.append(result)
            elif result.status == "migrated":
                # Would be migrated = not yet migrated
                report.skipped.append(MigrationResult(
                    target=target,
                    dbhost=dbhost,
                    job_id=job["id"],
                    owner_user_code=job["owner_user_code"],
                    status="skipped",
                    error="NOT YET MIGRATED",
                ))
            else:
                report.skipped.append(result)
        else:
            logger.info(f"[{i}/{len(jobs)}] Processing {target} on {dbhost}...")
            result = migrate_database(job, host_repo, dry_run)
            
            if result.status == "migrated":
                report.migrated.append(result)
                action = "Would migrate" if dry_run else "Migrated"
                logger.info(f"  {action}: {target} (owner: {result.owner_user_code})")
            elif result.status == "already_migrated":
                report.already_migrated.append(result)
                logger.info(f"  Already migrated: {target}")
            elif result.status == "skipped":
                report.skipped.append(result)
                logger.info(f"  Skipped: {target} ({result.error})")
            else:
                report.errors.append(result)
                logger.error(f"  ERROR: {target} - {result.error}")
    
    return report


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate pullDB metadata tables to include ownership information"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the migration",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify migration status of all databases",
    )
    
    args = parser.parse_args()
    
    if not any([args.dry_run, args.execute, args.verify]):
        parser.print_help()
        print("\nError: Must specify --dry-run, --execute, or --verify")
        return 1
    
    if args.dry_run:
        print("=" * 60)
        print("DRY RUN - No changes will be made")
        print("=" * 60)
        report = run_migration(dry_run=True)
    elif args.verify:
        print("=" * 60)
        print("VERIFY - Checking migration status")
        print("=" * 60)
        report = run_migration(dry_run=True, verify_only=True)
    else:
        print("=" * 60)
        print("EXECUTING MIGRATION")
        print("=" * 60)
        confirm = input("This will modify database tables. Continue? [y/N]: ")
        if confirm.lower() != "y":
            print("Aborted.")
            return 0
        report = run_migration(dry_run=False)
    
    print()
    print(report.summary())
    
    if report.errors:
        print("\nErrors:")
        for result in report.errors:
            print(f"  - {result.target} on {result.dbhost}: {result.error}")
    
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main())
