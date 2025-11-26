import os
import sys
import mysql.connector
from pulldb.infra.secrets import CredentialResolver

# Set env vars
if "AWS_PROFILE" in os.environ:
    del os.environ["AWS_PROFILE"]
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

def reset_jobs():
    print("Resolving credentials...")
    resolver = CredentialResolver()
    creds = resolver.resolve("aws-secretsmanager:/pulldb/mysql/coordination-db")
    
    print(f"Connecting to {creds.host}...")
    conn = mysql.connector.connect(
        host=creds.host,
        user=creds.username,
        password=creds.password,
        database="pulldb"
    )
    cursor = conn.cursor()
    
    print("Resetting running jobs to failed...")
    cursor.execute("UPDATE jobs SET status='failed', error_detail='Manual reset' WHERE status='running'")
    print(f"Updated {cursor.rowcount} rows.")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    reset_jobs()
