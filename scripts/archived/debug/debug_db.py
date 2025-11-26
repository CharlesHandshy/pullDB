
import os
import sys
import mysql.connector
from dotenv import load_dotenv
from pulldb.infra.secrets import CredentialResolver

# Load env from /opt/pulldb.service/.env
load_dotenv("/opt/pulldb.service/.env")

secret_id = os.getenv("PULLDB_COORDINATION_SECRET")
aws_profile = os.getenv("PULLDB_AWS_PROFILE")

print(f"Secret ID: {secret_id}")
print(f"AWS Profile: {aws_profile}")

if not secret_id:
    print("PULLDB_COORDINATION_SECRET not set")
    sys.exit(1)

try:
    resolver = CredentialResolver(aws_profile)
    creds = resolver.resolve(secret_id)
    print(f"Resolved credentials for host: {creds.host}, user: {creds.username}")
    
    conn = mysql.connector.connect(
        host=creds.host,
        user=creds.username,
        password=creds.password,
        database="pulldb"
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM jobs ORDER BY submitted_at DESC LIMIT 5")
    rows = cursor.fetchall()
    print(f"Found {len(rows)} jobs:")
    for row in rows:
        print(f"  ID: {row['id']}, Status: {row['status']}, Target: {row['target']}")
        if row['error_detail']:
            print(f"    Error: {row['error_detail']}")
        
    cursor.close()
    conn.close()

except Exception as e:
    print(f"Failed: {e}")
    sys.exit(1)
