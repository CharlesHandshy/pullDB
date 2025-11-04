# pullDB Knowledge Pool (condensed facts)

Purpose: a single-source, trimmed knowledge base used by agents and maintainers. This file contains only the facts required for current operations (Nov 2025). It is intentionally concise and indexed for fast lookup.

Last updated: 2025-11-04

---

## Index (categories)
- Accounts & ARNs
- S3 buckets & paths
- IAM roles & policies
- Secrets Manager (secrets + policies)
- EC2 / instance profile
- Restore workflow facts
- Quick commands & verification
- Purge candidates (files/docs to archive)
- Machine-readable index (JSON)
- IAM policy snippets (examples)
- Terraform examples (optional, small snippets)

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
- Coordination DB secret (MANDATORY): `/pulldb/mysql/coordination-db` (development account only)
- Target DB secrets:
  - `/pulldb/mysql/db3-dev`
  - `/pulldb/mysql/db4-dev`
  - `/pulldb/mysql/db5-dev`
- Secrets live in development account (345321506926) only as of 2025-11-01
- Runtime policy (`pulldb-secrets-manager-access`) should grant:
  - `secretsmanager:GetSecretValue` and `secretsmanager:DescribeSecret` on `arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/mysql/*`
  - `kms:Decrypt` (conditioned to Secrets Manager usage)

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
    "coordination_db": "/pulldb/mysql/coordination-db",
    "targets": ["/pulldb/mysql/db3-dev","/pulldb/mysql/db4-dev","/pulldb/mysql/db5-dev"]
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
