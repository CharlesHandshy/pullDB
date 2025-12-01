# MySQL User Separation

> **EXTENDS**: engineering-dna/standards/database.md (credential patterns)

---

## Overview

pullDB uses service-specific MySQL users with least-privilege access:
passwords for the service by host can be found in aws secret manager profile pr-dev:

| User | Service | Access Level |
|------|---------|--------------|
| `pulldb_api` | API Service | Job queue read/write (coordination DB only) |
| `pulldb_worker` | Worker Service | Job processing (coordination DB only) |
| `pulldb_loader` | myloader | Full access to target databases |

---

## Secret Structure

Each user has a dedicated AWS Secrets Manager secret:
Use profile pr-dev for secrets access to passwords by host:

| Secret Path | Contents | Service |
|-------------|----------|---------|
| `/pulldb/mysql/api` | `{"host": "...", "password": "..."}` | API |
| `/pulldb/mysql/worker` | `{"host": "...", "password": "..."}` | Worker |
| `/pulldb/mysql/loader` | `{"host": "...", "password": "..."}` | myloader |

### Username Resolution

Usernames come from environment variables, NOT secrets:

```bash
# API Service environment
PULLDB_API_MYSQL_USER=pulldb_api

# Worker Service environment  
PULLDB_WORKER_MYSQL_USER=pulldb_worker

# myloader (set by worker before subprocess)
PULLDB_LOADER_MYSQL_USER=pulldb_loader
```

### Rationale

1. **Secrets contain only host + password** - Reduces secret rotation complexity
2. **Usernames in environment** - Allows same secret structure across environments
3. **Service identity explicit** - Clear which service is connecting

---

## Privilege Grants

### pulldb_api (API Service)

```sql
-- Coordination database only
GRANT SELECT, INSERT, UPDATE ON pulldb_service.jobs TO 'pulldb_api'@'%';
GRANT SELECT, INSERT ON pulldb_service.job_events TO 'pulldb_api'@'%';
GRANT SELECT ON pulldb_service.auth_users TO 'pulldb_api'@'%';
GRANT SELECT ON pulldb_service.db_hosts TO 'pulldb_api'@'%';
GRANT SELECT ON pulldb_service.settings TO 'pulldb_api'@'%';

-- Explicit denial: Cannot access target databases
-- (No grants on other databases)
```

### pulldb_worker (Worker Service)

```sql
-- Coordination database
GRANT SELECT, UPDATE ON pulldb_service.jobs TO 'pulldb_worker'@'%';
GRANT SELECT, INSERT ON pulldb_service.job_events TO 'pulldb_worker'@'%';
GRANT SELECT ON pulldb_service.db_hosts TO 'pulldb_worker'@'%';
GRANT SELECT ON pulldb_service.settings TO 'pulldb_worker'@'%';

-- Cannot create jobs (API only)
-- Cannot modify users or hosts
```

### pulldb_loader (myloader)

```sql
-- Target database host (not coordination DB)
-- Granted per-database as needed, OR:
GRANT ALL PRIVILEGES ON *.* TO 'pulldb_loader'@'%';

-- Note: pulldb_loader connects to TARGET hosts, not coordination DB
-- Each target host has its own pulldb_loader credentials
```

---

## Credential Resolution

```python
from pulldb.infra.secrets import CredentialResolver

class ServiceCredentialResolver:
    """Resolve credentials for specific pullDB services."""
    
    SERVICE_SECRETS = {
        "api": "/pulldb/mysql/api",
        "worker": "/pulldb/mysql/worker",
        "loader": "/pulldb/mysql/loader",
    }
    
    SERVICE_USER_VARS = {
        "api": "PULLDB_API_MYSQL_USER",
        "worker": "PULLDB_WORKER_MYSQL_USER",
        "loader": "PULLDB_LOADER_MYSQL_USER",
    }
    
    def resolve(self, service: str) -> MySQLCredentials:
        """Resolve MySQL credentials for a specific service.
        
        Args:
            service: One of 'api', 'worker', 'loader'
            
        Returns:
            MySQLCredentials with host, username, password
            
        Raises:
            CredentialError: If secret or env var missing
        """
        secret_path = self.SERVICE_SECRETS[service]
        user_var = self.SERVICE_USER_VARS[service]
        
        # Get username from environment
        username = os.environ.get(user_var)
        if not username:
            raise CredentialError(
                f"Environment variable {user_var} not set. "
                f"Required for {service} service MySQL access."
            )
        
        # Get host + password from secret
        secret = self.secrets_client.get_secret(secret_path)
        
        return MySQLCredentials(
            host=secret["host"],
            username=username,
            password=secret["password"],
            port=int(os.environ.get("PULLDB_MYSQL_PORT", 3306)),
            database=os.environ.get("PULLDB_MYSQL_DATABASE", "pulldb_service"),
        )
```

---

## Cross-Host Credential Resolution

For myloader, credentials are per-target-host (from `db_hosts.credential_ref`):

```python
def resolve_loader_credentials(host: DBHost) -> MySQLCredentials:
    """Resolve myloader credentials for a specific target host.
    
    The credential_ref in db_hosts points to a host-specific secret
    containing the connection details for that host.
    
    Args:
        host: DBHost record with credential_ref
        
    Returns:
        MySQLCredentials for the target host
    """
    secret = secrets_client.get_secret(host.credential_ref)
    
    return MySQLCredentials(
        host=secret["host"],
        username=secret.get("username", "pulldb_loader"),
        password=secret["password"],
        port=secret.get("port", 3306),
    )
```

---

## Secret Tags

All pullDB secrets MUST be tagged for IAM policy compliance:

```bash
# Required tag
aws secretsmanager tag-resource \
    --secret-id /pulldb/mysql/api \
    --tags Key=Service,Value=pulldb
```

The IAM policy uses tag-based access control:

```json
{
  "Condition": {
    "StringEquals": {
      "secretsmanager:ResourceTag/Service": "pulldb"
    }
  }
}
```

---

## User Creation SQL

```sql
-- Create service users (run on coordination DB host)
CREATE USER 'pulldb_api'@'%' IDENTIFIED BY '<password>';
CREATE USER 'pulldb_worker'@'%' IDENTIFIED BY '<password>';

-- Create loader user (run on each target DB host)
CREATE USER 'pulldb_loader'@'%' IDENTIFIED BY '<password>';

-- Apply grants as documented above
```

---

## Related

- [engineering-dna/standards/database.md](../../engineering-dna/standards/database.md) - Base credential patterns
- [engineering-dna/standards/aws.md](../../engineering-dna/standards/aws.md) - Secrets Manager patterns
- [docs/KNOWLEDGE-POOL.md](../../docs/KNOWLEDGE-POOL.md) - Secret paths and account IDs
- [docs/mysql-schema.md](../../docs/mysql-schema.md) - Schema and table definitions
