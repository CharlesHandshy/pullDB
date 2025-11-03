#!/usr/bin/env bash
set -euo pipefail

# pullDB installer (interactive + non-interactive)
# Default install prefix: /opt/pulldb
# Responsibilities:
#  - Prompt or accept flags for install directory (--prefix)
#  - Accept AWS profile (--aws-profile) & coordination secret (--secret)
#  - Optional validation (--validate) of AWS profile and secret existence
#  - Create directory structure and Python virtual environment
#  - Install Python package
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
  --aws-profile NAME      AWS profile for PULLDB_AWS_PROFILE (default dev)
                          (see docs/aws-quickstart.md for examples and required IAM permissions)
  --secret NAME           Coordination secret name (default /pulldb/mysql/coordination-db)
                          Supported formats: aws-secretsmanager:/path, aws-ssm:/path
  --yes                   Assume yes for all confirmations
  --no-systemd            Do not install or enable systemd unit
  --validate              Validate AWS profile and secret existence
  --python BIN            Python interpreter (default python3)
  --help                  Show this help

Examples:
  sudo scripts/install_pulldb.sh --prefix /opt/pulldb --aws-profile dev \
    --secret aws-secretsmanager:/pulldb/mysql/coordination-db --yes

  # Run lightweight validation (will warn only when --validate used)
  sudo scripts/install_pulldb.sh --validate --aws-profile dev --secret /pulldb/mysql/coordination-db

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
  cat > "$env_path" <<EOF
# pullDB environment configuration
# Generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')
PULLDB_INSTALL_PREFIX=${INSTALL_PREFIX}
PULLDB_AWS_PROFILE=${AWS_PROFILE}
PULLDB_COORDINATION_SECRET=${COORD_SECRET}
# Additional optional overrides (uncomment as needed)
# PULLDB_LOG_DIR=
# PULLDB_WORK_DIR=
EOF
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
    info "Installing pulldb package from repository root: ${REPO_ROOT}"
    pip install "${REPO_ROOT}" || fail "pip install failed for ${REPO_ROOT}"
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

Next Steps:
1. Verify AWS credential access: aws sts get-caller-identity --profile ${AWS_PROFILE}
2. Confirm secret exists: aws --profile ${AWS_PROFILE} secretsmanager describe-secret --secret-id ${COORD_SECRET}
3. Validate daemon status: systemctl status pulldb-worker.service (if enabled)
4. Run CLI help: ${INSTALL_PREFIX}/venv/bin/pulldb --help
5. Tail logs (example): journalctl -u pulldb-worker -f -o cat

Uninstall (manual):
  systemctl stop pulldb-worker.service || true
  systemctl disable pulldb-worker.service || true
  rm -f /etc/systemd/system/pulldb-worker.service
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
    prompt AWS_PROFILE "AWS profile for pullDB" "dev"
  fi
  if [[ -z "$COORD_SECRET" ]]; then
    prompt COORD_SECRET "Coordination DB secret name" "/pulldb/mysql/coordination-db"
  fi

  mkdir -p "$INSTALL_PREFIX"
  cd "$INSTALL_PREFIX"

  generate_env_file ".env"
  create_virtualenv "$INSTALL_PREFIX/venv"
  validate_aws

  if [[ $NO_SYSTEMD -eq 1 ]]; then
    warn "--no-systemd specified; skipping unit install."
  else
    if confirm "Install systemd worker daemon?"; then
      install_systemd_unit "$INSTALL_PREFIX/scripts/pulldb-worker.service" || true
    else
      warn "Skipping systemd installation."
    fi
  fi

  post_install_summary
}

main "$@"
