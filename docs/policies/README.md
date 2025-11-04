pulldb policies
================

This directory contains canonical, minimal IAM policy JSON files and trust policies referenced by `docs/KNOWLEDGE-POOL.md`.

Usage notes:
- These files are templates. Replace `<ACCOUNT_ID>` and `<EXTERNAL_ID>` placeholders when deploying.
- Review and scope ARNs (KMS keys, S3 prefixes) for your environment before attaching.
- Do not include secrets or credentials in policy files.

Files:
- `pulldb-staging-s3-read.json` — minimal staging S3 read policy
- `pulldb-secrets-manager-access.json` — secretsmanager + kms decrypt policy for dev role
- `pulldb-prod-policy.json` — production read-only S3 + parameter store with explicit deny on writes
- `pulldb-prod-trust.json` — assume-role trust policy for production cross-account role

Security guidance:
- Prefer creating these policies in the account owning the resource (production account for prod S3 policy).
- Use external IDs for cross-account trust where appropriate.
