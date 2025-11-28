import os
from dotenv import load_dotenv
from pulldb.domain.config import Config
from pulldb.infra.mysql import build_default_pool, SettingsRepository
from pulldb.infra.secrets import CredentialResolver


def main():
    load_dotenv()
    config = Config.minimal_from_env()

    coordination_secret = os.getenv("PULLDB_COORDINATION_SECRET")
    if (
        coordination_secret
        and config.mysql_user == "root"
        and not config.mysql_password
    ):
        try:
            resolver = CredentialResolver(config.aws_profile)
            creds = resolver.resolve(coordination_secret)
            config.mysql_host = creds.host
            config.mysql_user = creds.username
            config.mysql_password = creds.password
        except Exception as e:
            print(f"Failed to resolve coordination secret: {e}")
            return

    pool = build_default_pool(
        host=config.mysql_host,
        user=config.mysql_user,
        password=config.mysql_password,
        database=config.mysql_database,
    )

    with pool.connection() as conn:
        with conn.cursor() as cursor:
            print("Deleting obsolete settings...")
            cursor.execute(
                "DELETE FROM settings WHERE setting_key IN ('customers_after_sql_dir', 'qa_template_after_sql_dir')"
            )
            print(f"Deleted {cursor.rowcount} rows.")
        conn.commit()


if __name__ == "__main__":
    main()
