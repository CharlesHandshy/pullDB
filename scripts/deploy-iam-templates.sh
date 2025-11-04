#!/usr/bin/env bash
# Print safe AWS CLI commands to create policies/roles from templates in docs/policies/
# This script DOES NOT execute commands by default. It prints them for operator review.

set -euo pipefail

ROOT_DIR="$(dirname "$(dirname "${BASH_SOURCE[0]}")")"
POLICIES_DIR="$ROOT_DIR/docs/policies"

echo "This script prints AWS CLI commands to create IAM policies and roles using templates in $POLICIES_DIR"
echo "It will NOT execute them. Review and run the printed commands manually when ready."
echo

cat <<'EOF'
# Create staging policy (run in dev account)
aws iam create-policy --policy-name pulldb-staging-s3-read \
  --policy-document file://docs/policies/pulldb-staging-s3-read.json

# Create secrets access policy (run in dev account)
aws iam create-policy --policy-name pulldb-secrets-manager-access \
  --policy-document file://docs/policies/pulldb-secrets-manager-access.json

# Create production policy (run in production account)
aws iam create-policy --policy-name pulldb-prod-policy \
  --policy-document file://docs/policies/pulldb-prod-policy.json

# Create production role with trust policy (run in production account)
aws iam create-role --role-name pulldb-cross-account-readonly \
  --assume-role-policy-document file://docs/policies/pulldb-prod-trust.json

# Attach policy to role (run in production account)
aws iam attach-role-policy --role-name pulldb-cross-account-readonly \
  --policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/pulldb-prod-policy
EOF

echo
echo "NOTE: Replace <ACCOUNT_ID> and <EXTERNAL_ID> placeholders as appropriate."
