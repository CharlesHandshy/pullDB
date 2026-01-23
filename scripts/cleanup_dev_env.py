#!/usr/bin/env python3
"""Cleanup development environment.

Drops all customer/staging databases and clears the jobs/history tables.
WARNING: This is destructive!
"""

import logging
import sys

import mysql.connector

from pulldb.domain.config import Config


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("cleanup")

KEEP_DBS = {
    "information_schema",
    "mysql",
    "performance_schema",
    "sys",
    "pulldb",
    "pulldb_test_coordination",
}


def get_db_connection(config: Config):
    """Get MySQL connection using config credentials."""
    return mysql.connector.connect(
        host=config.mysql_host,
        user=config.mysql_user,
        password=config.mysql_password,
        database=config.mysql_database,  # Connect to pulldb initially
    )


def cleanup():
    """Execute cleanup of databases and job history."""
    config = Config.minimal_from_env()

    # Override with root if needed for DROP DATABASE permissions
    # Assuming the configured user might not have DROP privileges on all DBs
    # But in dev, it's usually root or has high privs.
    # If PULLDB_MYSQL_USER is not root, we might want to try root/no-pass or prompt.
    # For now, use config, but fallback to root if config is not root.

    try:
        conn = get_db_connection(config)
    except mysql.connector.Error as e:
        logger.error(f"Failed to connect with config credentials: {e}")
        logger.info("Trying root@localhost with empty password...")
        try:
            # Try standard socket connection for root (auth_socket)
            conn = mysql.connector.connect(
                user="root",
                password="",
                unix_socket="/var/run/mysqld/mysqld.sock",
                database="pulldb_service",
            )
        except mysql.connector.Error as e2:
            logger.error(f"Failed to connect as root via socket: {e2}")
            sys.exit(1)

    cursor = conn.cursor()

    # 1. Identify databases to drop
    logger.info("Scanning for databases to drop...")
    cursor.execute("SHOW DATABASES")
    # type: ignore[index] - cursor.fetchall() returns tuples here
    all_dbs = {str(row[0]) for row in cursor.fetchall()}

    dbs_to_drop = [db for db in all_dbs if db not in KEEP_DBS]

    if not dbs_to_drop:
        logger.info("No databases found to drop.")
    else:
        logger.info(
            f"Found {len(dbs_to_drop)} databases to drop: {', '.join(dbs_to_drop)}"
        )
        # confirm = input("Proceed with DROP DATABASE? [y/N] ")
        # if confirm.lower() != 'y':
        #     logger.info("Aborted.")
        #     return

        for db in dbs_to_drop:
            logger.info(f"Dropping database: {db}")
            try:
                cursor.execute(f"DROP DATABASE `{db}`")
            except mysql.connector.Error as e:
                logger.error(f"Failed to drop {db}: {e}")

    # 2. Truncate jobs and history
    logger.info("Cleaning up jobs and history...")
    try:
        # Disable foreign key checks to allow truncation if needed
        # (though jobs/events usually fine)
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

        logger.info("Truncating job_events...")
        cursor.execute("TRUNCATE TABLE pulldb.job_events")

        logger.info("Truncating jobs...")
        cursor.execute("TRUNCATE TABLE pulldb.jobs")

        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        logger.info("Jobs and history cleared.")

    except mysql.connector.Error as e:
        logger.error(f"Failed to clean up tables: {e}")

    conn.close()
    logger.info("Cleanup complete.")


if __name__ == "__main__":
    cleanup()
