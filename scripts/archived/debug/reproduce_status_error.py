import os
import sys
import logging
from dotenv import load_dotenv
from pulldb.infra.mysql import JobRepository, build_default_pool
from pulldb.infra.secrets import CredentialResolver

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load env
load_dotenv("/opt/pulldb.service/.env")


def main():
    secret_id = os.getenv("PULLDB_COORDINATION_SECRET")
    aws_profile = os.getenv("PULLDB_AWS_PROFILE")

    if not secret_id:
        # Fallback to local dev env vars if secret not set
        host = os.getenv("PULLDB_MYSQL_HOST", "localhost")
        user = os.getenv("PULLDB_MYSQL_USER", "root")
        password = os.getenv("PULLDB_MYSQL_PASSWORD", "")
        database = os.getenv("PULLDB_MYSQL_DATABASE", "pulldb")
        logger.info(f"Using env vars: {host}, {user}, {database}")
    else:
        logger.info(f"Resolving secret: {secret_id}")
        resolver = CredentialResolver(aws_profile)
        creds = resolver.resolve(secret_id)
        host = creds.host
        user = creds.username
        password = creds.password
        database = "pulldb"  # Assumed or from config

    try:
        pool = build_default_pool(host, user, password, database)
        repo = JobRepository(pool)

        logger.info("Calling get_recent_jobs(limit=5)...")
        jobs = repo.get_recent_jobs(limit=5)

        logger.info(f"Successfully retrieved {len(jobs)} jobs.")
        for job in jobs:
            logger.info(f"Job {job.id}: {job.status} - {job.current_operation}")

    except Exception as e:
        logger.error(f"Failed to get recent jobs: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
