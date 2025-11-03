AWS quickstart for pullDB
=========================

This short guide shows the minimal AWS checks, secret formats, and IAM permissions the installer and runtime expect.

Quick validation commands
-------------------------
# Validate the AWS profile can call STS
aws --profile <profile> sts get-caller-identity

# Secrets Manager: describe the secret
aws --profile <profile> secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db

# Secrets Manager: get the secret value (requires GetSecretValue)
aws --profile <profile> secretsmanager get-secret-value --secret-id /pulldb/mysql/coordination-db

# SSM Parameter Store: get parameter (with decryption)
aws --profile <profile> ssm get-parameter --name /pulldb/mysql/coordination-db --with-decryption

Supported secret reference formats
----------------------------------
The installer accepts a secret "reference" which is written to the environment file as
`PULLDB_COORDINATION_SECRET`. The worker resolves this at runtime using the CredentialResolver
(`pulldb/infra/secrets.py`). Supported prefixes:

- aws-secretsmanager:/pulldb/mysql/coordination-db
  - A Secrets Manager secret. The value should contain the credentials needed to connect to the
    coordination MySQL database (JSON or connection string format expected by CredentialResolver).
  - The installer accepts either a full ARN or this path-style name.

- aws-ssm:/pulldb/mysql/coordination-db
  - A Systems Manager Parameter Store parameter, typically a SecureString containing the
    connection payload.

If you leave off the prefix and pass just `/pulldb/mysql/coordination-db`, the installer will
attempt to resolve it as a Secrets Manager secret first.

Minimum IAM permissions
-----------------------
The following are the minimal permissions the pulldb worker needs at runtime and that the
installer validates when `--validate` is used. Adjust IAM policies to your security model.

Secrets Manager (recommended):
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:/pulldb/mysql/*"
    }
  ]
}

SSM Parameter Store (alternative):
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter"
      ],
      "Resource": "arn:aws:ssm:REGION:ACCOUNT:parameter/pulldb/mysql/*"
    }
  ]
}

S3 access for backup discovery and download (example):
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::pestroutes-rds-backup-prod-vpc-us-east-1-s3/*"
    }
  ]
}

Security notes
--------------
- The installer only writes the secret *reference* to `/opt/pulldb/.env`, not the secret value.
- File permissions on `/opt/pulldb/.env` should be restrictive (owner pulldb:root or similar).
- For CI and automated installations, prefer instance roles or environment-based credentials over
  baking profile names into files.

Troubleshooting
---------------
- AccessDenied from the CLI: verify the profile maps to an identity with the above permissions.
- ResourceNotFound: double-check the secret/parameter name and account/region.

Further reading
---------------
- docs/aws-secrets-manager-setup.md (full onboarding instructions)
- pulldb/infra/secrets.py (CredentialResolver implementation)
