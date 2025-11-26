import os
import sys
import uuid
import logging
import json
from datetime import datetime
from dotenv import load_dotenv
from pulldb.domain.config import Config
from pulldb.domain.models import Job, JobStatus
from pulldb.infra.mysql import MySQLPool, JobRepository, UserRepository, build_default_pool
from pulldb.worker.loop import run_poll_loop
from pulldb.worker.service import _build_job_executor
from pulldb.infra.secrets import CredentialResolver

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("manual_test")

def main():
    print("--- Manual Integration Test ---")
    
    # Load environment variables
    load_dotenv()
    
    # 1. Load Config
    print("Loading configuration...")
    # Bootstrap config to get credentials for pool
    base_config = Config.minimal_from_env()
    
    # Resolve coordination secret if needed (copied from service.py logic)
    coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
    if coordination_secret and base_config.mysql_user == "root" and not base_config.mysql_password:
        try:
            resolver = CredentialResolver(base_config.aws_profile)
            creds = resolver.resolve(coordination_secret)
            base_config.mysql_host = creds.host
            base_config.mysql_user = creds.username
            base_config.mysql_password = creds.password
        except Exception as e:
            print(f"Failed to resolve coordination secret: {e}")
            sys.exit(1)

    pool = build_default_pool(
        host=base_config.mysql_host,
        user=base_config.mysql_user,
        password=base_config.mysql_password,
        database=base_config.mysql_database,
    )
    
    config = Config.from_env_and_mysql(pool)
    print(f"Work Dir: {config.work_dir}")
    print(f"S3 Profile: {config.s3_aws_profile}")
    
    # 2. Repositories
    job_repo = JobRepository(pool)
    user_repo = UserRepository(pool)
    
    # 3. User Setup
    username = "charles"
    print(f"Getting/Creating user '{username}'...")
    user = user_repo.get_or_create_user(username)
    print(f"User: {user.username} (code: {user.user_code})")
    
    # 4. Job Setup
    customer_id = "appalachian"
    target = f"{user.user_code}{customer_id}"
    job_id = str(uuid.uuid4())
    # Staging name must match pulldb.worker.staging.generate_staging_name logic:
    # {target}_{job_id_hex[:12]} (no hyphens)
    staging_name = f"{target}_{job_id.replace('-', '')[:12]}"
    dbhost = config.default_dbhost or "localhost"
    
    print(f"Creating Job:")
    print(f"  ID: {job_id}")
    print(f"  Target: {target}")
    print(f"  Staging: {staging_name}")
    print(f"  Host: {dbhost}")
    
    job = Job(
        id=job_id,
        owner_user_id=user.user_id,
        owner_username=user.username,
        owner_user_code=user.user_code,
        target=target,
        staging_name=staging_name,
        dbhost=dbhost,
        status=JobStatus.QUEUED,
        submitted_at=datetime.utcnow(),
        options_json={"customer_id": customer_id, "overwrite": "true"},
    )
    
    # 5. Enqueue
    print("Enqueueing job...")
    try:
        job_repo.enqueue_job(job)
        print("Job enqueued successfully.")
    except Exception as e:
        print(f"Failed to enqueue job: {e}")
        # Check if it's an exclusivity error, maybe clear old jobs?
        # For now, just fail hard.
        sys.exit(1)
        
    # 6. Run Worker
    print("Starting Worker (Oneshot)...")
    executor = _build_job_executor(config, job_repo)
    
    try:
        run_poll_loop(
            job_repo,
            executor,
            max_iterations=1,
            poll_interval=1.0,
            should_stop=lambda: False
        )
        print("Worker finished.")
    except Exception as e:
        print(f"Worker failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
