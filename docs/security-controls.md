# Security Controls for S3 and Secrets Manager

> **Status**: ACTIVE (Implementation Verification)
> **Related Documents**:
> - `design/security-model.md` (High-level security philosophy)
> - `docs/AWS-SETUP.md` (Consolidated AWS setup guide)

## Overview

This document details the specific security controls implemented for AWS S3 and AWS Secrets Manager interactions within pullDB. It serves as the verification reference for the security review conducted on Nov 24, 2025.

## AWS Secrets Manager Controls

**Implementation**: `pulldb/infra/secrets.py`

### 1. Credential Redaction
- **Control**: The `MySQLCredentials` class implements a custom `__repr__` method that explicitly redacts the password field.
- **Verification**:
  ```python
  def __repr__(self) -> str:
      return (
          f"MySQLCredentials(username={self.username!r}, "
          f"password='***REDACTED***', "
          f"host={self.host!r}, ...)"
      )
  ```
- **Benefit**: Prevents accidental leakage of passwords in application logs, tracebacks, or debugger output.

### 2. Least Privilege Access
- **Control**: IAM policies are strictly scoped to specific resources.
- **Policy**: `pulldb-secrets-manager-access`
- **Scope**: `arn:aws:secretsmanager:us-east-1:345321506926:secret:/pulldb/mysql/*`
- **Actions**: `GetSecretValue`, `DescribeSecret` (Read-only), `ListSecrets` (metadata discovery).
- **Note**: `ListSecrets` requires `Resource: "*"` because AWS does not support resource-level permissions for this action. Filtering is done client-side.
- **Benefit**: Compromise of the application role limits exposure to only pullDB-specific database credentials.

### 3. Encryption at Rest
- **Control**: All secrets are encrypted using AWS KMS.
- **Implementation**: Secrets Manager enforces KMS encryption by default.
- **Permission**: The IAM role requires `kms:Decrypt` permission, scoped via condition `kms:ViaService` to `secretsmanager.us-east-1.amazonaws.com`.
- **Benefit**: Protects credentials even if underlying storage media is compromised.

### 4. Explicit Identity Management
- **Control**: The `CredentialResolver` respects the `PULLDB_AWS_PROFILE` environment variable.
- **Benefit**: Ensures operations use the intended identity (e.g., `pr-dev` vs instance profile), preventing accidental cross-account confusion.

### 5. Error Handling
- **Control**: Distinguishes between `ResourceNotFoundException` and `AccessDeniedException`.
- **Benefit**: Provides actionable FAIL HARD diagnostics without leaking existence or metadata of unauthorized secrets to attackers.

## AWS S3 Controls

**Implementation**: `pulldb/infra/s3.py`

### 1. Read-Only Design
- **Control**: The `S3Client` and `discover_latest_backup` functions are implemented for read-only operations (`ListObjectsV2`, `HeadObject`, `GetObject`).
- **Constraint**: No `PutObject` or `DeleteObject` methods exist in the discovery module.
- **Benefit**: Eliminates the risk of accidental backup deletion or modification by the discovery logic.

### 2. Strict Input Validation
- **Control**: Bucket paths and prefixes are validated before use.
- **Regex Enforcement**: Filenames must match strict patterns (e.g., `daily_mydumper_...`) to be processed.
- **Benefit**: Prevents the application from processing or downloading arbitrary files (e.g., malicious payloads) that might be placed in the bucket.

### 3. Timestamp Validation
- **Control**: Embedded timestamps in filenames are parsed and validated against expected formats.
- **Benefit**: Ensures only valid backup artifacts are considered for restoration.

### 4. TLS Enforcement
- **Control**: `boto3` uses HTTPS by default for all API calls.
- **Benefit**: Protects backup metadata and content from interception during transit.

### 5. Metadata-Only Discovery
- **Control**: Discovery logic uses `HeadObject` to retrieve size and metadata without downloading the full object.
- **Benefit**: Minimizes data transfer and exposure; full download only occurs during the explicit restore phase (Worker service).

## General Security Principles

### FAIL HARD on Security Violations
- **Principle**: Any authentication failure, permission denial, or validation error results in an immediate hard failure.
- **Implementation**: Custom exception classes (`CredentialResolutionError`, `BackupValidationError`) propagate the root cause up the stack.
- **Benefit**: Prevents the system from running in an insecure or degraded state.

### No Hardcoded Secrets
- **Principle**: Credentials are never stored in source code or configuration files.
- **Implementation**: All credentials are resolved at runtime from AWS Secrets Manager or SSM Parameter Store.
- **Benefit**: Eliminates the risk of secret leakage via source control.

## Operational Security: Profile Usage

Correct profile selection is a critical security control to prevent cross-account accidents and ensure least privilege.

### 1. `pr-dev` (Development Account)
- **Purpose**: Access to AWS Secrets Manager and MySQL coordination database.
- **Usage**:
  - Local development and testing of credential resolution.
  - Managing secrets (create/update) in the development account.
  - **Security Note**: This is the *only* profile with permission to read `/pulldb/mysql/*` secrets.

### 2. `pr-staging` (Staging Account Access)
- **Purpose**: Read-only access to the **Staging** S3 bucket (`pestroutesrdsdbs`).
- **Usage**:
  - Verifying backup discovery logic against staging data.
  - Testing downloaders with staging artifacts.
  - **Constraint**: Does NOT have access to Secrets Manager. Attempting to resolve secrets with this profile will fail (AccessDenied).

### 3. `pr-prod` (Production Account Access)
- **Purpose**: Read-only access to the **Production** S3 bucket (`pestroutes-rds-backup-prod-vpc-us-east-1-s3`).
- **Usage**:
  - Verifying discovery logic against production data patterns.
  - **Constraint**: Strictly read-only. No write access. No Secrets Manager access.

### 4. Instance Profile (EC2 Default)
- **Purpose**: Production runtime identity on the EC2 instance.
- **Usage**:
  - The API and Worker services run without an explicit `AWS_PROFILE` (or with `PULLDB_AWS_PROFILE` set to empty/default).
  - Automatically inherits permissions for *both* Secrets Manager (local account) and S3 (cross-account via assumed roles or direct policy).
