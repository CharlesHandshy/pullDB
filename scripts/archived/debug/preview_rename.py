"""Preview atomic rename SQL."""

import logging
import os
import sys

from dotenv import load_dotenv

from pulldb.domain.config import Config
from pulldb.infra.mysql import HostRepository, MySQLPool
from pulldb.infra.secrets import CredentialResolver

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("preview")

def main() -> None:
    load_dotenv("/opt/pulldb.service/.env")
    config = Config.minimal_from_env()
    
    coord_secret_id = os.getenv("PULLDB_COORDINATION_SECRET")
    resolver = CredentialResolver(config.aws_profile)
    
    if coord_secret_id:
        creds = resolver.resolve(coord_secret_id)
        pool = MySQLPool(host=creds.host, user=creds.username, password=creds.password, database=config.mysql_database)
    else:
        pool = MySQLPool(host=config.mysql_host, user=config.mysql_user, password=config.mysql_password, database=config.mysql_database)
        
    host_repo = HostRepository(pool, resolver)
    target_creds = host_repo.get_host_credentials("localhost")
    
    target_pool = MySQLPool(
        host=target_creds.host,
        port=target_creds.port,
        user=target_creds.username,
        password=target_creds.password,
        database="mysql"
    )
    
    with target_pool.connection() as conn:
        with conn.cursor() as cursor:
            logger.info("Setting group_concat_max_len...")
            cursor.execute("SET SESSION group_concat_max_len = 1000000")
            
            logger.info("Calling preview procedure...")
            cursor.callproc("pulldb_atomic_rename_preview", ["charleappalachian_1554ef81c76d", "charleappalachian"])
            
            # Fetch result
            for result in cursor.stored_results():
                row = result.fetchone()
                if row:
                    sql = row[0]
                    logger.info(f"Generated SQL length: {len(sql)}")
                    logger.info(f"SQL start: {sql[:100]}")
                    logger.info(f"SQL end: {sql[-100:]}")
                else:
                    logger.error("No result returned")

if __name__ == "__main__":
    main()
