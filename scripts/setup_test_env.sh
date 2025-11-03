#!/usr/bin/env bash
set -euo pipefail

# setup_test_env.sh - Ephemeral test environment provisioning for pullDB
#
# Creates (or refreshes) a Python virtual environment with all tooling and runtime
# dependencies required to run the test suite locally (mypy, pytest, pytest-timeout,
# ruff, mysql-connector-python, boto3, click, moto, jsonschema, fastapi, uvicorn,
# mypy-boto3 type stub packages). Provides a --dry-run mode to print planned actions
# without executing, and a --freeze option to emit a requirements-style lock summary.
#
# FAIL HARD philosophy: any step that does not complete successfully aborts with
# actionable diagnostics.
#
# Usage examples:
#   bash scripts/setup_test_env.sh                   # create .venv-test (default)
#   bash scripts/setup_test_env.sh --venv .venv-ci    # custom venv path
#   bash scripts/setup_test_env.sh --refresh          # recreate venv from scratch
#   bash scripts/setup_test_env.sh --dry-run          # show actions only
#   bash scripts/setup_test_env.sh --freeze           # output installed versions
#   bash scripts/setup_test_env.sh --python python3.12 # custom interpreter
#
# After creation:
#   source .venv-test/bin/activate
#   pytest -q --disable-warnings --maxfail=1
#   mypy pulldb
#
# This script intentionally does not install optional AWS credentials or system
# packages—only Python dependencies.

VENVDIR=".venv-test"
PYTHON_BIN="python3"
DO_REFRESH=0
DO_DRY_RUN=0
DO_FREEZE=0

PACKAGES=(
  pip
  setuptools
  wheel
  mypy
  pytest
  pytest-timeout
  ruff
  mysql-connector-python
  boto3
  click
  moto
  jsonschema
  fastapi
  uvicorn
  mypy-boto3-s3
  mypy-boto3-secretsmanager
  mypy-boto3-ssm
)

log() { echo "[setup-test-env] $*"; }
fail() { echo "[setup-test-env][ERROR] $*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: bash scripts/setup_test_env.sh [options]

Options:
  --venv PATH       Virtualenv directory (default .venv-test)
  --python BIN      Python interpreter (default python3)
  --refresh         Remove and recreate venv
  --dry-run         Show planned actions without executing
  --freeze          After install, output package version summary
  --help            Show this help
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --venv) VENVDIR="$2"; shift 2 ;;
      --python) PYTHON_BIN="$2"; shift 2 ;;
      --refresh) DO_REFRESH=1; shift ;;
      --dry-run) DO_DRY_RUN=1; shift ;;
      --freeze) DO_FREEZE=1; shift ;;
      --help|-h) usage; exit 0 ;;
      *) fail "Unknown option: $1" ;;
    esac
  done
}

print_plan() {
  log "Virtualenv directory: ${VENVDIR}";
  log "Interpreter: ${PYTHON_BIN}";
  if [[ $DO_REFRESH -eq 1 ]]; then log "Refresh: enabled"; else log "Refresh: disabled"; fi
  log "Packages to install (${#PACKAGES[@]}): ${PACKAGES[*]}";
  if [[ $DO_FREEZE -eq 1 ]]; then log "Freeze summary will be printed after install"; fi
}

create_or_refresh_venv() {
  if [[ $DO_REFRESH -eq 1 && -d "$VENVDIR" ]]; then
    log "Refreshing venv: removing existing ${VENVDIR}";
    rm -rf "$VENVDIR" || fail "Failed to remove existing venv ${VENVDIR}";
  fi
  if [[ ! -d "$VENVDIR" ]]; then
    log "Creating virtualenv at ${VENVDIR}";
    "$PYTHON_BIN" -m venv "$VENVDIR" || fail "Virtualenv creation failed";
  else
    log "Reusing existing virtualenv ${VENVDIR}";
  fi
}

install_packages() {
  # shellcheck disable=SC1090
  source "$VENVDIR/bin/activate" || fail "Failed to activate venv";
  log "Upgrading base packaging tools";
  pip install --upgrade pip setuptools wheel || fail "Failed to upgrade base tooling";
  log "Installing test/runtime packages";
  pip install "${PACKAGES[@]}" || fail "Failed to install packages";
}

freeze_summary() {
  # shellcheck disable=SC1090
  source "$VENVDIR/bin/activate" || fail "Failed to activate venv";
  log "Freeze summary (pip list)";
  pip list --format=columns | sed 's/^/[freeze] /';
}

main() {
  parse_args "$@";
  print_plan;
  if [[ $DO_DRY_RUN -eq 1 ]]; then
    log "Dry-run mode active; no changes applied.";
    exit 0;
  fi
  create_or_refresh_venv;
  install_packages;
  if [[ $DO_FREEZE -eq 1 ]]; then
    freeze_summary;
  fi
  log "Test environment setup complete. Activate with: source ${VENVDIR}/bin/activate";
}

main "$@"
