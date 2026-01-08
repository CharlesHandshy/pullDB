#!/usr/bin/env python3
"""Debug and fix atomic rename silent failure for job 380a026a.

This script investigates and attempts to complete the failed atomic rename
for job 380a026a-5dc9-4eb2-b699-17681534c230 on aurora-test.

Investigation steps:
1. Query job details from pulldb_service.jobs
2. Verify current state of staging/target databases
3. Get host credentials from AWS Secrets Manager
4. Attempt atomic rename with new validation logic
5. Update job status based on outcome
6. Output comprehensive diagnostics

Usage:
    python3 scripts/debug_atomic_rename_silent_failure.py [--dry-run]

Options:
    --dry-run    Check state without attempting rename
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import mysql.connector

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pulldb.infra.logging import get_logger
from pulldb.worker.atomic_rename import (
    AtomicRenameConnectionSpec,
    AtomicRenameSpec,
    atomic_rename_staging_to_target,
)

logger = get_logger("debug_atomic_rename")

JOB_ID = "380a026a-5dc9-4eb2-b699-17681534c230"


def get_pulldb_connection() -> mysql.connector.MySQLConnection:
    """Get connection to pulldb_service database."""
    return mysql.connector.connect(
        host=os.getenv("PULLDB_SERVICE_DB_HOST", "localhost"),
        port=int(os.getenv("PULLDB_SERVICE_DB_PORT", "3306")),
        user=os.getenv("PULLDB_SERVICE_DB_USER", "pulldb"),
        password=os.getenv("PULLDB_SERVICE_DB_PASSWORD", ""),
        database="pulldb_service",
        autocommit=True,
    )


def get_job_details(conn: Any) -> dict[str, Any]:
    """Query job details from pulldb_service."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT
            id, hostname, target, status, started_at, completed_at,
            snapshot, aws_account, job_metadata, error_message
        FROM jobs
        WHERE id = %s
        """,
        (JOB_ID,)
    )
    job = cursor.fetchone()
    cursor.close()
    
    if not job:
        raise ValueError(f"Job {JOB_ID} not found")
    
    return job  # type: ignore


def get_database_state(host_conn: Any, staging_db: str, target_db: str) -> dict[str, Any]:
    """Check current state of staging and target databases."""
    cursor = host_conn.cursor()
    
    # Check staging
    cursor.execute("SHOW DATABASES LIKE %s", (staging_db,))
    staging_exists = cursor.fetchone() is not None
    
    staging_table_count = 0
    if staging_exists:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
            (staging_db,)
        )
        result = cursor.fetchone()
        staging_table_count = int(result[0]) if result else 0
    
    # Check target
    cursor.execute("SHOW DATABASES LIKE %s", (target_db,))
    target_exists = cursor.fetchone() is not None
    
    target_table_count = 0
    if target_exists:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
            (target_db,)
        )
        result = cursor.fetchone()
        target_table_count = int(result[0]) if result else 0
    
    cursor.close()
    
    return {
        "staging_exists": staging_exists,
        "staging_table_count": staging_table_count,
        "target_exists": target_exists,
        "target_table_count": target_table_count,
    }


def get_host_credentials(hostname: str, aws_account: str) -> dict[str, Any]:
    """Get MySQL credentials from AWS Secrets Manager."""
    # Get the credential reference from db_hosts
    service_conn = get_pulldb_connection()
    cursor = service_conn.cursor()
    cursor.execute(
        "SELECT credential_ref FROM db_hosts WHERE hostname = %s",
        (hostname,)
    )
    row = cursor.fetchone()
    cursor.close()
    service_conn.close()
    
    if not row:
        raise ValueError(f"Host {hostname} not found in db_hosts")
    
    credential_ref = row[0]
    
    # Get credentials from Secrets Manager
    # credential_ref format: aws-secretsmanager:/path/to/secret
    secret_name = credential_ref.replace("aws-secretsmanager:", "")
    
    # Create boto3 client for the specific account
    session = boto3.Session(profile_name=aws_account if aws_account != "default" else None)
    client = session.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
    
    response = client.get_secret_value(SecretId=secret_name)
    secret_dict = json.loads(response["SecretString"])
    
    return {
        "host": secret_dict["host"],
        "port": int(secret_dict.get("port", 3306)),
        "username": secret_dict["username"],
        "password": secret_dict["password"],
    }


def attempt_atomic_rename(job: dict[str, Any], creds: dict[str, Any], staging_db: str, dry_run: bool = False) -> bool:
    """Attempt atomic rename with new validation logic."""
    if dry_run:
        logger.info("DRY RUN: Would attempt atomic rename")
        return False
    
    logger.info(f"Attempting atomic rename: {staging_db} -> {job['target']}")
    
    try:
        conn_spec = AtomicRenameConnectionSpec(
            mysql_host=creds["host"],
            mysql_port=creds["port"],
            mysql_user=creds["username"],
            mysql_password=creds["password"],
            timeout_seconds=300,
        )
        rename_spec = AtomicRenameSpec(
            job_id=job["id"],
            staging_db=staging_db,
            target_db=job["target"],
        )
        
        atomic_rename_staging_to_target(conn_spec, rename_spec)
        logger.info("Atomic rename completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Atomic rename failed: {e}", exc_info=True)
        return False


def update_job_status(job_id: str, status: str, error_message: str | None = None) -> None:
    """Update job status in pulldb_service."""
    conn = get_pulldb_connection()
    cursor = conn.cursor()
    
    if status == "completed":
        cursor.execute(
            """
            UPDATE jobs
            SET status = 'completed', completed_at = %s, error_message = NULL
            WHERE id = %s
            """,
            (datetime.now(UTC), job_id)
        )
    else:
        cursor.execute(
            """
            UPDATE jobs
            SET status = %s, error_message = %s
            WHERE id = %s
            """,
            (status, error_message, job_id)
        )
    
    cursor.close()
    conn.close()
    logger.info(f"Updated job {job_id} status to {status}")


def main() -> int:
    """Run the debug script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check state without attempting rename"
    )
    args = parser.parse_args()
    
    logger.info(f"=== Debug Atomic Rename Silent Failure for Job {JOB_ID} ===")
    
    # Step 1: Get job details
    logger.info("Step 1: Querying job details...")
    service_conn = get_pulldb_connection()
    job = get_job_details(service_conn)
    service_conn.close()
    
    logger.info("Job details:")
    logger.info(f"  ID: {job['id']}")
    logger.info(f"  Hostname: {job['hostname']}")
    logger.info(f"  Target: {job['target']}")
    logger.info(f"  Status: {job['status']}")
    logger.info(f"  Started: {job['started_at']}")
    logger.info(f"  Completed: {job['completed_at']}")
    logger.info(f"  AWS Account: {job['aws_account']}")
    
    # Infer staging database name from job metadata
    staging_db = f"pulldb_staging_{job['target']}"
    
    # Step 2: Get host credentials
    logger.info("\nStep 2: Getting host credentials...")
    creds = get_host_credentials(job["hostname"], job["aws_account"])
    logger.info(f"  Host: {creds['host']}:{creds['port']}")
    logger.info(f"  User: {creds['username']}")
    
    # Step 3: Check database state
    logger.info("\nStep 3: Checking database state...")
    host_conn = mysql.connector.connect(
        host=creds["host"],
        port=creds["port"],
        user=creds["username"],
        password=creds["password"],
        autocommit=True,
    )
    state = get_database_state(host_conn, staging_db, job["target"])
    host_conn.close()
    
    logger.info("Database state:")
    logger.info(f"  Staging DB ({staging_db}):")
    logger.info(f"    Exists: {state['staging_exists']}")
    logger.info(f"    Tables: {state['staging_table_count']}")
    logger.info(f"  Target DB ({job['target']}):")
    logger.info(f"    Exists: {state['target_exists']}")
    logger.info(f"    Tables: {state['target_table_count']}")
    
    # Step 4: Analyze state and decide action
    logger.info("\nStep 4: Analyzing state...")
    
    if state["staging_exists"] and state["staging_table_count"] > 0:
        if state["target_exists"]:
            logger.warning(
                "⚠️  BOTH staging and target exist! This is unexpected. "
                "Manual investigation required."
            )
            return 1
        else:
            logger.info(
                "✓ Staging exists with tables, target doesn't exist. "
                "This matches the reported failure state."
            )
            
            if not args.dry_run:
                logger.info("\nStep 5: Attempting atomic rename with new validation...")
                success = attempt_atomic_rename(job, creds, staging_db, dry_run=False)
                
                if success:
                    logger.info("\n✅ SUCCESS! Atomic rename completed.")
                    logger.info("Step 6: Updating job status to completed...")
                    update_job_status(job["id"], "completed")
                    logger.info("Job status updated successfully!")
                    return 0
                else:
                    logger.error("\n❌ FAILED! Atomic rename still failed.")
                    logger.info("Staging database preserved for inspection.")
                    return 1
            else:
                logger.info("\nDRY RUN: Would attempt atomic rename here.")
                return 0
    
    elif not state["staging_exists"] and state["target_exists"]:
        logger.info(
            "✓ Rename already completed! Staging gone, target exists. "
            "Job status just needs updating."
        )
        
        if not args.dry_run:
            logger.info("Updating job status to completed...")
            update_job_status(job["id"], "completed")
            logger.info("Job status updated successfully!")
        else:
            logger.info("DRY RUN: Would update job status here.")
        return 0
    
    else:
        logger.error(
            f"❌ Unexpected state: staging_exists={state['staging_exists']}, "
            f"target_exists={state['target_exists']}"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
