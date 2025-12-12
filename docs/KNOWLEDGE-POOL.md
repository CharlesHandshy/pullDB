# pullDB Knowledge Pool (condensed facts)

[← Back to Documentation Index](START-HERE.md)

Purpose: a single-source, trimmed knowledge base used by agents and maintainers. This file contains only the facts required for current operations. It is intentionally concise and indexed for fast lookup.

**Related:** [Deployment](deployment.md) · [policies/](policies/) · [terraform/](terraform/)

Last updated: 2025-12-12
Current version: v0.0.8
Phases complete: 0-4

---

## Index (categories)
- **Authentication & Sessions** (NEW - Phase 4)
- **RBAC Permission Matrix** (NEW - Phase 4)
- **Simulation Framework** (NEW - Phase 4)
- CLI Architecture & Scope
- Web UI Layout Architecture
- Web UI Style Guide
- Web UI HCA Architecture (NEW)
- S3 Multi-Location Configuration (v0.0.7)
- **Phase 4 Schema Tables** (NEW)
- Accounts & ARNs
- S3 buckets & paths
- IAM roles & policies
- Secrets Manager (secrets + policies)
- EC2 / instance profile
- Restore workflow facts
- System Paths & Service Locations
- Lessons Learned & Troubleshooting
- Quick commands & verification
- Purge candidates (files/docs to archive)
- Machine-readable index (JSON)
- IAM policy snippets (examples)
- Terraform examples (optional, small snippets)

---

## Authentication & Sessions (Phase 4)

pullDB implements a dual-mode authentication system supporting both development (trusted headers) and production (session-based) flows.

### Auth Modes

| Mode | Environment | How It Works |
|------|-------------|--------------|
| `trusted` | Development | `X-Pulldb-User` header trusted directly |
| `session` | Production | bcrypt password + session token cookie |
| `both` | Transition | Tries trusted header first, falls back to session |

**Configuration**: `PULLDB_AUTH_MODE` environment variable (default: `both`)

### Password Hashing

- **Algorithm**: bcrypt with work factor 12
- **Functions**: `hash_password()`, `verify_password()` in `pulldb/auth/password.py`
- **Storage**: `auth_credentials` table (user_id → hashed password)

### Session Management

- **Token**: 32-byte random hex string
- **Cookie**: `pulldb_session` (HttpOnly, Secure in prod, SameSite=Lax)
- **TTL**: 24 hours (configurable via `PULLDB_SESSION_TTL_HOURS`)
- **Storage**: `sessions` table with expiry timestamp

### Key Components

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/auth/password.py` | shared | bcrypt hash/verify utilities |
| `pulldb/auth/repository.py` | shared | AuthRepository for credential storage |
| `pulldb/api/auth.py` | pages | FastAPI auth middleware |
| `pulldb/web/features/auth/` | features | Login/logout routes |

### Quick Reference

```python
# Verify password
from pulldb.auth.password import verify_password
is_valid = verify_password(plain_text, hashed)

# Get current user (in route)
from pulldb.api.auth import get_current_user
user = await get_current_user(request, auth_repo)
```

---

## RBAC Permission Matrix (Phase 4)

Role-Based Access Control with three roles: `USER`, `MANAGER`, `ADMIN`.

### Permission Matrix

| Action | USER | MANAGER | ADMIN |
|--------|------|---------|-------|
| View own jobs | ✅ | ✅ | ✅ |
| Submit own jobs | ✅ | ✅ | ✅ |
| Cancel own jobs | ✅ | ✅ | ✅ |
| View managed users' jobs | ❌ | ✅ | ✅ |
| Cancel managed users' jobs | ❌ | ✅ | ✅ |
| View all jobs | ❌ | ❌ | ✅ |
| Cancel any job | ❌ | ❌ | ✅ |
| Manage users | ❌ | ❌ | ✅ |
| Orphan cleanup | ❌ | ❌ | ✅ |
| System settings | ❌ | ❌ | ✅ |

### Manager Relationships

- Stored in `manager_user_relationship` table
- One manager can manage multiple users
- Users can have multiple managers (uncommon)
- Query: `SELECT user_id FROM manager_user_relationship WHERE manager_id = ?`

### Key Components

| File | Layer | Purpose |
|------|-------|---------|
| `pulldb/domain/permissions.py` | entities | `check_permission()`, `UserRole` enum |
| `pulldb/domain/models.py` | entities | `User.role` field |
| `pulldb/infra/mysql.py` | shared | `UserRepository.get_managed_users()` |

### Usage Pattern

```python
from pulldb.domain.permissions import check_permission, Permission

# Check if user can cancel a job
if not check_permission(current_user, Permission.CANCEL_JOB, job.user_id):
    raise PermissionDenied("Cannot cancel this job")
```

---

## Simulation Framework (Phase 4)

In-memory mock system for testing without external dependencies.

### Architecture

```
┌─────────────────────────────────────────────────────┐
│              pulldb/simulation/                     │
├─────────────────────────────────────────────────────┤
│ api/         │ FastAPI routes for scenario control  │
├──────────────┼──────────────────────────────────────┤
│ core/engine  │ SimulationEngine orchestration       │
│ core/bus     │ EventBus for component communication │
│ core/state   │ Global state management              │
│ core/runner  │ MockQueueRunner job processing       │
│ core/seed    │ Test data generation                 │
├──────────────┼──────────────────────────────────────┤
│ adapters/    │ Mock implementations                 │
│   mock_mysql │ In-memory Job/User/Host repos        │
│   mock_s3    │ Mock S3 client                       │
│   mock_exec  │ Mock command executor                │
└──────────────┴──────────────────────────────────────┘
```

### Mock Adapters

| Adapter | Replaces | Key Class |
|---------|----------|-----------|
| `mock_mysql.py` | `pulldb/infra/mysql.py` | `MockJobRepository`, `MockUserRepository` |
| `mock_s3.py` | `pulldb/infra/s3.py` | `MockS3Client` |
| `mock_exec.py` | `pulldb/infra/exec.py` | `MockCommandExecutor` |

### Usage

```python
# Import through package root (HCA compliant)
from pulldb.simulation import (
    MockJobRepository,
    MockUserRepository,
    SimulationEngine,
)

# Set up simulation
engine = SimulationEngine()
job_repo = MockJobRepository()
engine.register(job_repo)
```

### Chaos Scenarios

Available via `core/scenarios.py`:
- `DownloadFailure` - S3 download fails
- `RestoreTimeout` - myloader times out
- `DiskFull` - Disk capacity check fails
- `NetworkPartition` - Connection drops

---

## Web UI HCA Architecture (Phase 4)

The web package follows HCA internally for UI component organization.

### Layer Mapping

| HCA Layer | Web Directory | Contents |
|-----------|---------------|----------|
| **shared** | `web/shared/` | `layouts/`, `ui/`, `contracts/`, `utils/` |
| **entities** | `web/entities/` | `job/`, `user/`, `host/`, `database/` |
| **features** | `web/features/` | `auth/`, `dashboard/`, `jobs/`, `admin/`, `manager/`, `restore/` |
| **widgets** | `web/widgets/` | `sidebar/`, `job_table/`, `filter_bar/`, `stats_cards/` |
| **pages** | `web/pages/` | `admin/`, `dashboard/`, `error/` |

### Key Files

| File | Purpose |
|------|---------|
| `dependencies.py` | FastAPI dependency injection (templates, auth) |
| `router_registry.py` | Combines all feature routers |
| `exceptions.py` | Custom web exception types |

### Template Hierarchy

```
templates/
├── base.html           # Root layout (shared)
├── layouts/            # Page layouts (shared)
├── components/         # Reusable components (widgets)
├── pages/              # Full page templates
└── partials/           # HTMX partials (features)
```

---

## Phase 4 Schema Tables

New tables added in Phase 4 for authentication and RBAC.

| Migration | Table | Purpose |
|-----------|-------|---------|
| `070_auth_users_role.sql` | — | Adds `role` column to `auth_users` |
| `071_auth_credentials.sql` | `auth_credentials` | Bcrypt password hashes |
| `072_sessions.sql` | `sessions` | Session tokens with expiry |
| `072_password_reset.sql` | `password_reset_tokens` | Password reset flow |
| `073_manager_user_relationship.sql` | `manager_user_relationship` | Manager-to-user mapping |
| `074_audit_logs.sql` | `audit_logs` | Security audit trail |

### Table: auth_credentials

```sql
CREATE TABLE auth_credentials (
    user_id INT PRIMARY KEY,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES auth_users(id)
);
```

### Table: sessions

```sql
CREATE TABLE sessions (
    token VARCHAR(64) PRIMARY KEY,
    user_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES auth_users(id)
);
```

### Table: manager_user_relationship

```sql
CREATE TABLE manager_user_relationship (
    manager_id INT NOT NULL,
    user_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (manager_id, user_id),
    FOREIGN KEY (manager_id) REFERENCES auth_users(id),
    FOREIGN KEY (user_id) REFERENCES auth_users(id)
);
```

---

## CLI Architecture & Scope

**Core Principle**: CLIs are thin interface clients to the server applications. All work is performed by the Worker service.

### pulldb CLI (User-Facing)
- **Scope**: Limited to operations from the user's own point of view
- **Target users**: Developers restoring databases for their own work
- **Allowed operations**:
  - ✅ Submit restore jobs (`pulldb restore`)
  - ✅ View status of own jobs (`pulldb status`)
  - ✅ Cancel own jobs (`pulldb cancel`)
  - ✅ View job history (`pulldb history`)
  - ✅ View job events/logs (`pulldb events`)
- **NOT allowed** (affects other users' work):
  - ❌ Orphan database reports
  - ❌ Deleting unaligned databases
  - ❌ Global cleanup operations
  - ❌ System-wide administration

### pulldb-admin CLI (Admin-Facing)
- **Scope**: Administrative operations affecting the system as a whole
- **Target users**: System administrators and operators
- **Operations**:
  - Orphan database reports and cleanup
  - Scheduled staging cleanup
  - Log pruning
  - Host management
  - System-wide monitoring

### Architectural Flow
```
User CLI (pulldb)     → API Service → Worker Service
Admin CLI (pulldb-admin) → API Service → Worker Service
```

Both CLIs are thin clients that:
1. Accept user input
2. Send commands to the API
3. Display results

The Worker performs all actual operations (database drops, S3 downloads, restores, etc.).

---

## Web UI Layout Architecture

**Full documentation**: [design/web-layout.md](design/web-layout.md)

### Layout Structure
```
┌───────────────────────────────────────────────────────────────────┐
│3│               │          PAGE HEADER BAR                        │
│p│  [Video Logo] │ Page Title    │ Subtitle │          [Login Info]│
│x├─────┐───────────────────────────────────────────────────────────┤
│ │SIDE │                    WORK AREA                              │
│ │BAR  │                  (content-body)                           │
│ │HOVER│               Scrolls independently                       │
│ │     ├───────────────────────────────────────────────────────────┤
│ │     │ © 2025 pullDB • v0.0.8    │    Service Titan/Field Routes │
└───────┴───────────────────────────────────────────────────────────┘
```

### Key Components
- **3px Strip**: Fixed left edge, gradient accent, full viewport height
- **Header**: Full width, video logo + title/subtitle + login info
- **Sidebar**: 12px invisible trigger zone, expands to 220px on hover, overlays content
- **Work Area**: Scrollable content area, flex child of app-body
- **Footer**: Two rows - copyright/version + branding

### Template Blocks
```jinja
{% block header_title %}Page Title{% endblock %}
{% block header_subtitle %}<p class="page-subtitle">Description</p>{% endblock %}
{% block header_actions %}<!-- Buttons/controls -->{% endblock %}
{% block content %}<!-- Main page content -->{% endblock %}
```

### Static Assets
- Logo video: `pulldb/images/pullDB_logo.mp4` → `/static/images/pullDB_logo.mp4`
- Brand logos: `servicetitan-logo.svg`, `fieldroutes-logo.svg`

---

## Web UI Style Guide (NEW)

**Full documentation**: [STYLE-GUIDE.md](STYLE-GUIDE.md)

### Design Philosophy
pullDB is an **internal operations tool**. UI priorities:
1. **Clarity over Cleverness** - Fast, accurate information
2. **Efficiency over Aesthetics** - Minimal clicks for power users
3. **Consistency over Creativity** - Same patterns everywhere

### UX Laws Applied
- **Doherty Threshold**: All transitions < 400ms
- **Hick's Law**: Max 4 stat cards, 7±2 nav items per section
- **Fitts's Law**: Minimum 32px button targets
- **Von Restorff Effect**: Status badges use distinct colors

### Color Quick Reference
| Status | Background | Text |
|--------|------------|------|
| Queued | `gray-100` | `gray-700` |
| Running | `primary-100` | `primary-700` |
| Complete | `success-100` | `success-700` |
| Failed | `danger-100` | `danger-700` |
| Canceled | `warning-100` | `warning-700` |

### Key CSS Tokens
```css
/* Primary brand */
--primary-500: #3b82f6;
--primary-600: #2563eb;

/* Spacing (4px scale) */
--space-4: 1rem;     /* Standard padding */
--space-6: 1.5rem;   /* Card padding */

/* Border radius */
--radius-md: 0.5rem; /* Buttons */
--radius-xl: 1rem;   /* Cards */
```

### Canonical Component Patterns
1. **Stat Card**: Icon (48px) + value + label
2. **Form Card**: Gradient header + icon + form body
3. **Status Badge**: Dot (animated for running) + label
4. **Table**: Uppercase headers, hover rows
5. **Empty State**: Icon + title + description + action

### File Locations
- Base styles: `pulldb/web/templates/base.html` (2100+ lines)
- Component styles: Inline per template (refactor planned)
- Static assets: `pulldb/images/` → `/static/images/`

---

## S3 Multi-Location Configuration (v0.0.7)

As of v0.0.7, pullDB supports multiple S3 backup locations configured via environment variable.

**Configuration Format**:
```bash
PULLDB_S3_BACKUP_LOCATIONS='[
  {"name": "staging", "bucket_path": "s3://pestroutesrdsdbs/daily/stg/", "profile": "pr-staging"},
  {"name": "prod", "bucket_path": "s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/", "profile": "pr-prod"}
]'
```

**Location Fields**:
- `name`: Human-readable identifier (used for filtering via `s3env=` option)
- `bucket_path`: Full S3 path including bucket and prefix
- `profile`: AWS profile name for cross-account access

**Usage**:
- `pulldb restore customer=acme` - Searches all configured locations
- `pulldb restore customer=acme s3env=prod` - Searches only locations with "prod" in name
- `pulldb search customer=acme` - Lists backups from all locations
- `pulldb search customer=acme s3env=staging` - Lists backups from staging only

**Worker Behavior**:
The worker filters locations based on job options:
```python
if env and env.lower() not in location.name.lower():
    continue  # Skip non-matching locations
```

---

## Accounts & ARNs
- Development account ID: 345321506926
- Staging account ID: 333204494849
- Production account ID: 448509429610

## S3 buckets & paths
- Staging backups bucket: `arn:aws:s3:::pestroutesrdsdbs`
  - Staging path: `s3://pestroutesrdsdbs/daily/stg/`
  - Contains both newer and older mydumper formats
- Production backups bucket: `arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3`
  - Production path: `s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/`

## IAM roles & policies (canonical)
- Dev EC2 role: `arn:aws:iam::345321506926:role/pulldb-ec2-service-role`
  - Expected attached policies (minimum runtime):
    - `pulldb-secrets-manager-access` (GetSecretValue, DescribeSecret, kms:Decrypt)
    - `pulldb-staging-s3-read` (s3:ListBucket, s3:GetObject, s3:HeadObject) — staging access
    - `pulldb-cross-account-assume-role` (sts:AssumeRole for production/staging cross-account roles) — optional
- Staging cross-account role (optional): `arn:aws:iam::333204494849:role/pulldb-cross-account-readonly`
- Production cross-account role (recommended for prod): `arn:aws:iam::448509429610:role/pulldb-cross-account-readonly`

## Secrets Manager (canonical secrets)

**MySQL User Separation (December 2025)**:
- pullDB now uses service-specific MySQL users with least-privilege access:
  - `pulldb_api` - API service (job queue read/write)
  - `pulldb_worker` - Worker service (job processing)
  - `pulldb_loader` - myloader restore operations (target database access)

- **Secrets** (one per user):
  - `/pulldb/mysql/api` - API service credentials
  - `/pulldb/mysql/worker` - Worker service credentials
  - `/pulldb/mysql/loader` - Loader credentials for target hosts
  - `/pulldb/mysql/coordination-db` - Coordination database credentials
  - `/pulldb/mysql/localhost-test` - Local testing credentials

- Secrets live in development account (345321506926) only

- **Required Tags** (for IAM policy compliance):
  - All `/pulldb/*` secrets MUST be tagged with `Service=pulldb`
  - The IAM policy `pulldb-secrets-manager-access` uses `secretsmanager:ResourceTag/Service` condition
  - When creating new secrets, always add: `--tags Key=Service,Value=pulldb`
  - Example: `aws secretsmanager tag-resource --secret-id /pulldb/mysql/NEW_SECRET --tags Key=Service,Value=pulldb`

- **Secret Structure** (host + password only):
  - `username` comes from service-specific environment variables:
    - `PULLDB_API_MYSQL_USER` (required for API service)
    - `PULLDB_WORKER_MYSQL_USER` (required for Worker service)
  - `PULLDB_MYSQL_PORT` (optional, default 3306)
  - `PULLDB_MYSQL_DATABASE` (default: `pulldb_service`)

- **Database**: `pulldb_service` (renamed from `pulldb`)
- **Schema path**: `schema/pulldb_service/`

- Runtime policy (`pulldb-secrets-manager-access`) should grant:
  - `secretsmanager:GetSecretValue` and `secretsmanager:DescribeSecret` on `arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/mysql/*`
  - `secretsmanager:ListSecrets` with `Resource: "*"` (no condition - AWS does not support condition keys for ListSecrets per service authorization reference)
  - `kms:Decrypt` (conditioned to Secrets Manager usage)
  - **Note**: ResourceTag conditions do NOT work for `ListSecrets` - AWS ignores them. Use `--filters` client-side instead.

## Machine-readable index (JSON)
The following JSON block is a compact, program-friendly index of the core artifacts referenced in this file. Use it as a single-source map for automation or verification scripts.

```json
{
  "accounts": {
    "development": "345321506926",
    "staging": "333204494849",
    "production": "448509429610"
  },
  "s3": {
    "staging_bucket": "pestroutesrdsdbs",
    "staging_prefix": "daily/stg/",
    "production_bucket": "pestroutes-rds-backup-prod-vpc-us-east-1-s3",
    "production_prefix": "daily/prod/"
  },
  "iam": {
    "dev_ec2_role": "arn:aws:iam::345321506926:role/pulldb-ec2-service-role",
    "staging_cross_account_role": "arn:aws:iam::333204494849:role/pulldb-cross-account-readonly",
    "production_cross_account_role": "arn:aws:iam::448509429610:role/pulldb-cross-account-readonly",
    "instance_profile": "pulldb-instance-profile"
  },
  "secrets": {
    "api": "/pulldb/mysql/api",
    "worker": "/pulldb/mysql/worker",
    "loader": "/pulldb/mysql/loader"
  },
  "schema": {
    "canonical_doc": "docs/mysql-schema.md",
    "database": "pulldb_service",
    "schema_dir": "schema/pulldb_service/",
    "hosts_table": "db_hosts"
  },
  "mysql_users": {
    "api": "pulldb_api",
    "worker": "pulldb_worker",
    "loader": "pulldb_loader"
  }
}
```

This JSON is intentionally compact. If you'd prefer a separate `docs/KNOWLEDGE-POOL.json` file, I can add it and keep it in sync.

## EC2 / Instance Profile
- Instance profile name: `pulldb-instance-profile`
- Instance profile must contain the role `pulldb-ec2-service-role` and be attached to the EC2 instance running API + Worker
- IMDSv2 is used for token-based metadata retrieval in verification steps

### Quick IAM policy snippets (safe examples)
These are minimal, least-privilege examples suitable for transforming into full policies or templates.

- staging S3 read policy (attach to role used by dev instances for staging bucket):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::pestroutesrdsdbs"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:HeadObject"],
      "Resource": "arn:aws:s3:::pestroutesrdsdbs/daily/stg/*"
    }
  ]
}
```

- production cross-account assume-role trust (to be created in production account):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::345321506926:role/pulldb-ec2-service-role"},
      "Action": "sts:AssumeRole",
      "Condition": {"StringEquals": {"sts:ExternalId": "<EXTERNAL_ID_HERE>"}}
    }
  ]
}
```

Replace `<EXTERNAL_ID_HERE>` with a strong, unique external ID provided by the dev account when creating the trust relationship.

### Terraform hint (small snippet)
If you use Terraform for IAM, this minimal snippet demonstrates creating an assume-role in the production account:

```hcl
resource "aws_iam_role" "pulldb_cross_account" {
  name = "pulldb-cross-account-readonly"
  assume_role_policy = file("./pulldb-cross-account-trust.json")
}
```

This file should be created and applied in the production account only. Keep secrets/keys out of Terraform state.

## Restore workflow facts (operational)
- Staging database naming: `{target}_{job_id_first_12_chars}` (max lengths enforced)
- S3 preflight: require `*-schema-create.sql.{gz,zst}` exists and `free_space >= tar_size * 1.8` before extraction
- Post-restore SQL: executed from `customers_after_sql/` or `qa_template_after_sql/` in lexicographic order
- Atomic rename via stored procedure: `pulldb_atomic_rename` / `pulldb_atomic_rename_preview` exists and is versioned

## Database Schema (Quick Reference)
- **Canonical Source**: `docs/mysql-schema.md` (Read this for full column definitions)
- **Hosts Table**: `db_hosts` (NOT `hosts`) - contains registered database servers
- **Jobs Table**: `jobs` - tracks restore requests and status
- **Users Table**: `auth_users` - tracks authorized users
- **Settings Table**: `settings` - dynamic configuration (key/value)

## Test Configuration (Local Development)
- **Test MySQL credentials**: Set environment variables to use local MySQL instead of AWS Secrets Manager:
  - `PULLDB_TEST_MYSQL_HOST=localhost`
  - `PULLDB_TEST_MYSQL_USER=pulldb_test`
  - `PULLDB_TEST_MYSQL_PASSWORD=test123` (or empty string for auth_socket users)
- **Auto-database setup**: The test suite automatically creates the `pulldb` database if it doesn't exist and drops it after tests if it was created by the test suite
- **Schema location**: `schema/pulldb/*.sql` (files applied in lexicographic order)
- **Empty password handling**: Empty passwords (`""`) are valid - the fixture checks `password is not None` not truthiness

## Local Environment & Binaries
- myloader binaries location: `/opt/pulldb.service.service/bin/` (installed)
  - Source location: `pulldb/binaries/`
  - Available versions: `myloader-0.9.5`, `myloader-0.19.3-3`

## System Paths & Service Locations
- **Installation Root**: `/opt/pulldb.service`
- **Virtual Environment**: `/opt/pulldb.service.service/venv`
- **Logs**: `/opt/pulldb.service.service/logs`
- **Work Directory**: `/opt/pulldb.service.service/work`
- **Systemd Units**:
  - API Service: `/etc/systemd/system/pulldb-api.service`
  - Worker Service: `/etc/systemd/system/pulldb-worker.service`
- **Binaries**:
  - `pulldb` CLI: `/opt/pulldb.service.service/venv/bin/pulldb`
  - `myloader`: `/opt/pulldb.service.service/bin/myloader` (symlinked or direct)

## Lessons Learned & Troubleshooting
- **Service User Identity**: Services (`pulldb-api`, `pulldb-worker`) MUST run as the `pulldb` system user. Running as `root` or a developer user causes permission issues with logs and work directories.
- **S3 Backup Structure**: Some S3 tarballs contain a top-level directory (e.g., `customer/metadata`) while others are flat. `myloader` fails if pointed at the root of a nested backup. The worker now automatically resolves the correct path by searching for the `metadata` file within the extracted archive.
- **Progress Reporting**: `myloader` does not natively report percentage progress. We estimate progress by tracking S3 download bytes vs total size.
- **AWS Profile Scoping**: `PULLDB_AWS_PROFILE` controls the default boto3 session (Secrets Manager, SSM). `PULLDB_S3_AWS_PROFILE` controls the S3 client.
  - **Issue**: Setting `PULLDB_AWS_PROFILE=pr-prod` breaks Secrets Manager access because the production role cannot read dev secrets.
  - **Fix**: Use `PULLDB_S3_AWS_PROFILE=pr-prod` for S3 access, and leave `PULLDB_AWS_PROFILE` unset (to use instance profile) or set to `pr-dev`.
- **Logical Hostnames**: The `hostname` column in `db_hosts` is a logical alias (e.g., `dev-db-01`), NOT the FQDN. The actual connection FQDN is stored in the AWS Secret referenced by `credential_ref`. This allows CLI users to use short names while the system connects securely.
- **Testing Restriction**: Use `dev-db-01` or `localhost` for testing purposes.
- **MySQL Root Socket Auth**: On localhost, root MySQL user uses `auth_socket` plugin (no password needed when connecting via Unix socket). Scripts running as root MUST use socket auth, not TCP with password.
- **Migration Script Auth** (Nov 2025 fix):
  - **Problem**: `pulldb-migrate` failed when run as root because AWS credentials are in user-specific `~/.aws/credentials` (not accessible to root).
  - **Solution**: For localhost, use Unix socket auth instead of TCP with AWS credentials.
  - **URL Format**: dbmate socket URL is `mysql://user:@/database?socket=/path/to/socket` (empty password, `@/` separator).
  - **Socket Locations**: `/var/run/mysqld/mysqld.sock` (Debian/Ubuntu), `/tmp/mysql.sock` (macOS), `/var/lib/mysql/mysql.sock` (RHEL).
  - **Priority**: DATABASE_URL (override) → socket auth (localhost) → AWS Secrets Manager (remote/fallback).
- **Migration Baseline**: When installing on an existing database, use `pulldb-migrate baseline` to mark all migrations as applied without running them. This prevents migration errors from schema drift.

### Phase 2 Lessons (Nov 2025)

- **AWS Region Configuration**:
  - **Problem**: boto3 failed with "You must specify a region" when running outside AWS.
  - **Root Cause**: CredentialResolver didn't pass region to boto3.Session().
  - **Fix**: Added `aws_region` parameter with fallback chain: explicit param → `PULLDB_AWS_REGION` → `AWS_DEFAULT_REGION` → `"us-east-1"`.
  - **Recommendation**: Always set `AWS_DEFAULT_REGION` in `.env` files for non-EC2 environments.

- **Settings Sync (db ↔ .env)**:
  - **Problem**: Settings changes required editing both database AND .env file manually.
  - **Solution**: Implemented `pulldb-admin settings pull/push/diff` commands.
  - **Commands**: `pull` (db→env), `push` (env→db), `diff` (compare both).
  - **File Detection**: Auto-finds `/opt/pulldb.service/.env` (installed) or repo root `.env` (dev).

- **dpkg Upgrade Does NOT Run Migrations**:
  - **Problem**: Users expected `dpkg -i pulldb_*.deb` to auto-update schema.
  - **Reality**: dpkg only upgrades files; migrations require separate step.
  - **Fix**: Created `packaging/INSTALL-UPGRADE.md` with explicit post-install steps.
  - **Required Steps**: After dpkg install, run `sudo /opt/pulldb.service/scripts/pulldb-migrate.sh migrate`.

- **CLI dotenv Auto-Loading**:
  - **Problem**: CLI tools required manual `source .env` before use.
  - **Fix**: Added `load_dotenv()` at module import in `admin.py` and `main.py`.
  - **Behavior**: Auto-loads `.env` from working directory or install paths.

## myloader 0.19 Metadata Compatibility
- **Source**: `src/myloader/myloader_process.c` (GitHub)
- **[config] Section**: Keys here are treated as command-line arguments (prepended with `--`).
  - Useful for: `rows`, `threads`, `database`, `compress-protocol`, `local-infile`.
- **[myloader_session_variables] Section**: Sets MySQL session variables.
  - Critical for restores: `sql_log_bin=0`, `foreign_key_checks=0`, `time_zone='+00:00'`.
- **Table Sections**: `[database.table]` (quoted).
  - `real_table_name`: Allows renaming.
  - `rows`: Critical for progress bar accuracy.
  - `is_view`, `is_sequence`: Object type flags.
- **Replication**: `[source]`, `[master]`, `[replication...]` sections for GTID/binlog setup.

## Quick commands & verification
- Verify caller identity (from EC2 with instance profile):
  - `aws sts get-caller-identity`
- List staging backups (from instance with role attached):
  - `aws s3 ls s3://pestroutesrdsdbs/daily/stg/`
- Check secret: `aws secretsmanager get-secret-value --secret-id /pulldb/mysql/coordination-db`
- Verify instance profile attached to EC2:
  - IMDSv2 token + metadata: `TOKEN=$(curl -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds:21600' -s)` then `curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/ -s`

## Purge candidates (docs/files to archive)
*Criteria*: documents that are obsolete, duplicated, or superseded by `docs/AWS-SETUP.md` and `docs/KNOWLEDGE-POOL.md`.

- `docs/aws-quickstart.md` — superseded and removed
- `docs/aws-ec2-deployment-setup.md` — superseded (content consolidated)
- `docs/aws-doc-consolidation.md` — consolidation metadata (archive)
- `docs/aws-setup.md.OBSOLETE` and similar `*.OBSOLETE` files — archive or delete
- Any duplicate copies of the same topic (see file_search duplicates list)

---

## Web UI Design Patterns (December 2025)

### Hover-Reveal Sidebar Pattern
The pullDB web interface uses a **hover-reveal sidebar** pattern for maximum content area:

**Core Behavior**:
- Sidebar hidden by default at ALL screen sizes (`transform: translateX(-100%)`)
- Content area uses 100% width (`margin-left: 0`)
- Sidebar floats over content as overlay when triggered
- Opens via: left edge hover (12px trigger zone) OR menu button tap
- Closes via: mouse leave (with delay) OR backdrop click

**CSS Architecture**:
```css
.sidebar {
    position: fixed;
    transform: translateX(-100%);  /* Hidden by default */
    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    z-index: 200;
}
.sidebar.open {
    transform: translateX(0);
    box-shadow: 4px 0 20px rgba(0, 0, 0, 0.15);
}
.sidebar-trigger {  /* Invisible left edge zone */
    position: fixed; left: 0; width: 12px; height: 100%; z-index: 100;
}
.sidebar-backdrop {  /* Dark overlay when open */
    position: fixed; inset: 0; background: rgba(0, 0, 0, 0.3); z-index: 150;
}
```

**JavaScript Timing**:
- Open delay: 150ms (prevents accidental triggers)
- Close delay: 200ms (prevents flickering)
- Menu button: immediate (no delay needed)

### Device Detection (Touch vs Mouse)
Use CSS media queries to detect input capabilities:

**Media Queries**:
```css
/* Mouse/trackpad devices: hide menu button, use edge hover */
@media (hover: hover) and (pointer: fine) {
    .menu-btn { display: none; }
    .sidebar-trigger { display: block; }
}

/* Touch devices: show menu button, hide edge trigger */
@media (hover: none), (pointer: coarse) {
    .menu-btn { display: flex; }
    .sidebar-trigger { display: none; }
}
```

**Values**:
- `hover: hover` - Device supports true hover (mouse/trackpad)
- `hover: none` - No hover support (touch devices)
- `pointer: fine` - Precise pointer (mouse)
- `pointer: coarse` - Imprecise pointer (finger/touch)

**JavaScript Alternative**:
```javascript
// Check if device has hover capability
const hasHover = window.matchMedia('(hover: hover)').matches;
const hasFinePointer = window.matchMedia('(pointer: fine)').matches;
const isTouchDevice = navigator.maxTouchPoints > 0;
```

### Responsive Table Layout Pattern
For full-viewport data tables (Jobs page):

**Key Classes**:
- `.main-content.full-height-page` - prevents scroll on container
- `.layout-fullheight` - flex column, `min-height: 0` for shrinking
- `.layout-body` - `flex: 1` fills remaining space

**Critical CSS**:
```css
.main-content {
    height: 100vh;
    max-height: 100vh;
    display: flex;
    flex-direction: column;
}
.main-content.full-height-page {
    overflow: hidden;  /* Children manage scroll */
}
.main-content.full-height-page > div {
    flex: 1;
    min-height: 0;  /* Allow shrinking */
}
```

### VirtualScroller (3-Window Pattern)
For large datasets with smooth scrolling:

**Architecture**:
- Renders 3 "windows" of rows (before, visible, after)
- Each window = viewport height worth of rows
- Scroll position determines which rows to render
- Placeholder divs maintain scroll height

**Key Parameters**:
- `rowHeight`: Fixed height per row (required)
- `overscan`: Extra rows above/below viewport (default: 10)
- `totalRows`: Total dataset size
- `visibleRange`: Currently rendered row indices

---

## How to use this file
- For quick lookups, search this file for the keyword (ARN, secret name, bucket name)
- For step-by-step actions, follow `docs/AWS-SETUP.md` (canonical), and use this KNOWLEDGE-POOL for fast facts
- When purging, move candidate files into `docs/archived/` with a short summary commit message (include `Purge:` tag)

---

If you'd like, I will:
- create `docs/archived/` and move purge candidates there (commit), or
- generate a machine-readable index (JSON) for quick programmatic lookups, or
- expand any category with deeper extracted facts (e.g., full IAM policy JSON snippets)

---

[← Back to Documentation Index](START-HERE.md) · [Deployment →](deployment.md)
