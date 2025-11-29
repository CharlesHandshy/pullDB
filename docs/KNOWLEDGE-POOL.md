# pullDB Knowledge Pool (condensed facts)

Purpose: a single-source, trimmed knowledge base used by agents and maintainers. This file contains only the facts required for current operations (Nov 2025). It is intentionally concise and indexed for fast lookup.

Last updated: 2025-11-29
Current version: v0.0.7
Phases complete: 0-3

---

## Index (categories)
- CLI Architecture & Scope
- S3 Multi-Location Configuration (v0.0.7)
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

## How to use this file
- For quick lookups, search this file for the keyword (ARN, secret name, bucket name)
- For step-by-step actions, follow `docs/AWS-SETUP.md` (canonical), and use this KNOWLEDGE-POOL for fast facts
- When purging, move candidate files into `docs/archived/` with a short summary commit message (include `Purge:` tag)

---

If you'd like, I will:
- create `docs/archived/` and move purge candidates there (commit), or
- generate a machine-readable index (JSON) for quick programmatic lookups, or
- expand any category with deeper extracted facts (e.g., full IAM policy JSON snippets)
