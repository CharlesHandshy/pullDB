#!/usr/bin/env bash
# CI permissions & ownership verification for pullDB
# Fails if unexpected root-owned files or drift in test-env (when present).
# Optional auto-remediation when PERMS_FIX=1 (only for test-env drift; root-owned artifacts still fail).
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FAILURES=0
PERMS_FIX="${PERMS_FIX:-0}"  # When set to 1 attempt remediation of test-env drift

log() { echo "[ci-perms] $*"; }
err() { echo "[ci-perms][ERROR] $*" >&2; }

log "Starting CI permissions check (auto-fix=$PERMS_FIX)"

# 1. Root-owned scan confined to project working directory
ROOT_OWNED=$(find "$ROOT_DIR" -user root -printf '%p\n' || true)
if [[ -n "$ROOT_OWNED" ]]; then
  err "Root-owned artifacts detected (cannot auto-fix without elevated privileges):\n$ROOT_OWNED"
  FAILURES=$((FAILURES+1))
else
  log "No root-owned artifacts detected"
fi

# 2. Run permission audit if test-env exists (non-fatal absence)
if [[ -d "$ROOT_DIR/test-env" ]]; then
  log "Running audit-permissions.sh on test-env"
  if ! bash "$ROOT_DIR/scripts/audit-permissions.sh" "$ROOT_DIR/test-env"; then
    err "Permission drift detected in test-env"
    if [[ "$PERMS_FIX" == "1" ]]; then
      log "Attempting auto-remediation (PERMS_FIX=1)"
      if bash "$ROOT_DIR/scripts/audit-permissions.sh" --fix "$ROOT_DIR/test-env"; then
        log "Auto-remediation succeeded for test-env drift"
      else
        err "Auto-remediation failed or residual drift remains"
        FAILURES=$((FAILURES+1))
      fi
    else
      FAILURES=$((FAILURES+1))
    fi
  else
    log "test-env permissions OK"
  fi
else
  log "test-env directory absent (skipping permission audit)"
fi

# 3. Report result
if [[ $FAILURES -gt 0 ]]; then
  err "CI permissions check failed with $FAILURES issue(s)."
  exit 3
fi
log "CI permissions check passed."
