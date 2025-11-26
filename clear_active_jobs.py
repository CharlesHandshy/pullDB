import os
import sys
from dotenv import load_dotenv
from pulldb.infra.mysql import build_default_pool
from pulldb.domain.config import Config
from pulldb.infra.secrets import CredentialResolver

def main():
    load_dotenv()
    
    # Load config
    config = Config.minimal_from_env()
    
    # Resolve secret
    coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
    if coordination_secret and config.mysql_user == "root" and not config.mysql_password:
        try:
            resolver = CredentialResolver(config.aws_profile)
            creds = resolver.resolve(coordination_secret)
            config.mysql_host = creds.host
            config.mysql_user = creds.username
            config.mysql_password = creds.password
        except Exception as e:
            print(f"Failed to resolve secret: {e}")
            sys.exit(1)

    pool = build_default_pool(
        host=config.mysql_host,
        user=config.mysql_user,
        password=config.mysql_password,
        database=config.mysql_database,
    )

    target = "charleappalachian"
    print(f"Clearing active jobs for target '{target}'...")
    
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE jobs 
                SET status = 'failed', error_detail = 'Manual clear by script' 
                WHERE target = %s AND status IN ('queued', 'running')
                """,
                (target,)
            )
            print(f"Updated {cursor.rowcount} rows.")
            conn.commit()

if __name__ == "__main__":
    main()
