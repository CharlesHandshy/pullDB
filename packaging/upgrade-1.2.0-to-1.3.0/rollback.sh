#!/usr/bin/env bash
# =============================================================================
# pullDB 1.3.0 → 1.2.0  Rollback Script
# =============================================================================
# Run this ONLY if upgrade.sh completed the cutover step and something is wrong.
# Reads rollback-state.env written by upgrade.sh.
#
# Usage:  sudo ./rollback.sh
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/rollback-$(date +%Y%m%d-%H%M%S).log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*" | tee -a "$LOG_FILE"; }
ok()   { echo -e "${GREEN}  ✓${NC} $*" | tee -a "$LOG_FILE"; }
warn() { echo -e "${YELLOW}  ⚠${NC}  $*" | tee -a "$LOG_FILE"; }
die()  { echo -e "${RED}  ✗ FATAL:${NC} $*" | tee -a "$LOG_FILE"; exit 1; }

[[ $EUID -eq 0 ]] || die "Must run as root"

STATE_FILE="${SCRIPT_DIR}/rollback-state.env"
[[ -f "$STATE_FILE" ]] || die "rollback-state.env not found. Was upgrade.sh run?"

# Load state
# shellcheck disable=SC1090
source "$STATE_FILE"

log "=== pullDB Rollback: 1.3.0 → 1.2.0 (log: $LOG_FILE) ==="
log "  Will restore: $BLUE_CONTAINER ($BLUE_IMAGE)  on web=$BLUE_WEB_PORT api=$BLUE_API_PORT"
log "  Will stop:    $GREEN_CONTAINER"
echo ""
read -r -p "Proceed with rollback? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { log "Aborted."; exit 0; }

# Stop green
log "Stopping green container $GREEN_CONTAINER ..."
docker stop "$GREEN_CONTAINER" >> "$LOG_FILE" 2>&1 || warn "Green was not running"
ok "Green stopped"

# Restart blue on its original ports
log "Restarting blue container $BLUE_CONTAINER on ports $BLUE_WEB_PORT/$BLUE_API_PORT ..."
docker start "$BLUE_CONTAINER" >> "$LOG_FILE" 2>&1 || {
    # Blue was removed — recreate it
    warn "docker start failed, attempting docker run ..."
    docker run -d \
        --name "$BLUE_CONTAINER" \
        -p "${BLUE_WEB_PORT}:8000" \
        -p "${BLUE_API_PORT}:8080" \
        -v "${BLUE_CONFIG_DIR}:/etc/pulldb:ro" \
        -v "${BLUE_DATA_DIR}:/mnt/data" \
        -v "${BLUE_MYSQL_VOL}:/var/lib/mysql" \
        "$BLUE_IMAGE" \
        >> "$LOG_FILE" 2>&1 || die "Could not restart blue container"
}
ok "Blue started"

# Wait for blue health
MAX_WAIT=120; ELAPSED=0
while (( ELAPSED < MAX_WAIT )); do
    H=$(curl -fsk "https://localhost:${BLUE_API_PORT}/api/health" 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null \
        || echo "pending")
    [[ "$H" == "healthy" || "$H" == "ok" ]] && break
    sleep 5; ELAPSED=$(( ELAPSED + 5 ))
done
[[ "$H" == "healthy" || "$H" == "ok" ]] || die "Blue did not come healthy after ${MAX_WAIT}s"
ok "Blue is healthy on web=$BLUE_WEB_PORT api=$BLUE_API_PORT"

log "=== ROLLBACK COMPLETE ==="
log "  Active: $BLUE_CONTAINER (1.2.0)"
log "  Green container ($GREEN_CONTAINER) is stopped but not removed."
log "  To remove: docker rm $GREEN_CONTAINER && docker volume rm $GREEN_MYSQL_VOL"
