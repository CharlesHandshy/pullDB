"""Deploy atomic rename procedure."""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from pulldb.domain.config import Config
from pulldb.infra.mysql import HostRepository, MySQLPool
from pulldb.infra.secrets import CredentialResolver

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deploy_proc")

def main() -> None:
    load_dotenv("/opt/pulldb/.env")

    try:
        config = Config.minimal_from_env()
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Resolve coordination credentials
    coord_secret_id = os.getenv("PULLDB_COORDINATION_SECRET")
    coord_host = config.mysql_host
    coord_user = config.mysql_user
    coord_password = config.mysql_password

    resolver = CredentialResolver(config.aws_profile)

    if coord_secret_id:
        try:
            creds = resolver.resolve(coord_secret_id)
            coord_host = creds.host
            coord_user = creds.username
            coord_password = creds.password
        except Exception as e:
            logger.error(f"Failed to resolve coordination credentials: {e}")
            sys.exit(1)

    pool = MySQLPool(
        host=coord_host,
        user=coord_user,
        password=coord_password,
        database=config.mysql_database,
    )
    host_repo = HostRepository(pool, resolver)

    target_host = "localhost"
    try:
        target_creds = host_repo.get_host_credentials(target_host)
    except Exception as e:
        logger.error(f"Failed to resolve target credentials: {e}")
        sys.exit(1)

    # Read SQL file
    sql_path = Path("docs/atomic_rename_procedure.sql")
    if not sql_path.exists():
        logger.error(f"SQL file not found: {sql_path}")
        sys.exit(1)
    
    sql_content = sql_path.read_text()

    # Write credentials to temp file and run mysql client
    import subprocess
    import tempfile

    logger.info(f"Deploying procedure to {target_host} using mysql client...")
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write(f"[client]\nuser={target_creds.username}\npassword={target_creds.password}\nhost={target_creds.host}\nport={target_creds.port}\n")
        cnf_path = f.name

    try:
        cmd = ["mysql", f"--defaults-file={cnf_path}", "--database=mysql"]
        with open(sql_path, "r") as sql_file:
            result = subprocess.run(cmd, stdin=sql_file, capture_output=True, text=True)
            
        if result.returncode != 0:
            logger.error(f"mysql client failed:\n{result.stderr}")
            sys.exit(1)
        else:
            logger.info("Deployment complete via mysql client.")
            
    finally:
        os.unlink(cnf_path)

if __name__ == "__main__":
    main()
