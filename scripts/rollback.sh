#!/usr/bin/env bash
# =============================================================================
# pullDB — Manual rollback
# =============================================================================
# Promotes the paused blue (previous) container back to active.
# Use when green has been promoted but something is wrong post-promotion.
#
# Usage:
#   sudo ./scripts/rollback.sh
# =============================================================================
set -euo pipefail

STATE_DIR="/etc/pulldb"
ACTIVE_COLOR_FILE="${STATE_DIR}/.active-color"
COMPOSE_FILE="compose/docker-compose.yml"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[rollback]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[rollback]${NC} $*"; }
log_error() { echo -e "${RED}[rollback]${NC} $*" >&2; }

if [[ $EUID -ne 0 ]]; then log_error "Must run as root"; exit 1; fi

# Read current active color
if [[ ! -f "$ACTIVE_COLOR_FILE" ]]; then
    log_error "No active color file found at ${ACTIVE_COLOR_FILE}"
    log_error "Cannot determine which container to roll back to"
    exit 1
fi

ACTIVE_COLOR=$(cat "$ACTIVE_COLOR_FILE")
case "$ACTIVE_COLOR" in
    blue)  PREVIOUS_COLOR=green ;;
    green) PREVIOUS_COLOR=blue  ;;
    *)     log_error "Unknown active color: ${ACTIVE_COLOR}"; exit 1 ;;
esac

ACTIVE_CONTAINER="pulldb-${ACTIVE_COLOR}"
PREVIOUS_CONTAINER="pulldb-${PREVIOUS_COLOR}"

log_info "Current active: ${ACTIVE_COLOR} (${ACTIVE_CONTAINER})"
log_info "Rolling back to: ${PREVIOUS_COLOR} (${PREVIOUS_CONTAINER})"

# Verify the previous container exists and is paused
if ! docker inspect "$PREVIOUS_CONTAINER" >/dev/null 2>&1; then
    log_error "Previous container '${PREVIOUS_CONTAINER}' not found"
    log_error "It may have already been cleaned up — rollback is not possible"
    exit 1
fi

PREV_STATE=$(docker inspect --format '{{.State.Status}}' "$PREVIOUS_CONTAINER" 2>/dev/null || echo "unknown")
log_info "Previous container state: ${PREV_STATE}"

if [[ "$PREV_STATE" != "paused" && "$PREV_STATE" != "exited" ]]; then
    log_warn "Previous container is in state '${PREV_STATE}' (expected 'paused')"
fi

echo ""
read -r -p "  Rollback from ${ACTIVE_COLOR} → ${PREVIOUS_COLOR}? This will stop the current active container. [y/N] " confirm
case "$confirm" in [yY]*) ;; *) echo "Aborted."; exit 0 ;; esac

echo ""
log_info "Phase 1: Disabling maintenance mode on previous container..."
if [[ "$PREV_STATE" == "paused" ]]; then
    docker unpause "$PREVIOUS_CONTAINER" 2>/dev/null || true
fi
docker start "$PREVIOUS_CONTAINER" 2>/dev/null || true
docker exec "$PREVIOUS_CONTAINER" pulldb-admin maintenance disable 2>/dev/null \
    || log_warn "Could not disable maintenance mode — run manually after rollback: pulldb-admin maintenance disable"

log_info "Phase 2: Stopping active container (${ACTIVE_CONTAINER})..."
docker compose -p "pulldb-${ACTIVE_COLOR}" \
    --env-file "${STATE_DIR}/.env.${ACTIVE_COLOR}" \
    -f "$COMPOSE_FILE" \
    stop 2>/dev/null || docker stop "$ACTIVE_CONTAINER" 2>/dev/null || true

log_info "Phase 3: Promoting previous container to real ports..."
# Restart on real ports (already unpaused/started in Phase 1)
docker compose -p "pulldb-${PREVIOUS_COLOR}" \
    --env-file "${STATE_DIR}/.env.active" \
    -f "$COMPOSE_FILE" \
    up -d

# Update state
echo "$PREVIOUS_COLOR" > "$ACTIVE_COLOR_FILE"
cp "${STATE_DIR}/.env.${PREVIOUS_COLOR}" "${STATE_DIR}/.env.active"

log_info "Phase 4: Verifying rollback..."
sleep 5
if curl -fsk --max-time 10 "https://localhost:8080/api/health" >/dev/null 2>&1; then
    log_info "Health check passed — rollback successful"
else
    log_warn "Health check failed — check: docker logs ${PREVIOUS_CONTAINER}"
fi

echo ""
echo -e "${GREEN}Rollback complete. Active: ${PREVIOUS_COLOR}${NC}"
echo ""
echo "  The failed ${ACTIVE_COLOR} container is stopped but not removed."
echo "  Once you have investigated, remove it with:"
echo "    docker rm ${ACTIVE_CONTAINER}"
echo ""
