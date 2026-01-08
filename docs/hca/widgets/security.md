# pullDB Security Model

> **Security architecture, authentication, authorization, and secrets management**
>
> This document covers the security design of pullDB including the MySQL user model,
> authentication modes, role-based access control (RBAC), and secrets handling.

## Table of Contents

- [Overview](#overview)
- [MySQL User Model](#mysql-user-model)
- [Authentication Modes](#authentication-modes)
- [Role-Based Access Control](#role-based-access-control)
- [Session Management](#session-management)
- [Secrets Management](#secrets-management)
- [Network Security](#network-security)
- [Operational Security](#operational-security)

---

## Overview

pullDB implements defense-in-depth with multiple security layers:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Security Layers                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Layer 1: Network Security                                    │    │
│  │ • Security Groups (VPC firewall)                            │    │
│  │ • TLS for external connections                              │    │
│  │ • VPC endpoints for AWS services                            │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Layer 2: Authentication                                      │    │
│  │ • Session-based (bcrypt passwords)                          │    │
│  │ • Trusted headers (internal CLI)                            │    │
│  │ • EC2 instance profiles (AWS)                               │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Layer 3: Authorization (RBAC)                               │    │
│  │ • USER: Own resources only                                  │    │
│  │ • MANAGER: Team resources                                   │    │
│  │ • ADMIN: Full access                                        │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Layer 4: Database Security                                   │    │
│  │ • Least-privilege MySQL users                               │    │
│  │ • Service-specific credentials                              │    │
│  │ • No shared passwords                                       │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## MySQL User Model

pullDB uses **three separate MySQL users** with least-privilege grants. This ensures each service component has only the permissions it needs.

### User Overview

| User | Service | Purpose | Secrets Path |
|------|---------|---------|--------------|
| `pulldb_api` | API, Web | Read/write job queue, user management | `/pulldb/mysql/api` |
| `pulldb_worker` | Worker | Process jobs, update status, emit events | `/pulldb/mysql/worker` |
| `pulldb_loader` | Worker (myloader) | Restore operations on target databases | `/pulldb/mysql/loader` |

### Permission Matrix

```sql
-- pulldb_api: API and Web services
GRANT SELECT, INSERT, UPDATE ON pulldb_service.jobs TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE ON pulldb_service.users TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT ON pulldb_service.job_events TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.sessions TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.hosts TO 'pulldb_api'@'localhost';
GRANT SELECT ON pulldb_service.settings TO 'pulldb_api'@'localhost';
-- NO: DELETE on jobs (audit trail)
-- NO: TRUNCATE, DROP (destructive)

-- pulldb_worker: Job processing
GRANT SELECT, UPDATE ON pulldb_service.jobs TO 'pulldb_worker'@'localhost';
GRANT INSERT ON pulldb_service.job_events TO 'pulldb_worker'@'localhost';
GRANT SELECT ON pulldb_service.hosts TO 'pulldb_worker'@'localhost';
GRANT SELECT ON pulldb_service.settings TO 'pulldb_worker'@'localhost';
-- NO: INSERT on jobs (only API submits)
-- NO: User table access (not needed)

-- pulldb_loader: Database restore operations (on TARGET hosts)
GRANT CREATE, DROP, ALTER, INDEX, INSERT, UPDATE, DELETE, SELECT,
      LOCK TABLES, TRIGGER, CREATE VIEW, CREATE ROUTINE, ALTER ROUTINE,
      REFERENCES, EVENT, EXECUTE, PROCESS
ON *.* TO 'pulldb_loader'@'%';
-- Broad privileges required for:
-- - myloader restore operations (data + schema)
-- - Stored procedure deployment (CREATE/ALTER ROUTINE, EXECUTE)
-- - Atomic database rename after restore
```

### Why Three Users?

| Benefit | Description |
|---------|-------------|
| **Blast Radius** | Compromised worker can't modify user accounts |
| **Audit Trail** | MySQL logs show which service performed each action |
| **Compliance** | Meets principle of least privilege requirements |
| **Defense in Depth** | Multiple credentials mean multiple keys to compromise |

### Configuration

Services identify themselves via environment variables:

```bash
# API Service (.env or systemd)
PULLDB_API_MYSQL_USER=pulldb_api

# Worker Service (.env or systemd)
PULLDB_WORKER_MYSQL_USER=pulldb_worker

# Loader is used automatically by worker for myloader operations
```

---

## Authentication Modes

pullDB supports three authentication modes, configured via `PULLDB_AUTH_MODE`:

### Trusted Mode (`trusted`)

Used for CLI access where users are already authenticated via SSH/sudo.

```
┌──────────────┐    SSH + sudo    ┌──────────────┐   X-Pulldb-User   ┌──────────────┐
│ User Machine │ ──────────────▶ │  CLI (pulldb)│ ────────────────▶ │   API        │
│              │                  │              │                    │              │
│ jsmith       │                  │ $USER=jsmith │                    │ Trusts header│
└──────────────┘                  └──────────────┘                    └──────────────┘
```

- CLI sends `X-Pulldb-User: <username>` header
- API trusts this header without password verification
- User identity derived from SSH/sudo login
- **Use case**: Internal CLI on trusted network

### Session Mode (`session`)

Used for web UI access with username/password authentication.

```
┌──────────────┐                  ┌──────────────┐   session_token   ┌──────────────┐
│   Browser    │ ──login form───▶│   Web UI     │ ────cookie──────▶ │   API        │
│              │                  │              │                    │              │
│ jsmith/pass  │                  │ bcrypt check │                    │ Verify token │
└──────────────┘                  └──────────────┘                    └──────────────┘
```

- User provides username and password
- Password verified against bcrypt hash in database
- Session token issued (32-byte random, SHA-256 hashed for storage)
- Cookie expires after `PULLDB_SESSION_TTL_HOURS` (default: 24)
- **Use case**: Web UI, external API access

### Both Mode (`both`) - Default

Accepts either authentication method. This is the default and recommended mode.

```bash
# In .env or systemd environment
PULLDB_AUTH_MODE=both
```

---

## Role-Based Access Control

### Roles

| Role | Level | Description |
|------|-------|-------------|
| `USER` | 1 | Standard user - own resources only |
| `MANAGER` | 2 | Team lead - view/cancel team jobs |
| `ADMIN` | 3 | Administrator - full system access |

### Permission Matrix

| Action | USER | MANAGER | ADMIN |
|--------|------|---------|-------|
| Submit own job | ✅ | ✅ | ✅ |
| View own jobs | ✅ | ✅ | ✅ |
| Cancel own job | ✅ | ✅ | ✅ |
| View team jobs | ❌ | ✅ | ✅ |
| Cancel team job | ❌ | ✅ | ✅ |
| View all jobs | ❌ | ❌ | ✅ |
| Cancel any job | ❌ | ❌ | ✅ |
| Manage users | ❌ | ❌ | ✅ |
| Manage hosts | ❌ | ❌ | ✅ |
| System settings | ❌ | ❌ | ✅ |
| View audit log | ❌ | ❌ | ✅ |

### Role Assignment

Roles are stored in the `users` table:

```sql
-- Assign manager role
UPDATE users SET role = 'MANAGER' WHERE username = 'teamlead';

-- Assign admin role
UPDATE users SET role = 'ADMIN' WHERE username = 'sysadmin';

-- Default role for new users
-- role = 'USER'
```

Or via CLI:

```bash
pulldb-admin users set-role teamlead MANAGER
pulldb-admin users set-role sysadmin ADMIN
```

---

## Session Management

### Session Token Lifecycle

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Login     │      │   Active    │      │   Expired   │
│             │─────▶│             │─────▶│             │
│ Generate    │      │ Validate    │      │ Cleanup     │
│ token       │      │ on request  │      │ background  │
└─────────────┘      └─────────────┘      └─────────────┘
```

### Token Properties

| Property | Value |
|----------|-------|
| Length | 32 bytes (64 hex characters) |
| Storage | SHA-256 hash (never store raw token) |
| TTL | 24 hours (configurable via `PULLDB_SESSION_TTL_HOURS`) |
| Cookie | `session_token`, HttpOnly, SameSite=Lax |

### Session Storage

```sql
CREATE TABLE sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    token_hash CHAR(64) NOT NULL,  -- SHA-256 of token
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    ip_address VARCHAR(45),        -- IPv4 or IPv6
    user_agent TEXT,
    UNIQUE KEY (token_hash),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

### Session Cleanup

Expired sessions are cleaned up automatically:
- Background task runs every hour
- Deletes sessions where `expires_at < NOW()`
- Manual cleanup: `pulldb-admin sessions cleanup`

---

## Secrets Management

### AWS Secrets Manager

pullDB stores credentials in AWS Secrets Manager, never in configuration files.

#### Secret Structure

Each secret contains a JSON object:

```json
{
  "password": "actual_password_here",
  "host": "localhost"
}
```

#### Secret Paths

| Path | Purpose |
|------|---------|
| `/pulldb/mysql/api` | API service MySQL credentials |
| `/pulldb/mysql/worker` | Worker service MySQL credentials |
| `/pulldb/mysql/loader` | myloader MySQL credentials |
| `/pulldb/mysql/coordination-db` | Coordination database (alias) |

#### Resolution

The `CredentialResolver` class handles secret resolution:

```python
from pulldb.infra.secrets import CredentialResolver

resolver = CredentialResolver()

# Resolve from Secrets Manager
creds = resolver.resolve('aws-secretsmanager:/pulldb/mysql/api')
print(f"Host: {creds.host}, Password: {creds.password}")
```

### Secrets Rotation

pullDB provides unified secret rotation via CLI and Web UI. Both use the same atomic 7-phase workflow.

#### CLI Rotation

```bash
# Rotate credentials for a host (by alias, hostname, or host_id)
pulldb-admin secrets rotate-host mydb

# With custom password length (default: 32)
pulldb-admin secrets rotate-host --length 48 mydb

# JSON output for scripting
pulldb-admin secrets rotate-host --json mydb

# Skip confirmation prompt
pulldb-admin secrets rotate-host --yes mydb
```

#### Web UI Rotation

Navigate to **Admin → Hosts → [Host Detail]** and click the **Quick Rotate** button. A modal displays real-time progress through all phases.

#### Rotation Phases

The rotation service performs these steps atomically:

1. **fetch_credentials** - Fetch current credentials from AWS Secrets Manager
2. **validate_current** - Verify current credentials work on MySQL
3. **generate_password** - Generate cryptographically secure password
4. **mysql_update** - Update MySQL user password (ALTER USER)
5. **verify_new_password** - Verify new password works on MySQL
6. **aws_update** - Update AWS Secrets Manager secret
7. **final_verify** - Round-trip verification (AWS → MySQL)

If MySQL update succeeds but AWS update fails, the service provides manual fix instructions to prevent credential desync.

#### Rotation Schedule

| Secret | Rotation Frequency | Notes |
|--------|-------------------|-------|
| API credentials | Quarterly | Low risk, internal only |
| Worker credentials | Quarterly | Low risk, internal only |
| Loader credentials | Monthly | Higher risk, accesses target DBs |

---

## Network Security

### Security Group Rules

See [AWS Setup Guide - Security Groups](../AWS-SETUP.md#a3-security-groups-configuration) for detailed rules.

#### Summary

| Service | Port | Source | Protocol |
|---------|------|--------|----------|
| Web UI | 8000 | VPC CIDR | TCP |
| REST API | 8080 | VPC CIDR | TCP |
| MySQL (coord) | 3306 | localhost | TCP |
| MySQL (target) | 3306 | pulldb-service SG | TCP |

### TLS Configuration

For production deployments, use a reverse proxy (nginx, ALB) for TLS termination:

```
┌──────────┐   HTTPS    ┌──────────┐   HTTP    ┌──────────────┐
│ Browser  │ ─────────▶ │  nginx   │ ────────▶│ pulldb-web   │
│          │   :443     │          │   :8000   │ (localhost)  │
└──────────┘            └──────────┘            └──────────────┘
```

### VPC Endpoints

Use VPC endpoints to keep AWS API traffic within AWS network:

| Service | Endpoint Type | Purpose |
|---------|--------------|---------|
| S3 | Gateway | Backup downloads |
| Secrets Manager | Interface | Credential resolution |
| STS | Interface | IAM role assumption |

---

## Operational Security

### Audit Logging

All security-relevant events are logged:

```sql
-- Sample audit entries
SELECT * FROM audit_log WHERE event_type IN (
    'user_login',
    'user_logout', 
    'password_change',
    'role_change',
    'job_submitted',
    'job_canceled',
    'admin_action'
);
```

### Log Retention

| Log Type | Retention | Location |
|----------|-----------|----------|
| Application logs | 30 days | `/var/log/pulldb/` |
| Audit log (DB) | 1 year | `pulldb_service.audit_log` |
| Access logs (nginx) | 90 days | `/var/log/nginx/` |

### Security Checklist

#### Deployment

- [ ] Security groups configured per A.3
- [ ] VPC endpoints created for S3, Secrets Manager
- [ ] TLS termination configured (nginx/ALB)
- [ ] Instance profile attached (no stored credentials)

#### Configuration

- [ ] `PULLDB_AUTH_MODE=both` (or `session` for web-only)
- [ ] `PULLDB_SESSION_TTL_HOURS` set appropriately
- [ ] MySQL users have least-privilege grants
- [ ] Secrets created with `Service=pulldb` tag

#### Monitoring

- [ ] Failed login alerts configured
- [ ] Unusual API activity alerts
- [ ] Secrets Manager access CloudTrail

---

## See Also

- [AWS Setup Guide](../AWS-SETUP.md) - Complete AWS configuration
- [Architecture](architecture.md) - System design overview
- [Auth Guide](../pages/auth-guide.md) - Authentication walkthrough
