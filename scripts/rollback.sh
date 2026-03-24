#!/usr/bin/env bash
# =============================================================================
# pullDB — Manual rollback
# =============================================================================
# Promotes the stopped previous container back to active.
# Use when the new container has been promoted but something is wrong.
#
# Usage:
#   sudo ./scripts/rollback.sh
# =============================================================================
set -euo pipefail

STATE_DIR="/etc/pulldb"
ACTIVE_COLOR_FILE="${STATE_DIR}/.active-color"
COMPOSE_FILE="${STATE_DIR}/docker-compose.yml"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[rollback]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[rollback]${NC} $*"; }
log_error() { echo -e "${RED}[rollback]${NC} $*" >&2; }

if [[ $EUID -ne 0 ]]; then log_error "Must run as root"; exit 1; fi

[[ -f "$COMPOSE_FILE" ]] || { log_error "Compose file not found at ${COMPOSE_FILE}"; exit 1; }

if [[ ! -f "$ACTIVE_COLOR_FILE" ]]; then
    log_error "No active color file found at ${ACTIVE_COLOR_FILE}"
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
PREVIOUS_ENV="${STATE_DIR}/.env.${PREVIOUS_COLOR}"

log_info "Current active: ${ACTIVE_COLOR} (${ACTIVE_CONTAINER})"
log_info "Rolling back to: ${PREVIOUS_COLOR} (${PREVIOUS_CONTAINER})"

# Verify previous container exists
if ! docker inspect "$PREVIOUS_CONTAINER" >/dev/null 2>&1; then
    log_error "Previous container '${PREVIOUS_CONTAINER}' not found"
    log_error "It may have already been cleaned up — rollback is not possible"
    exit 1
fi

# Verify the previous env file exists
if [[ ! -f "$PREVIOUS_ENV" ]]; then
    log_error "Previous env file not found: ${PREVIOUS_ENV}"
    exit 1
fi

PREV_STATE=$(docker inspect --format '{{.State.Status}}' "$PREVIOUS_CONTAINER" 2>/dev/null || echo "unknown")
log_info "Previous container state: ${PREV_STATE}"

if [[ "$PREV_STATE" != "exited" && "$PREV_STATE" != "paused" ]]; then
    log_warn "Previous container is in state '${PREV_STATE}' (expected exited or paused)"
fi

echo ""
read -r -p "  Rollback from ${ACTIVE_COLOR} → ${PREVIOUS_COLOR}? This will stop the current active container. [y/N] " confirm
case "$confirm" in [yY]*) ;; *) echo "Aborted."; exit 0 ;; esac

echo ""

# Phase 1: Disable maintenance mode on previous container via direct MySQL.
# We cannot use pulldb-admin here because the container is stopped —
# starting it before stopping the active would cause a port conflict.
log_info "Phase 1: Disabling maintenance mode on previous container (via MySQL)..."
if [[ "$PREV_STATE" == "paused" ]]; then
    docker unpause "$PREVIOUS_CONTAINER" 2>/dev/null || true
fi
docker start "$PREVIOUS_CONTAINER" --attach=false 2>/dev/null || true

# Wait briefly for MySQL to be ready inside the previous container
local_attempts=0
until docker exec "$PREVIOUS_CONTAINER" mysql -e "SELECT 1" >/dev/null 2>&1; do
    (( local_attempts++ )) || true
    (( local_attempts >= 15 )) && break
    sleep 2
done

docker exec "$PREVIOUS_CONTAINER" mysql pulldb_service \
    -e "INSERT INTO settings (setting_key, setting_value, description)
        VALUES ('maintenance_mode','false','Disabled by rollback.sh')
        ON DUPLICATE KEY UPDATE setting_value='false'" 2>/dev/null \
    || log_warn "Could not disable maintenance mode in previous container — will retry after promotion"

# Stop immediately — it will be restarted on real ports in Phase 3
docker stop "$PREVIOUS_CONTAINER" 2>/dev/null || true

# Phase 2: Stop the current active container
log_info "Phase 2: Stopping active container (${ACTIVE_CONTAINER})..."
docker compose -p "pulldb-${ACTIVE_COLOR}" \
    --env-file "${STATE_DIR}/.env.${ACTIVE_COLOR}" \
    -f "$COMPOSE_FILE" \
    stop 2>/dev/null || docker stop "$ACTIVE_CONTAINER" 2>/dev/null || true

# Phase 3: Start previous container on real ports using its own env file
log_info "Phase 3: Promoting ${PREVIOUS_CONTAINER} to real ports..."
docker compose -p "pulldb-${PREVIOUS_COLOR}" \
    --env-file "$PREVIOUS_ENV" \
    -f "$COMPOSE_FILE" \
    up -d

# Update state
echo "$PREVIOUS_COLOR" > "$ACTIVE_COLOR_FILE"
cp "$PREVIOUS_ENV" "${STATE_DIR}/.env.active"
chmod 600 "${STATE_DIR}/.env.active"

# Phase 4: Verify
log_info "Phase 4: Verifying rollback..."
local_attempts=0
until curl -fsk --max-time 5 "https://localhost:8080/api/health" >/dev/null 2>&1; do
    (( local_attempts++ )) || true
    if (( local_attempts >= 24 )); then
        log_warn "Health check failed after 120s — check: docker logs ${PREVIOUS_CONTAINER}"
        break
    fi
    sleep 5
done

if curl -fsk --max-time 5 "https://localhost:8080/api/health" >/dev/null 2>&1; then
    # Try maintenance disable via admin CLI now that it's running
    docker exec "$PREVIOUS_CONTAINER" pulldb-admin maintenance disable 2>/dev/null || true
    log_info "Health check passed — rollback successful"
fi

echo ""
echo -e "${GREEN}Rollback complete. Active: ${PREVIOUS_COLOR}${NC}"
echo ""
echo "  The failed ${ACTIVE_COLOR} container is stopped but not removed."
echo "  Once you have investigated, remove it with:"
echo "    docker rm ${ACTIVE_CONTAINER}"
echo ""
