import os
import sys
from pulldb.infra.mysql import build_default_pool
from pulldb.domain.config import Config

# Load config to get DB creds
config = Config.minimal_from_env()

# Override with coordination secret if needed (similar to service.py)
coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
if coordination_secret and config.mysql_user == "root" and not config.mysql_password:
    from pulldb.infra.secrets import CredentialResolver

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

job_id = "8810373a-a539-41c4-92ee-06562e659579"

print(f"Marking job {job_id} as failed...")
with pool.connection() as conn:
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE jobs SET status = 'failed', error_detail = 'Manual reset' WHERE id = %s",
            (job_id,),
        )
        conn.commit()
        print(f"Updated {cursor.rowcount} rows.")
