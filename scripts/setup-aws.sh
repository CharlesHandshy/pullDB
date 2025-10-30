#!/bin/bash
#
# AWS CLI v2 Installation and Configuration Script for pullDB
# Installs AWS CLI v2, verifies install, and optionally configures a default profile.
# Safe to re-run; skips steps if already installed.
#
# Usage:
#   sudo ./scripts/setup-aws.sh            # Install only
#   sudo ./scripts/setup-aws.sh --configure PROFILE_NAME REGION OUTPUT   # set region/output only; add keys with 'aws configure --profile <name>'
#   sudo ./scripts/setup-aws.sh --force    # Reinstall even if present
#
# Example:
#   sudo ./scripts/setup-aws.sh --configure pr-prod us-east-1 json
#
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

if [[ $EUID -ne 0 ]]; then
  error "Please run as root (use sudo)."
  exit 1
fi

FORCE=0
CONFIGURE=0
PROFILE_NAME=""
PROFILE_REGION=""
PROFILE_OUTPUT="json"

while (( "$#" )); do
  case "$1" in
    --force)
      FORCE=1
      shift
      ;;
    --configure)
      CONFIGURE=1
      PROFILE_NAME="$2"
      PROFILE_REGION="$3"
      PROFILE_OUTPUT="$4"
      shift 4
      ;;
    *)
      error "Unknown argument: $1"
      exit 1
      ;;
  esac
done

AWS_BIN="/usr/local/bin/aws"
INSTALLED=0
if command -v aws >/dev/null 2>&1; then
  INSTALLED=1
fi

if [[ $INSTALLED -eq 1 && $FORCE -eq 0 ]]; then
  info "AWS CLI already installed: $(aws --version)"
else
  if [[ $INSTALLED -eq 1 && $FORCE -eq 1 ]]; then
    warn "--force specified: reinstalling AWS CLI."
    rm -rf /usr/local/aws-cli || true
    rm -f /usr/local/bin/aws || true
  fi

  TMPDIR="/tmp/awscli_install"
  rm -rf "$TMPDIR"
  mkdir -p "$TMPDIR"
  info "Downloading AWS CLI v2 installer..."
  curl -sS "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "$TMPDIR/awscliv2.zip"

  if ! command -v unzip >/dev/null 2>&1; then
    info "Installing unzip package..."
    apt update -y >/dev/null 2>&1 || true
    apt install -y unzip >/dev/null 2>&1
  fi

  info "Extracting installer..."
  unzip -q "$TMPDIR/awscliv2.zip" -d "$TMPDIR"

  info "Running installer..."
  "$TMPDIR/aws/install" --update

  info "Cleaning up temporary files..."
  rm -rf "$TMPDIR"
fi

if ! command -v aws >/dev/null 2>&1; then
  error "AWS CLI installation failed. 'aws' not found on PATH."
  exit 1
fi

AWS_VERSION=$(aws --version)
info "AWS CLI Installed: $AWS_VERSION"

info "Verifying basic AWS CLI functionality (no credentials)..."
set +e
aws sts get-caller-identity >/dev/null 2>&1
STS_EXIT=$?
set -e
if [[ $STS_EXIT -ne 0 ]]; then
  info "STS call failed as expected (no credentials yet). This is normal."
fi

if [[ $CONFIGURE -eq 1 ]]; then
  if [[ -z "$PROFILE_NAME" || -z "$PROFILE_REGION" ]]; then
    error "--configure requires PROFILE_NAME REGION OUTPUT"
    exit 1
  fi
  info "Configuring AWS profile '$PROFILE_NAME' region/output (credentials managed separately)."

  TARGET_USER=${SUDO_USER:-root}
  TARGET_HOME=$(eval echo "~$TARGET_USER")
  AWS_CONFIG_DIR="$TARGET_HOME/.aws"
  mkdir -p "$AWS_CONFIG_DIR"
  CONFIG_FILE="$AWS_CONFIG_DIR/config"
  touch "$CONFIG_FILE"

  if grep -q "\[profile $PROFILE_NAME\]" "$CONFIG_FILE"; then
    warn "Profile '$PROFILE_NAME' already exists; updating region/output."
    sed -i "/\[profile $PROFILE_NAME\]/,/^$/ s/region = .*/region = $PROFILE_REGION/" "$CONFIG_FILE" || true
    sed -i "/\[profile $PROFILE_NAME\]/,/^$/ s/output = .*/output = $PROFILE_OUTPUT/" "$CONFIG_FILE" || true
  else
    cat >> "$CONFIG_FILE" <<EOF
[profile $PROFILE_NAME]
region = $PROFILE_REGION
output = $PROFILE_OUTPUT
EOF
  fi

  chmod 600 "$CONFIG_FILE"
  info "Region/output written for profile '$PROFILE_NAME'. Run 'aws configure --profile $PROFILE_NAME' as $TARGET_USER to add access keys if needed (development only; prefer IAM role)."
fi

cat <<SUMMARY

============================================
AWS CLI Setup Complete
============================================
Binary: $(command -v aws)
Version: $AWS_VERSION
Force Reinstall: $FORCE
Profile Configured: $CONFIGURE (${PROFILE_NAME:-none})

Next Steps:
1. (Dev only) Add credentials: sudo -u ${SUDO_USER:-$USER} aws configure --profile ${PROFILE_NAME:-your-profile}
2. (Prod) Attach IAM role to instance; no local keys required.
3. Validate identity:
  AWS_PROFILE=${PROFILE_NAME:-your-profile} aws sts get-caller-identity
4. List bucket (after permissions):
  AWS_PROFILE=${PROFILE_NAME:-your-profile} aws s3 ls s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/ | head
5. Prefer Parameter Store for MySQL credentials (see docs/parameter-store-setup.md)

SUMMARY
