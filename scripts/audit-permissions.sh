#!/usr/bin/env bash
# Audit permissions and ownership under the test environment or project root.
# Follows Development File Ownership Principle.
# Exit codes:
# 0 = no drift OR drift successfully auto-remediated with --fix
# 2 = target directory missing
# 3 = drift detected (no fix mode)
# 4 = drift persists after attempted auto-remediation
set -euo pipefail

SHOW_HELP=0
FIX_MODE=0
EXPECTED_OWNER="${USER}" # Single-user assumption; can be overridden with --owner
TARGET_DIR=""

usage() {
  cat <<EOF
Usage: $0 [--fix] [--owner USER] [directory]

Audits ownership and permissions enforcing policy:
  Directories: 750 (or 755 acceptable)
  Executable scripts (*.sh, venv/bin/*): 750 (755 acceptable)
  Credentials (config/mysql-credentials.txt): 600 or 640
  Config (*.env, pyvenv.cfg, config/*): 640 or 600
  Regular files: 640/600/644

Options:
  --fix          Attempt auto-remediation of detected drift
  --owner USER   Expected owner (default: current \$USER)
  --help         Show this help

Exit codes:
  0 Success (clean or fixed)
  2 Target directory missing
  3 Drift detected (no fix performed)
  4 Drift persists after --fix
EOF
}

# Parse arguments (support flags in any order)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fix)
      FIX_MODE=1; shift ;;
    --owner)
      EXPECTED_OWNER="$2"; shift 2 ;;
    --help|-h)
      SHOW_HELP=1; shift ;;
    --*)
      echo "Unknown option: $1" >&2; exit 1 ;;
    *)
      if [[ -z "$TARGET_DIR" ]]; then
        TARGET_DIR="$1"; shift
      else
        echo "Unexpected extra positional argument: $1" >&2; exit 1
      fi ;;
  esac
done

[[ $SHOW_HELP -eq 1 ]] && { usage; exit 0; }
[[ -z "$TARGET_DIR" ]] && TARGET_DIR="test-env"

log() { echo "[audit] $*"; }
err() { echo "[audit][ERROR] $*" >&2; }

if [[ ! -d "$TARGET_DIR" ]]; then
  err "Target directory '$TARGET_DIR' does not exist"
  exit 2
fi

scan() {
  local drift=0
  while IFS= read -r line; do
    mode=$(echo "$line" | awk '{print $1}')
    owner=$(echo "$line" | awk '{print $2}')
    group=$(echo "$line" | awk '{print $3}')
    path=$(echo "$line" | cut -d' ' -f4-)

    # Skip symlinks; mode on symlink is not meaningful for enforcement here.
    if [[ -L "$path" ]]; then
      continue
    fi

    if [[ "$owner" != "$EXPECTED_OWNER" ]]; then
      err "Ownership drift: $path (owner=$owner expected=$EXPECTED_OWNER)"
      drift=$((drift+1))
      continue
    fi

    if [[ -d "$path" ]]; then
      [[ "$mode" == 750 || "$mode" == 755 ]] || { err "Directory mode drift: $path mode=$mode"; drift=$((drift+1)); }
    else
      case "$path" in
        *.sh|*/venv/bin/*)
          [[ "$mode" == 750 || "$mode" == 755 ]] || { err "Executable/script mode drift: $path mode=$mode"; drift=$((drift+1)); }
          ;;
        */config/mysql-credentials.txt)
          [[ "$mode" == 600 || "$mode" == 640 ]] || { err "Credential file mode drift: $path mode=$mode"; drift=$((drift+1)); }
          ;;
        *.env|*/pyvenv.cfg|*/config/*)
          [[ "$mode" == 640 || "$mode" == 600 ]] || { err "Config file mode drift: $path mode=$mode"; drift=$((drift+1)); }
          ;;
        *)
          [[ "$mode" == 640 || "$mode" == 600 || "$mode" == 644 ]] || { err "Regular file mode drift: $path mode=$mode"; drift=$((drift+1)); }
          ;;
      esac
    fi
  done < <(find "$TARGET_DIR" -printf '%m %u %g %p\n')
  echo "$drift"
}

remediate() {
  log "Attempting auto-remediation for '$TARGET_DIR' (owner=$EXPECTED_OWNER)"
  # Ownership normalization
  chown -R "$EXPECTED_OWNER":"$EXPECTED_OWNER" "$TARGET_DIR" 2>/dev/null || err "Ownership normalization encountered errors (non-fatal)"
  # Directory modes
  find "$TARGET_DIR" -type d -exec chmod 750 {} +
  # Executable scripts & venv bin
  find "$TARGET_DIR" -type f \( -name '*.sh' -o -path '*/venv/bin/*' \) -exec chmod 750 {} +
  # Credentials
  find "$TARGET_DIR" -type f -path '*/config/mysql-credentials.txt' -exec chmod 600 {} +
  # Config files (.env, pyvenv.cfg, config/*)
  find "$TARGET_DIR" -type f \( -name '*.env' -o -name 'pyvenv.cfg' -o -path '*/config/*' \) -exec chmod 640 {} +
  # Regular files (exclude already handled patterns)
  find "$TARGET_DIR" -type f \
    ! -path '*/venv/bin/*' \
    ! -name '*.sh' \
    ! -name 'mysql-credentials.txt' \
    ! -name '*.env' \
    ! -name 'pyvenv.cfg' \
    -exec chmod u=rw,g=r,o= {} +
}

log "Auditing permissions in: $TARGET_DIR (owner expectation: $EXPECTED_OWNER)"

DRIFT_COUNT=$(scan)

if [[ $DRIFT_COUNT -gt 0 ]]; then
  err "Detected $DRIFT_COUNT permission/ownership drift issue(s)"
  if [[ $FIX_MODE -eq 1 ]]; then
    remediate
    log "Re-scanning after remediation"
    DRIFT_COUNT=$(scan)
    if [[ $DRIFT_COUNT -gt 0 ]]; then
      err "Drift persists after auto-remediation (remaining=$DRIFT_COUNT). Manual intervention required."
      exit 4
    else
      log "Drift auto-remediated successfully."
      exit 0
    fi
  else
    exit 3
  fi
fi

log "No drift detected. Ownership and permissions conform to policy."
exit 0
