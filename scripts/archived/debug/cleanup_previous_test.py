import os
import shutil
import logging
from dotenv import load_dotenv
from pulldb.domain.config import Config
from pulldb.infra.mysql import build_default_pool
from pulldb.infra.secrets import CredentialResolver

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cleanup")

def cleanup():
    load_dotenv()
    
    # 1. Load Config to get DB creds
    base_config = Config.minimal_from_env()
    
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
            return

    # 2. Connect to MySQL
    # Try to get restore user credentials which should have DROP privileges
    try:
        resolver = CredentialResolver(base_config.aws_profile)
        # Assuming localhost-test is the secret for the target host 'localhost'
        creds = resolver.resolve("aws-secretsmanager:/pulldb/mysql/localhost-test")
        print(f"Using restore user: {creds.username}")
        pool = build_default_pool(
            host=creds.host,
            user=creds.username,
            password=creds.password,
            database=base_config.mysql_database,
        )
    except Exception as e:
        print(f"Failed to resolve restore credentials, falling back to config: {e}")
        pool = build_default_pool(
            host=base_config.mysql_host,
            user=base_config.mysql_user,
            password=base_config.mysql_password,
            database=base_config.mysql_database,
        )
    
    # 3. Drop Staging Database
    staging_db = "charleactionpest_64d7e2d4350a"
    print(f"Dropping staging database: {staging_db}")
    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS {staging_db}")
        print("Database dropped.")
    except Exception as e:
        print(f"Error dropping database: {e}")

    # 4. Clean Work Directory
    work_dir = "/tmp/pulldb_test_actionpest"
    print(f"Cleaning work directory: {work_dir}")
    if os.path.exists(work_dir):
        try:
            shutil.rmtree(work_dir)
            print("Work directory removed.")
        except Exception as e:
            print(f"Error removing work directory: {e}")
    else:
        print("Work directory does not exist.")

    # 5. Cleanup Active Jobs
    print("Cleaning up active jobs for target 'charleactionpest'...")
    try:
        # Reconnect with app user for coordination DB updates
        pool_app = build_default_pool(
            host=base_config.mysql_host,
            user=base_config.mysql_user,
            password=base_config.mysql_password,
            database=base_config.mysql_database,
        )
        with pool_app.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE jobs 
                    SET status = 'failed', completed_at = UTC_TIMESTAMP(6), error_detail = 'Cleanup script'
                    WHERE target = 'charleactionpest' AND status IN ('queued', 'running')
                    """
                )
                print(f"Marked {cursor.rowcount} jobs as failed.")
            conn.commit()
    except Exception as e:
        print(f"Error cleaning up jobs: {e}")

if __name__ == "__main__":
    cleanup()
