
import os
import sys
from dotenv import load_dotenv
from pulldb.infra.secrets import CredentialResolver

# Load env from /opt/pulldb/.env
load_dotenv("/opt/pulldb/.env")

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
    print(f"Successfully resolved credentials for host: {creds.host}, user: {creds.username}")
except Exception as e:
    print(f"Failed to resolve secret: {e}")
    sys.exit(1)
