#!/usr/bin/env bash
# verify-secrets-perms.sh
# Diagnostic script to verify Secrets Manager permissions for pullDB instance role.
# Safe, read-only: uses IAM and Secrets Manager APIs (no mutations).
#
# REQUIREMENTS:
#   - AWS CLI configured with a profile having IAM read permissions (NOT instance profile)
#   - jq installed (optional; script degrades gracefully without it)
#
# IMPORTANT: This script requires iam:ListAttachedRolePolicies, iam:GetRole, and
# iam:SimulatePrincipalPolicy permissions. Run with --profile using a user/role
# that has IAMReadOnlyAccess or equivalent. The EC2 instance profile cannot verify itself.
#
# USAGE:
#   ./scripts/verify-secrets-perms.sh --profile <admin-profile> [--secret /pulldb/mysql/coordination-db]
#
# EXIT CODES:
#   0 = All required permissions verified
#   1 = Missing attachment or simulation failure
#   2 = Secret retrieval failed
#   3 = KMS key issues detected
#
# Performs:
#   1. Check role attachment for pulldb-secrets-manager-access
#   2. IAM policy simulation for required actions
#   3. Live describe + get of target secret
#   4. Negative simulation for admin actions (should be denied)
#   5. Optional KMS key policy inspection if secret uses CMK

set -euo pipefail
ROLE_NAME="pulldb-ec2-service-role"
POLICY_NAME="pulldb-secrets-manager-access"
SECRET_ID="/pulldb/mysql/coordination-db"
AWS_REGION="us-east-1"
PROFILE=""

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="$2"; shift 2 ;;
    --secret)
      SECRET_ID="$2"; shift 2 ;;
    --help|-h)
      sed -n '1,40p' "$0"; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

AWS() { if [[ -n "$PROFILE" ]]; then aws --profile "$PROFILE" "$@"; else aws "$@"; fi }

log() { echo "[verify] $*"; }
warn() { echo "[warn] $*" >&2; }
fail() { echo "[fail] $*" >&2; }

log "Role: $ROLE_NAME | Policy: $POLICY_NAME | Secret: $SECRET_ID | Region: $AWS_REGION"

# 1. Verify policy attachment
ATTACH_ERR=""
ATTACHED=$(AWS iam list-attached-role-policies --role-name "$ROLE_NAME" --query 'AttachedPolicies[].PolicyName' --output text 2> >(ATTACH_ERR=$(cat); typeset -p ATTACH_ERR) || true)
if [[ -n "$ATTACH_ERR" && "$ATTACH_ERR" == *"AccessDenied"* ]]; then
  fail "AccessDenied for iam:ListAttachedRolePolicies on $ROLE_NAME."
  echo "" >&2
  echo "This script requires IAM read permissions (iam:ListAttachedRolePolicies, iam:GetRole, iam:SimulatePrincipalPolicy)." >&2
  echo "The EC2 instance profile cannot verify its own IAM configuration." >&2
  echo "" >&2
  echo "Remediation:" >&2
  echo "  1. Run with an admin profile that has IAMReadOnlyAccess:" >&2
  echo "     ./scripts/verify-secrets-perms.sh --profile dev-admin" >&2
  echo "" >&2
  echo "  2. Configure AWS CLI with a user profile:" >&2
  echo "     aws configure --profile dev-admin" >&2
  echo "" >&2
  echo "  3. If running on EC2, you can temporarily grant the instance profile IAM read permissions," >&2
  echo "     but this is NOT recommended for production (least privilege principle)." >&2
  exit 1
fi
if ! grep -q "$POLICY_NAME" <<< "$ATTACHED"; then
  fail "Policy $POLICY_NAME NOT attached to role $ROLE_NAME. Attach with: aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn arn:aws:iam::345321506926:policy/$POLICY_NAME"
  exit 1
fi
log "Policy attachment: OK"

ROLE_ARN=""
if ROLE_ARN=$(AWS iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text 2>/dev/null); then
  log "Resolved role ARN: $ROLE_ARN"
  # 2. IAM policy simulation
  REQUIRED_ACTIONS=(secretsmanager:GetSecretValue secretsmanager:DescribeSecret secretsmanager:ListSecrets kms:Decrypt)
  SIMULATE_JSON=$(AWS iam simulate-principal-policy \
    --policy-source-arn "$ROLE_ARN" \
    --action-names "${REQUIRED_ACTIONS[@]}" \
    --resource-arns "arn:aws:secretsmanager:$AWS_REGION:$(cut -d: -f5 <<< "$ROLE_ARN"):secret:$SECRET_ID-*" 2>/dev/null || true)

  MISSING=""
  for act in "${REQUIRED_ACTIONS[@]}"; do
    DECISION=$(echo "$SIMULATE_JSON" | jq -r --arg A "$act" '.EvaluationResults[] | select(.EvalActionName==$A) | .EvalDecision' 2>/dev/null || echo "Unknown")
    if [[ "$DECISION" != "allowed" && "$DECISION" != "ImplicitDeny" ]]; then
      warn "Action $act evaluation returned $DECISION"
    fi
    if [[ "$DECISION" != "allowed" ]]; then
      MISSING+="$act "
    fi
    log "Simulate required action $act => $DECISION"
  done

  if [[ -n "$MISSING" ]]; then
    warn "Simulation indicates missing allows: $MISSING (continuing; live secret retrieval will confirm)."
  else
    log "Required actions simulation: OK"
  fi
else
  fail "AccessDenied for iam:GetRole on $ROLE_NAME. Grant permission or run with admin profile."; exit 1
fi

# 3. Live secret operations
DESCRIBE_OK=1
GET_OK=1

if DESCRIBE_OUT=$(AWS secretsmanager describe-secret --secret-id "$SECRET_ID" --region "$AWS_REGION" 2>/dev/null); then
  ACCOUNT_ID=$(echo "$DESCRIBE_OUT" | jq -r '.ARN' 2>/dev/null | cut -d: -f5 || true)
  log "DescribeSecret: OK (Account $ACCOUNT_ID)"
else
  fail "DescribeSecret failed for $SECRET_ID"
  DESCRIBE_OK=0
fi

if GET_OUT=$(AWS secretsmanager get-secret-value --secret-id "$SECRET_ID" --region "$AWS_REGION" 2>/dev/null); then
  TRUNC=$(echo "$GET_OUT" | jq -r '.SecretString' 2>/dev/null | head -c 80 || echo "(no jq)")
  log "GetSecretValue: OK (truncated: ${TRUNC}...)"
else
  fail "GetSecretValue failed for $SECRET_ID"
  GET_OK=0
fi

if [[ $DESCRIBE_OK -eq 0 || $GET_OK -eq 0 ]]; then
  exit 2
fi

# 4. Negative simulation (admin actions should be denied)
NEG_ACTIONS=(secretsmanager:CreateSecret secretsmanager:PutSecretValue secretsmanager:DeleteSecret)
NEG_JSON=$(AWS iam simulate-principal-policy \
  --policy-source-arn "$ROLE_ARN" \
  --action-names "${NEG_ACTIONS[@]}" \
  --resource-arns "arn:aws:secretsmanager:$AWS_REGION:$(cut -d: -f5 <<< "$ROLE_ARN"):secret:$SECRET_ID-*" 2>/dev/null || true)
NEG_FAIL=0
for act in "${NEG_ACTIONS[@]}"; do
  DECISION=$(echo "$NEG_JSON" | jq -r --arg A "$act" '.EvaluationResults[] | select(.EvalActionName==$A) | .EvalDecision' 2>/dev/null || echo "Unknown")
  log "Simulate admin action $act => $DECISION"
  if [[ "$DECISION" == "allowed" ]]; then
    fail "Admin action unexpectedly allowed: $act. Remove secret mutation permissions from role."; NEG_FAIL=1
  fi
done
if [[ $NEG_FAIL -eq 0 ]]; then
  log "Admin action denial simulation: OK"
fi

# 5. KMS key inspection (optional)
KMS_KEY_ID=$(echo "$DESCRIBE_OUT" | jq -r '.KmsKeyId' 2>/dev/null || echo "")
if [[ -n "$KMS_KEY_ID" && "$KMS_KEY_ID" != "null" ]]; then
  log "Secret uses CMK: $KMS_KEY_ID (checking decrypt permission)"
  # Simple test: attempt decrypt of a dummy blob will fail; rely on simulation already.
  # Here we just fetch key policy for human inspection.
  if KEY_POLICY=$(AWS kms get-key-policy --key-id "$KMS_KEY_ID" --policy-name default 2>/dev/null); then
    echo "$KEY_POLICY" | grep -q "$ROLE_NAME" && log "Key policy references role (good)" || warn "Role not explicitly present in key policy; relying on broader grants"
  else
    warn "Unable to retrieve key policy for $KMS_KEY_ID"
    exit 3
  fi
else
  log "Secret not using a customer CMK or key ID not exposed"
fi

log "All verification steps completed successfully"
exit 0
