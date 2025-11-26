
import json
import logging
import os
import sys

from pulldb.domain.config import Config
from pulldb.domain.models import JobStatus
from pulldb.infra.mysql import JobRepository, build_default_pool
from pulldb.infra.secrets import CredentialResolver

logging.basicConfig(level=logging.INFO)

def main():
    print("Bootstrap config...")
    # Bootstrap config
    base_config = Config.minimal_from_env()
    
    print("Resolving secret...")
    # Resolve coordination secret
    coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
    if (
        coordination_secret
        and base_config.mysql_user == "root"
        and not base_config.mysql_password
    ):
        try:
            resolver = CredentialResolver(base_config.aws_profile)
            creds = resolver.resolve(coordination_secret)
            base_config.mysql_host = creds.host
            base_config.mysql_user = creds.username
            base_config.mysql_password = creds.password
        except Exception as e:
            print(f"Failed to resolve coordination secret: {e}")
            pass

    pool = build_default_pool(
        host=base_config.mysql_host,
        user=base_config.mysql_user,
        password=base_config.mysql_password,
        database=base_config.mysql_database,
    )

    job_repo = JobRepository(pool)

    # Check job status
    # Assuming we want the latest job for 'charleappalachian'
    # jobs = job_repo.get_active_jobs() # This only returns queued/running
    # We need completed jobs.
    # get_recent_jobs supports status filter.

    recent_jobs = job_repo.get_recent_jobs(
        limit=10, statuses=[JobStatus.COMPLETE.value, JobStatus.FAILED.value]
    )
    target_job = None
    for job in recent_jobs:
        if job.target == "charleappalachian":
            target_job = job
            break

    if not target_job:
        print("No completed/failed job found for charleappalachian yet.")
        # Check active
        active = job_repo.get_active_jobs()
        for job in active:
            if job.target == "charleappalachian":
                print(
                    f"Job {job.id} is still {job.status.value} "
                    f"(op: {job.current_operation})"
                )
                sys.exit(0)
        print("Job not found in active or recent history.")
        sys.exit(1)

    print(f"Job {target_job.id} finished with status: {target_job.status.value}")

    if target_job.status == JobStatus.FAILED:
        print(f"Error detail: {target_job.error_detail}")
        # sys.exit(1) # Don't exit, let's check DBs anyway

    # Verify target database
    print(f"Verifying target database: {target_job.target}")
    with pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SHOW DATABASES LIKE '{target_job.target}'")
        if not cursor.fetchone():
            print(f"Target database {target_job.target} does not exist!")
        else:
            print("Target database exists.")

        # Verify staging is gone
        staging_name = target_job.staging_name
        cursor.execute(f"SHOW DATABASES LIKE '{staging_name}'")
        if cursor.fetchone():
            print(f"Staging database {staging_name} still exists (should be dropped)!")
            # Drop it to clean up
            print(f"Dropping staging database {staging_name}...")
            cursor.execute(f"DROP DATABASE `{staging_name}`")
            print("Dropped.")
        else:
            print("Staging database cleaned up.")

    # Check job status
    # Assuming we want the latest job for 'charleappalachian'
    # jobs = job_repo.get_active_jobs() # This only returns queued/running
    # We need completed jobs.
    # get_recent_jobs supports status filter.

    recent_jobs = job_repo.get_recent_jobs(
        limit=10, statuses=[JobStatus.COMPLETE.value, JobStatus.FAILED.value]
    )
    target_job = None
    for job in recent_jobs:
        if job.target == "charleappalachian":
            target_job = job
            break

    if not target_job:
        print("No completed/failed job found for charleappalachian yet.")
        # Check active
        active = job_repo.get_active_jobs()
        for job in active:
            if job.target == "charleappalachian":
                print(
                    f"Job {job.id} is still {job.status.value} "
                    f"(op: {job.current_operation})"
                )
                sys.exit(0)
        print("Job not found in active or recent history.")
        sys.exit(1)

    print(f"Job {target_job.id} finished with status: {target_job.status.value}")

    if target_job.status == JobStatus.FAILED:
        print(f"Error detail: {target_job.error_detail}")
        sys.exit(1)

    # Verify target database
    print(f"Verifying target database: {target_job.target}")
    with pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SHOW DATABASES LIKE '{target_job.target}'")
        if not cursor.fetchone():
            print(f"Target database {target_job.target} does not exist!")
            sys.exit(1)
        print("Target database exists.")

        # Verify pullDB table
        cursor.execute(f"USE `{target_job.target}`")
        cursor.execute("SHOW TABLES LIKE 'pullDB'")
        if not cursor.fetchone():
            print("pullDB table missing!")
            sys.exit(1)
        print("pullDB table exists.")

        # Check metadata
        cursor.execute("SELECT * FROM pullDB")
        row = cursor.fetchone()
        if not row:
            print("pullDB table is empty!")
            sys.exit(1)

        # row is tuple, need to map columns
        # job_id, restored_by, restored_at, backup_file,
        # post_restore_sql_status, restore_completed_at
        print(f"Metadata: {row}")

        # Check post-sql status
        # post_restore_sql_status is JSON column, might be returned as string
        # or dict depending on connector
        status_json = row[4]
        if isinstance(status_json, str):
            status_data = json.loads(status_json)
        else:
            status_data = status_json

        print("Post-SQL Status:")
        print(json.dumps(status_data, indent=2))

        # Verify staging is gone
        staging_name = target_job.staging_name
        cursor.execute(f"SHOW DATABASES LIKE '{staging_name}'")
        if cursor.fetchone():
            print(f"Staging database {staging_name} still exists (should be dropped)!")
            # This might be okay if we failed, but we checked for success.
            sys.exit(1)
        print("Staging database cleaned up.")

if __name__ == "__main__":
    main()
