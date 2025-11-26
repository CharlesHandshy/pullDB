#!/usr/bin/env bash
# If executed with sh, try to re-exec with bash
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

set -euo pipefail

# pullDB installer (interactive + non-interactive)
# Default install prefix: /opt/pulldb
# Responsibilities:
#  - Prompt or accept flags for install directory (--prefix)
#  - Accept AWS profile (--aws-profile) & coordination secret (--secret)
#  - Optional validation (--validate) of AWS profile and secret existence
#  - Create directory structure and Python virtual environment
#  - Install Python package (from source or bundled wheel)
#  - Generate .env file with required variables
#  - Install systemd unit unless --no-systemd provided
#  - Non-interactive mode with --yes (assume yes to confirmations)
#  - Display post-install verification steps

INSTALL_PREFIX_DEFAULT="/opt/pulldb"
PYTHON_BIN="python3"
ASSUME_YES=0
NO_SYSTEMD=0
DO_VALIDATE=0
INSTALL_PREFIX=""
AWS_PROFILE=""
COORD_SECRET=""
LOG_DIR=""
WORK_DIR=""
TMP_DIR=""

info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*" >&2; }
fail() { echo "[ERROR] $*" >&2; exit 1; }

require_root() {
  if [[ ${EUID} -ne 0 ]]; then
    if [[ "${PULLDB_INSTALLER_ALLOW_NON_ROOT:-}" == "1" ]]; then
      warn "Non-root override active (PULLDB_INSTALLER_ALLOW_NON_ROOT=1). Systemd steps may fail."
      return 0
    fi
    fail "Installer must be run as root (systemd unit + /opt write). Use sudo. Set PULLDB_INSTALLER_ALLOW_NON_ROOT=1 for test override."
  fi
}

prompt() {
  local var="$1"; shift
  local prompt_text="$1"; shift
  local default_val="$1"; shift || true
  local value
  read -r -p "${prompt_text} [${default_val}]: " value || true
  if [[ -z "$value" ]]; then
    value="$default_val"
  fi
  printf -v "$var" '%s' "$value"
}

confirm() {
  local question="$1"; shift
  if [[ $ASSUME_YES -eq 1 ]]; then
    info "Auto-confirm: $question"
    return 0
  fi
  read -r -p "${question} [y/N]: " reply || true
  if [[ "$reply" =~ ^[Yy]$ ]]; then
    return 0
  fi
  return 1
}

validate_aws() {
  if [[ $DO_VALIDATE -eq 0 ]]; then
    return 0
  fi
  info "Validating AWS profile '${AWS_PROFILE}'"
  if ! aws sts get-caller-identity --profile "$AWS_PROFILE" >/dev/null 2>&1; then
    warn "AWS profile validation failed (aws sts get-caller-identity)."
  fi
  info "Checking secret '${COORD_SECRET}'"
  if ! aws --profile "$AWS_PROFILE" secretsmanager describe-secret --secret-id "$COORD_SECRET" >/dev/null 2>&1; then
    warn "Secret describe failed for ${COORD_SECRET}. Continue after creating it."
  fi
}

usage() {
  cat <<EOF
Usage: sudo scripts/install_pulldb.sh [options]

Options:
  --prefix DIR            Install directory (default /opt/pulldb)
  --aws-profile NAME      AWS profile for PULLDB_AWS_PROFILE (default pr-prod)
                          (see docs/AWS-SETUP.md for examples and required IAM permissions)
  --secret NAME           Coordination secret name (default aws-secretsmanager:/pulldb/mysql/coordination-db)
                          Supported formats: aws-secretsmanager:/path, aws-ssm:/path
  --log-dir DIR           Log directory (default /mnt/data/logs/pulldb.service)
  --work-dir DIR          Work directory for restores (default /mnt/data/work/pulldb.service)
  --tmp-dir DIR           Temp directory for downloads (default /mnt/data/tmp)
  --yes                   Assume yes for all confirmations
  --no-systemd            Do not install or enable systemd unit
  --validate              Validate AWS profile and secret existence
  --python BIN            Python interpreter (default python3)
  --help                  Show this help

Examples:
  sudo scripts/install_pulldb.sh --prefix /opt/pulldb.service --aws-profile pr-prod \\
    --secret aws-secretsmanager:/pulldb/mysql/coordination-db --yes

  # Custom directories on separate mount
  sudo scripts/install_pulldb.sh --prefix /opt/pulldb.service \\
    --log-dir /mnt/data/logs/pulldb --work-dir /mnt/data/work/pulldb --yes

  # Run lightweight validation (will warn only when --validate used)
  sudo scripts/install_pulldb.sh --validate --aws-profile pr-prod

  # If you rely on instance role or CI-provided creds, omit --aws-profile and validate later.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prefix)
        INSTALL_PREFIX="$2"; shift 2 ;;
      --aws-profile)
        AWS_PROFILE="$2"; shift 2 ;;
      --secret)
        COORD_SECRET="$2"; shift 2 ;;
      --log-dir)
        LOG_DIR="$2"; shift 2 ;;
      --work-dir)
        WORK_DIR="$2"; shift 2 ;;
      --tmp-dir)
        TMP_DIR="$2"; shift 2 ;;
      --yes)
        ASSUME_YES=1; shift ;;
      --no-systemd)
        NO_SYSTEMD=1; shift ;;
      --validate)
        DO_VALIDATE=1; shift ;;
      --python)
        PYTHON_BIN="$2"; shift 2 ;;
      --help|-h)
        usage; exit 0 ;;
      *)
        fail "Unknown option: $1" ;;
    esac
  done
}

generate_env_file() {
  local env_path="$1"; shift
  local example_path="${env_path}.example"
  
  # Always generate the example file with current settings
  cat > "$example_path" <<EOF
# pullDB environment configuration (example)
# Copy to .env and customize for your environment
# Generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')

# Required settings
PULLDB_INSTALL_PREFIX=${INSTALL_PREFIX}
PULLDB_AWS_PROFILE=${AWS_PROFILE}
PULLDB_COORDINATION_SECRET=${COORD_SECRET}

# Directory settings
PULLDB_LOG_DIR=${LOG_DIR}
PULLDB_WORK_DIR=${WORK_DIR}
PULLDB_TMP_DIR=${TMP_DIR}

# Optional overrides
# PULLDB_LOG_LEVEL=INFO
# AWS_DEFAULT_REGION=us-east-1
EOF
  
  # Only create .env if it doesn't exist
  if [[ -f "$env_path" ]]; then
    info "Existing .env preserved (not overwritten). See ${example_path} for new defaults."
  else
    cp "$example_path" "$env_path"
    info "Created ${env_path} from example."
  fi
}

ensure_data_directories() {
  # Create parent /mnt/data if needed
  if [[ ! -d "/mnt/data" ]]; then
    mkdir -p /mnt/data
    chmod 755 /mnt/data
  fi
  
  # Log directory
  if [[ -n "$LOG_DIR" && ! -d "$LOG_DIR" ]]; then
    mkdir -p "$LOG_DIR"
    info "Created log directory: $LOG_DIR"
  fi
  
  # Work directory
  if [[ -n "$WORK_DIR" && ! -d "$WORK_DIR" ]]; then
    mkdir -p "$WORK_DIR"
    info "Created work directory: $WORK_DIR"
  fi
  
  # Temp directory (shared, sticky bit)
  if [[ -n "$TMP_DIR" && ! -d "$TMP_DIR" ]]; then
    mkdir -p "$TMP_DIR"
    chmod 1777 "$TMP_DIR"
    info "Created temp directory: $TMP_DIR"
  fi
}

install_systemd_unit() {
  local unit_src="$1"; shift
  local unit_dest="/etc/systemd/system/pulldb-worker.service"
  if [[ ! -f "$unit_src" ]]; then
    warn "Systemd unit template not found: $unit_src (skipping)"
    return 1
  fi
  cp "$unit_src" "$unit_dest"
  # Inject EnvironmentFile line if not present
  if ! grep -q '^EnvironmentFile=' "$unit_dest"; then
    sed -i "/^\[Service\]/a EnvironmentFile=${INSTALL_PREFIX}/.env" "$unit_dest"
  fi
  systemctl daemon-reload
  info "Installed systemd unit to $unit_dest"
  if confirm "Enable pulldb-worker service?"; then
    systemctl enable pulldb-worker.service
    info "Enabled pulldb-worker.service"
  fi
  if confirm "Start pulldb-worker service now?"; then
    systemctl start pulldb-worker.service
    info "Started pulldb-worker.service"
  else
    warn "Service not started; you can start later with: systemctl start pulldb-worker.service"
  fi
}

create_virtualenv() {
  local venv_dir="$1"; shift
  if [[ -d "$venv_dir" ]]; then
    warn "Virtualenv already exists: $venv_dir (reusing)"
  else
    info "Creating virtual environment at $venv_dir"
    "$PYTHON_BIN" -m venv "$venv_dir"
  fi
  # shellcheck disable=SC1090
  source "$venv_dir/bin/activate"
  pip install --upgrade pip wheel
  if [[ "${PULLDB_INSTALLER_SKIP_PIP:-}" == "1" ]]; then
    warn "Skipping pip install (PULLDB_INSTALLER_SKIP_PIP=1)"
  else
    # Check if we are in a source repo or need to find a wheel
    if [[ -f "${REPO_ROOT}/pyproject.toml" ]]; then
        info "Installing pulldb package from repository root: ${REPO_ROOT}"
        pip install "${REPO_ROOT}" || fail "pip install failed for ${REPO_ROOT}"
    else
        # Look for a wheel in likely locations
        local wheel_file=""
        # Check current dir, parent dir, and a 'dist' subdir
        for loc in "${REPO_ROOT}" "${REPO_ROOT}/.." "${REPO_ROOT}/dist" "${REPO_ROOT}/../dist"; do
            if compgen -G "${loc}/pulldb-*.whl" > /dev/null; then
                wheel_file=$(ls "${loc}"/pulldb-*.whl | head -n 1)
                break
            fi
        done
        
        if [[ -n "$wheel_file" ]]; then
            info "Installing pulldb package from wheel: $wheel_file"
            pip install "$wheel_file" || fail "pip install failed for $wheel_file"
        else
            fail "Could not find pyproject.toml or pulldb-*.whl to install."
        fi
    fi
  fi
}

post_install_summary() {
  cat <<EOF
Installation complete.

Location: ${INSTALL_PREFIX}
Environment: ${INSTALL_PREFIX}/.env
Virtualenv: ${INSTALL_PREFIX}/venv
AWS Profile: ${AWS_PROFILE}
Coordination Secret: ${COORD_SECRET}
Log Directory: ${LOG_DIR}
Work Directory: ${WORK_DIR}
Temp Directory: ${TMP_DIR}

Next Steps:
1. Review/edit ${INSTALL_PREFIX}/.env
2. Verify AWS credential access: aws sts get-caller-identity --profile ${AWS_PROFILE}
3. Confirm secret exists: aws --profile ${AWS_PROFILE} secretsmanager describe-secret --secret-id ${COORD_SECRET}
4. Validate daemon status: systemctl status pulldb-worker.service (if enabled)
5. Run CLI help: ${INSTALL_PREFIX}/venv/bin/pulldb --help
6. Tail logs (example): journalctl -u pulldb-worker -f -o cat

Additional AWS guidance:
  See ${INSTALL_PREFIX}/AWS-SETUP.md for example AWS CLI validation commands and
  minimum IAM policy snippets required for Secrets Manager / SSM and S3 access.

Uninstall (manual):
  systemctl stop pulldb-worker.service pulldb-api.service || true
  systemctl disable pulldb-worker.service pulldb-api.service || true
  rm -f /etc/systemd/system/pulldb-worker.service /etc/systemd/system/pulldb-api.service
  systemctl daemon-reload
  rm -rf ${INSTALL_PREFIX}

EOF
}

main() {
  REPO_ROOT="$(pwd)"  # capture repository path before changing to install prefix
  require_root
  parse_args "$@"

  # Interactive fallbacks if not provided by flags
  if [[ -z "$INSTALL_PREFIX" ]]; then
    prompt INSTALL_PREFIX "Install directory" "$INSTALL_PREFIX_DEFAULT"
  fi
  if [[ -z "$AWS_PROFILE" ]]; then
    prompt AWS_PROFILE "AWS profile for pullDB" "pr-dev"
  fi
  if [[ -z "$COORD_SECRET" ]]; then
    prompt COORD_SECRET "Coordination DB secret name" "aws-secretsmanager:/pulldb/mysql/coordination-db"
  fi
  # Set defaults for directories based on install prefix
  if [[ -z "$LOG_DIR" ]]; then
    LOG_DIR="/mnt/data/logs/pulldb.service"
  fi
  if [[ -z "$WORK_DIR" ]]; then
    WORK_DIR="/mnt/data/work/pulldb.service"
  fi
  if [[ -z "$TMP_DIR" ]]; then
    TMP_DIR="/mnt/data/tmp"
  fi

  mkdir -p "$INSTALL_PREFIX"
  cd "$INSTALL_PREFIX"

  # Create data directories
  ensure_data_directories

  generate_env_file ".env"
  create_virtualenv "$INSTALL_PREFIX/venv"
  validate_aws

  if [[ $NO_SYSTEMD -eq 1 ]]; then
    warn "--no-systemd specified; skipping unit install."
  else
    if confirm "Install systemd worker daemon?"; then
      install_systemd_unit "$INSTALL_PREFIX/systemd/pulldb-worker.service" || true
    else
      warn "Skipping systemd installation."
    fi
  fi

  post_install_summary
}

main "$@"
