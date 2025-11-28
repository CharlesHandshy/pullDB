import os
import mysql.connector
from dotenv import load_dotenv
from pulldb.infra.secrets import CredentialResolver

load_dotenv("/opt/pulldb.service/.env")
secret_id = os.getenv("PULLDB_COORDINATION_SECRET")
aws_profile = os.getenv("PULLDB_AWS_PROFILE")

resolver = CredentialResolver(aws_profile)
creds = resolver.resolve(secret_id)

try:
    # Try with default (likely C extension)
    conn = mysql.connector.connect(
        user=creds.username, password=creds.password, host=creds.host
    )
    cursor = conn.cursor()
    print(f"Default cursor type: {type(cursor)}")
    try:
        cursor.execute("SELECT 1; SELECT 2", multi=True)
        print("Default cursor supports multi=True")
    except TypeError as e:
        print(f"Default cursor failed with multi=True: {e}")
    conn.close()
except Exception as e:
    print(f"Default connection failed: {e}")

print("-" * 20)

try:
    # Try with use_pure=True
    conn = mysql.connector.connect(
        user=creds.username, password=creds.password, host=creds.host, use_pure=True
    )
    cursor = conn.cursor()
    print(f"Pure cursor type: {type(cursor)}")
    print(dir(cursor))
    # Check execute signature
    import inspect

    print(inspect.signature(cursor.execute))
    try:
        cursor.execute("SELECT 1; SELECT 2", multi=True)
        print("Pure cursor supports multi=True")
    except TypeError as e:
        print(f"Pure cursor failed with multi=True: {e}")
    try:
        print("Trying execute without multi=True...")
        ret = cursor.execute("SELECT 1; SELECT 2")
        print(f"Execute returned: {ret}")
        while True:
            print(f"Result: {cursor.fetchall()}")
            if not cursor.nextset():
                break
    except Exception as e:
        print(f"Execute failed without multi=True: {e}")
    conn.close()
except Exception as e:
    print(f"Pure connection failed: {e}")
