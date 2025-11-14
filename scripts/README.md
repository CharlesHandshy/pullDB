# pullDB Scripts

This directory collects operational tooling, installer helpers, and diagnostics used to manage pullDB during the release freeze. Some historical scripts have been archived under `scripts/archived/` to preserve provenance without encouraging their use in new environments.

## Active Scripts

### verify-secrets-perms.sh

Diagnostic script to verify that the `pulldb-ec2-service-role` has correct Secrets Manager permissions.

### Requirements

- AWS CLI configured with a profile having IAM read permissions
- Profile must have: `iam:ListAttachedRolePolicies`, `iam:GetRole`, `iam:SimulatePrincipalPolicy`
- **Cannot** be run using the EC2 instance profile (it cannot introspect its own IAM configuration)

### Usage

```bash
# Basic usage with admin profile
./scripts/verify-secrets-perms.sh --profile dev-admin

# Verify specific secret
./scripts/verify-secrets-perms.sh --profile dev-admin --secret /pulldb/mysql/db3-dev

# View help
./scripts/verify-secrets-perms.sh --help
```

### What It Checks

1. **Policy Attachment**: Verifies `pulldb-secrets-manager-access` is attached to `pulldb-ec2-service-role`
2. **IAM Simulation**: Simulates required actions (GetSecretValue, DescribeSecret, ListSecrets, kms:Decrypt)
3. **Live Secret Access**: Attempts to describe and retrieve the secret
4. **Negative Test**: Verifies admin actions (CreateSecret, PutSecretValue, DeleteSecret) are denied
5. **KMS Key Policy**: If secret uses CMK, checks key policy references

### Exit Codes

- `0`: All permissions verified successfully
- `1`: Missing policy attachment or simulation failure
- `2`: Secret retrieval failed
- `3`: KMS key issues detected

### Example Output (Success)

```
[verify] Role: pulldb-ec2-service-role | Policy: pulldb-secrets-manager-access | Secret: /pulldb/mysql/coordination-db | Region: us-east-1
[verify] Policy attachment: OK
[verify] Resolved role ARN: arn:aws:iam::345321506926:role/pulldb-ec2-service-role
[verify] Simulate required action secretsmanager:GetSecretValue => allowed
[verify] Simulate required action secretsmanager:DescribeSecret => allowed
[verify] Simulate required action secretsmanager:ListSecrets => allowed
[verify] Simulate required action kms:Decrypt => allowed
[verify] Required actions simulation: OK
[verify] DescribeSecret: OK (Account 345321506926)
[verify] GetSecretValue: OK (truncated: {"username":"pulldb_app","password":"...
[verify] Simulate admin action secretsmanager:CreateSecret => implicitDeny
[verify] Simulate admin action secretsmanager:PutSecretValue => implicitDeny
[verify] Simulate admin action secretsmanager:DeleteSecret => implicitDeny
[verify] Admin action denial simulation: OK
[verify] Secret not using a customer CMK or key ID not exposed
[verify] All verification steps completed successfully
```

### Troubleshooting

**Error**: `AccessDenied for iam:ListAttachedRolePolicies`

- **Cause**: Running without a profile that has IAM read permissions
- **Fix**: Add `--profile dev-admin` (or another profile with IAMReadOnlyAccess)

**Error**: `Policy pulldb-secrets-manager-access NOT attached`

- **Cause**: Policy not attached to role
- **Fix**: Run the attach command shown in the error message

**Error**: `GetSecretValue failed`

- **Cause**: Policy attached but secret doesn't exist or KMS key denies access
- **Fix**: Verify secret exists: `aws secretsmanager list-secrets --query 'SecretList[?Name==`/pulldb/mysql/coordination-db`]'`

### Why Admin Profile Required?

The EC2 instance profile (`pulldb-ec2-service-role`) follows **least privilege principle** and does NOT have permissions to:
- List its own attached policies
- Get its own role details
- Simulate IAM policy decisions

These introspection actions are intentionally restricted to admin roles for security. However, the instance profile CAN read secrets directly once the policy is attached.

### Running from EC2 Instance

If you SSH into the EC2 instance:
1. Configure AWS CLI with an admin profile: `aws configure --profile dev-admin`
2. Run script with that profile: `./scripts/verify-secrets-perms.sh --profile dev-admin`
3. Test actual secret access (no profile needed): `aws secretsmanager get-secret-value --secret-id /pulldb/mysql/coordination-db`

### Integration with CI/CD

For automated verification in CI pipelines:
1. Use a service role or federated identity with IAMReadOnlyAccess
2. Run script as pre-deployment health check
3. Parse exit code (0 = success, non-zero = failure)
4. Include script output in build logs for audit trail

## Archived Scripts

| Script | Replacement |
| --- | --- |
| `setup-pulldb-schema.sh` | Apply `schema/pulldb.sql` directly (e.g. `mysql < schema/pulldb.sql`) |
| `setup-python-project.sh` | Activate a virtualenv and run `python -m pip install -e .[dev]` |

See `scripts/archived/README.md` for the original copies retained for reference.
