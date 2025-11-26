import os
import sys
from pulldb.infra.secrets import CredentialResolver

# Set env vars
os.environ["PULLDB_AWS_PROFILE"] = "pr-dev"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

resolver = CredentialResolver("pr-dev")

secret_id = "aws-secretsmanager:/pulldb/mysql/coordination-db"
print(f"Resolving {secret_id}...")

try:
    creds = resolver.resolve(secret_id)
    print(f"Username: {creds.username}")
    print(f"Password length: {len(creds.password)}")
    print(f"Host: {creds.host}")
except Exception as e:
    print(f"Failed: {e}")
