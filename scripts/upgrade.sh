#!/usr/bin/env bash
# =============================================================================
# pullDB — Blue/Green Upgrade Orchestrator
# =============================================================================
# Runs on the HOST. Manages the full 6-phase upgrade:
#
#   Phase 1 — Cleanup:   remove paused container from the previous upgrade
#   Phase 2 — Drain:     enable maintenance mode, wait for running jobs to finish
#   Phase 3 — Snapshot:  stop active container, copy MySQL data directory
#   Phase 4 — Candidate: spin up new container on validation ports with copied data
#   Phase 5 — Validate:  health + schema + QA restore
#   Phase 6 — Promote:   move data to permanent path, switch to real ports, re-enable
#
# Usage:
#   sudo ./scripts/upgrade.sh <image-uri>
#
# Example:
#   sudo ./scripts/upgrade.sh 123456789012.dkr.ecr.us-east-1.amazonaws.com/pulldb:1.4.0
#
# Options:
#   --skip-drain    Skip drain wait (useful for hotfixes already in the window)
#   --skip-qa       Skip validation tier 3 (QA restore); run tiers 1+2 only
#   --yes           Non-interactive: skip confirmation prompts
#   --dry-run       Print plan without executing
# =============================================================================
set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================
STATE_DIR="/etc/pulldb"
ACTIVE_COLOR_FILE="${STATE_DIR}/.active-color"
COMPOSE_FILE="${STATE_DIR}/docker-compose.yml"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPGRADE_TMP="/tmp/pulldb-upgrade"

# Permanent MySQL data directory on the host.
# Candidate uses a temp path during validation; on promote it is moved here.
MYSQL_DATA_BASE="/mnt/data/mysql"

# Real (active) ports
PORT_WEB_ACTIVE=8000
PORT_API_ACTIVE=8080

# Validation (candidate) ports — internal only, not externally routed
PORT_WEB_CANDIDATE=18000
PORT_API_CANDIDATE=18080

# Drain window
DRAIN_ZERO_HOUR=18      # 6PM — enable maintenance mode
DRAIN_DEADLINE_HOUR=7   # 7AM — maximum wait for running jobs

# =============================================================================
# Output helpers
# =============================================================================
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

log_info()  { echo -e "${GREEN}[upgrade]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[upgrade]${NC}  $*"; }
log_error() { echo -e "${RED}[upgrade]${NC}  $*" >&2; }
log_step()  { echo -e "\n${BLUE}══ Phase $* ${NC}"; }
log_dry()   { echo -e "  ${YELLOW}[DRY RUN]${NC} $*"; }

die() { log_error "$*"; exit 1; }

# =============================================================================
# Argument parsing
# =============================================================================
NEW_IMAGE=""
SKIP_DRAIN=false
SKIP_QA=false
YES=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-drain) SKIP_DRAIN=true; shift ;;
        --skip-qa)    SKIP_QA=true;    shift ;;
        --yes)        YES=true;        shift ;;
        --dry-run)    DRY_RUN=true;    shift ;;
        --*)          die "Unknown option: $1" ;;
        *)            NEW_IMAGE="$1";  shift ;;
    esac
done

[[ -z "$NEW_IMAGE" ]] && die "Usage: $0 [options] <image-uri>"

# =============================================================================
# Pre-flight
# =============================================================================
preflight() {
    [[ $EUID -ne 0 ]] && die "Must run as root"

    command -v docker >/dev/null 2>&1 || die "docker not found"
    docker compose version >/dev/null 2>&1 || die "docker compose plugin not found"
    command -v aws >/dev/null 2>&1 || die "aws CLI not found (needed for ECR login)"

    [[ -f "$COMPOSE_FILE" ]] \
        || die "Compose file not found at ${COMPOSE_FILE}. Run the installer first."
    [[ -f "$ACTIVE_COLOR_FILE" ]] \
        || die "No active color file at ${ACTIVE_COLOR_FILE}. Run the installer first."

    ACTIVE_COLOR=$(cat "$ACTIVE_COLOR_FILE")
    case "$ACTIVE_COLOR" in
        blue)  CANDIDATE_COLOR=green ;;
        green) CANDIDATE_COLOR=blue  ;;
        *)     die "Unknown active color: ${ACTIVE_COLOR}" ;;
    esac

    ACTIVE_CONTAINER="pulldb-${ACTIVE_COLOR}"
    CANDIDATE_CONTAINER="pulldb-${CANDIDATE_COLOR}"

    local state
    state=$(docker inspect --format '{{.State.Status}}' "$ACTIVE_CONTAINER" 2>/dev/null || echo "missing")
    [[ "$state" == "running" ]] \
        || die "Active container '${ACTIVE_CONTAINER}' is not running (state: ${state})"

    log_info "Active:    ${ACTIVE_COLOR}  (${ACTIVE_CONTAINER})"
    log_info "Candidate: ${CANDIDATE_COLOR}  (${CANDIDATE_CONTAINER})"
    log_info "New image: ${NEW_IMAGE}"

    if [[ "$DRY_RUN" == true ]]; then
        echo ""
        log_dry "Dry-run mode — no changes will be made"
        echo ""
    fi

    if [[ "$YES" != true && "$DRY_RUN" != true && -t 0 ]]; then
        echo ""
        read -r -p "  Proceed with upgrade? [y/N] " confirm
        case "$confirm" in [yY]*) ;; *) echo "Aborted."; exit 0 ;; esac
    fi
}

# =============================================================================
# Phase 1 — Cleanup previous paused container
# =============================================================================
phase1_cleanup() {
    log_step "1 — Cleanup (previous paused container)"

    local prev_state
    prev_state=$(docker inspect --format '{{.State.Status}}' "$CANDIDATE_CONTAINER" 2>/dev/null || echo "absent")

    if [[ "$prev_state" == "absent" ]]; then
        log_info "No previous '${CANDIDATE_CONTAINER}' to clean up"
        return
    fi

    log_info "Found previous '${CANDIDATE_CONTAINER}' in state: ${prev_state}"

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would stop and remove container: ${CANDIDATE_CONTAINER}"
        return
    fi

    if [[ "$prev_state" == "paused" ]]; then
        docker unpause "$CANDIDATE_CONTAINER" 2>/dev/null || true
    fi
    docker stop "$CANDIDATE_CONTAINER" 2>/dev/null || true
    docker rm   "$CANDIDATE_CONTAINER" 2>/dev/null || true
    rm -f "${STATE_DIR}/.env.${CANDIDATE_COLOR}"

    log_info "Previous '${CANDIDATE_CONTAINER}' removed"
}

# =============================================================================
# Phase 2 — Drain: enable maintenance mode, wait for running jobs to finish
# =============================================================================
# Queued jobs are durable — they survive restarts and upgrades unchanged.
# We only wait for jobs already running (status = running or canceling).
# =============================================================================
phase2_drain() {
    log_step "2 — Drain"

    if [[ "$SKIP_DRAIN" == true ]]; then
        log_warn "--skip-drain set: skipping drain phase"
        return
    fi

    local now_hour
    now_hour=$(date +%H | sed 's/^0*//')
    now_hour=${now_hour:-0}

    # Maintenance window spans midnight: hour >= 18 OR hour < 7
    local in_window=false
    if (( now_hour >= DRAIN_ZERO_HOUR || now_hour < DRAIN_DEADLINE_HOUR )); then
        in_window=true
    fi

    if [[ "$in_window" == false ]]; then
        log_warn "Current time is outside the maintenance window (6PM–7AM)"
        if [[ "$YES" != true && -t 0 ]]; then
            read -r -p "  Continue anyway? [y/N] " confirm
            case "$confirm" in [yY]*) ;; *) echo "Aborted."; exit 0 ;; esac
        fi
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would: docker exec ${ACTIVE_CONTAINER} pulldb-admin maintenance enable"
        log_dry "Would poll: jobs WHERE status IN ('running','canceling') until 0 or 7AM"
        return
    fi

    log_info "Enabling maintenance mode (worker stops claiming new jobs)..."
    docker exec "$ACTIVE_CONTAINER" pulldb-admin maintenance enable \
        || die "Failed to enable maintenance mode"

    # Wait for in-flight jobs to complete. Queued jobs are NOT waited on —
    # they are durable and will resume when the new container comes up.
    local deadline_ts
    deadline_ts=$(_next_7am_ts)
    local deadline_str
    deadline_str=$(date -d "@${deadline_ts}" '+%H:%M %Z' 2>/dev/null \
               || date -r  "${deadline_ts}" '+%H:%M %Z' 2>/dev/null \
               || echo "7AM")

    log_info "Waiting for running jobs to finish (deadline: ${deadline_str})..."

    local attempts=0
    while true; do
        local running_count
        running_count=$(docker exec "$ACTIVE_CONTAINER" \
            mysql pulldb_service -N \
            -e "SELECT COUNT(*) FROM jobs WHERE status IN ('running','canceling')" \
            2>/dev/null || echo "?")

        local now_ts
        now_ts=$(date +%s)

        if [[ "$running_count" == "0" ]]; then
            log_info "All running jobs finished"
            break
        fi

        if (( now_ts >= deadline_ts )); then
            log_warn "Deadline reached (${deadline_str}) with ${running_count} job(s) still running"
            log_warn "Proceeding — those jobs will be interrupted and can be re-queued"
            break
        fi

        (( attempts++ )) || true
        if (( attempts % 6 == 0 )); then
            local remaining=$(( deadline_ts - now_ts ))
            log_info "  ${running_count} job(s) running — ${remaining}s until deadline"
        fi
        sleep 10
    done
}

# Returns the Unix timestamp of the next 7AM local time
_next_7am_ts() {
    local today_7am
    today_7am=$(date -d "today 07:00" +%s 2>/dev/null \
             || date -j -f "%Y%m%d %H%M" "$(date +%Y%m%d) 0700" +%s 2>/dev/null \
             || echo "")

    local now_ts
    now_ts=$(date +%s)

    if [[ -z "$today_7am" ]]; then
        # date command failed — deadline is 24h from now
        echo $(( now_ts + 86400 ))
        return
    fi

    if (( today_7am > now_ts )); then
        echo "$today_7am"
    else
        echo $(( today_7am + 86400 ))
    fi
}

# =============================================================================
# Phase 3 — Snapshot: stop active container, copy MySQL data directory
# =============================================================================
# The system goes OFFLINE here and stays offline until Phase 6 promotes
# the candidate container onto the real ports.
# =============================================================================
phase3_snapshot() {
    log_step "3 — Snapshot (system offline from here)"

    MYSQL_DATA_COPY="${UPGRADE_TMP}/mysql-data"

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would stop ${ACTIVE_CONTAINER}  ← system goes offline"
        log_dry "Would docker cp ${ACTIVE_CONTAINER}:/var/lib/mysql ${MYSQL_DATA_COPY}"
        return
    fi

    mkdir -p "$UPGRADE_TMP"
    chmod 700 "$UPGRADE_TMP"
    rm -rf "$MYSQL_DATA_COPY"

    log_info "Stopping ${ACTIVE_CONTAINER}...  (system offline)"
    docker compose \
        -p "pulldb-${ACTIVE_COLOR}" \
        --env-file "${STATE_DIR}/.env.active" \
        -f "$COMPOSE_FILE" \
        stop 2>/dev/null || docker stop "$ACTIVE_CONTAINER" 2>/dev/null \
        || die "Could not stop active container"

    log_info "Copying MySQL data directory from ${ACTIVE_CONTAINER}..."
    docker cp "${ACTIVE_CONTAINER}:/var/lib/mysql" "$MYSQL_DATA_COPY" \
        || die "docker cp /var/lib/mysql failed"

    # Fix ownership so mysqld inside the new container can read it (mysql uid=999 in Ubuntu image)
    chown -R 999:999 "$MYSQL_DATA_COPY" 2>/dev/null || true

    local size
    size=$(du -sh "$MYSQL_DATA_COPY" 2>/dev/null | cut -f1 || echo "?")
    log_info "Data copy: ${MYSQL_DATA_COPY} (${size})"
    # Active container is left in stopped (exited) state — available for rollback via docker start
}

# =============================================================================
# Phase 4 — Candidate: spin up on validation ports with copied data
# =============================================================================
phase4_candidate() {
    log_step "4 — Candidate spin-up (validation ports ${PORT_WEB_CANDIDATE}/${PORT_API_CANDIDATE})"

    local candidate_env="${STATE_DIR}/.env.${CANDIDATE_COLOR}"

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would ECR login and pull ${NEW_IMAGE}"
        log_dry "Would write ${candidate_env}"
        log_dry "Would docker compose -p pulldb-${CANDIDATE_COLOR} up -d"
        log_dry "  CONTAINER_NAME=${CANDIDATE_CONTAINER}"
        log_dry "  PORT_WEB=${PORT_WEB_CANDIDATE}  PORT_API=${PORT_API_CANDIDATE}"
        log_dry "  PULLDB_MYSQL_DATA_DIR=${MYSQL_DATA_COPY}"
        return
    fi

    log_info "Authenticating with ECR (host instance role)..."
    local ecr_registry ecr_region
    ecr_registry=$(echo "$NEW_IMAGE" | cut -d'/' -f1)
    ecr_region=$(echo "$ecr_registry" | sed 's/.*\.ecr\.\(.*\)\.amazonaws\.com/\1/')

    aws ecr get-login-password --region "$ecr_region" \
        | docker login --username AWS --password-stdin "$ecr_registry" \
        || die "ECR login failed — check host IAM role has ecr:GetAuthorizationToken"

    log_info "Pulling image: ${NEW_IMAGE}"
    docker pull "$NEW_IMAGE" || die "docker pull failed"

    # Candidate uses temp data path during validation
    cat > "$candidate_env" << EOF
# pullDB candidate env — ${CANDIDATE_COLOR}
# Generated by upgrade.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
PULLDB_IMAGE=${NEW_IMAGE}
CONTAINER_NAME=${CANDIDATE_CONTAINER}
PORT_WEB=${PORT_WEB_CANDIDATE}
PORT_API=${PORT_API_CANDIDATE}
PULLDB_IMPORT_DUMP=
PULLDB_MYSQL_DATA_DIR=${MYSQL_DATA_COPY}
EOF
    chmod 600 "$candidate_env"

    # Carry over validation settings from active env
    local active_env="${STATE_DIR}/.env.active"
    if [[ -f "$active_env" ]]; then
        grep -E "^PULLDB_VALIDATE_" "$active_env" >> "$candidate_env" 2>/dev/null || true
    fi

    log_info "Starting candidate container (volume-copy, offline)..."
    docker compose \
        -p "pulldb-${CANDIDATE_COLOR}" \
        --env-file "$candidate_env" \
        -f "$COMPOSE_FILE" \
        up -d

    log_info "Candidate '${CANDIDATE_CONTAINER}' starting — entrypoint applying schema migrations"
    log_info "validate.sh will poll until API is ready"
}

# =============================================================================
# Phase 5 — Validate
# =============================================================================
phase5_validate() {
    log_step "5 — Validate"

    local candidate_env="${STATE_DIR}/.env.${CANDIDATE_COLOR}"
    local validate_args=("$CANDIDATE_CONTAINER" "$PORT_API_CANDIDATE" "$candidate_env")
    [[ "$SKIP_QA" == true ]] && validate_args+=(--skip-qa)

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would run: scripts/validate.sh ${validate_args[*]}"
        return
    fi

    "${SCRIPTS_DIR}/validate.sh" "${validate_args[@]}" || {
        log_error "Validation FAILED — aborting upgrade"
        log_error "  Candidate logs: docker logs ${CANDIDATE_CONTAINER}"
        log_error ""
        log_error "Restoring active container and disabling maintenance mode..."

        docker start "$ACTIVE_CONTAINER" 2>/dev/null || true
        docker exec  "$ACTIVE_CONTAINER" pulldb-admin maintenance disable 2>/dev/null || true

        docker compose \
            -p "pulldb-${CANDIDATE_COLOR}" \
            --env-file "${STATE_DIR}/.env.${CANDIDATE_COLOR}" \
            -f "$COMPOSE_FILE" \
            stop 2>/dev/null || true

        log_error "Active container restored. Candidate stopped (not removed) for investigation."
        exit 1
    }
}

# =============================================================================
# Phase 6 — Promote: move data to permanent path, switch to real ports
# =============================================================================
phase6_promote() {
    log_step "6 — Promote"

    local candidate_env="${STATE_DIR}/.env.${CANDIDATE_COLOR}"
    local active_env="${STATE_DIR}/.env.active"

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would move ${MYSQL_DATA_COPY} → ${MYSQL_DATA_BASE}-${CANDIDATE_COLOR}"
        log_dry "Would relaunch ${CANDIDATE_CONTAINER} on ports ${PORT_WEB_ACTIVE}/${PORT_API_ACTIVE}"
        log_dry "Would write ${STATE_DIR}/.active-color = ${CANDIDATE_COLOR}"
        log_dry "Would docker exec ${CANDIDATE_CONTAINER} pulldb-admin maintenance disable"
        return
    fi

    # --- Move data from temp path to permanent host path ---
    local mysql_perm="${MYSQL_DATA_BASE}-${CANDIDATE_COLOR}"
    log_info "Moving MySQL data to permanent path: ${mysql_perm}"
    rm -rf "$mysql_perm"
    mv "$MYSQL_DATA_COPY" "$mysql_perm" \
        || { cp -a "$MYSQL_DATA_COPY" "$mysql_perm" && rm -rf "$MYSQL_DATA_COPY"; } \
        || die "Could not move MySQL data to ${mysql_perm}"

    # --- Stop candidate on validation ports ---
    log_info "Stopping candidate from validation ports..."
    docker compose \
        -p "pulldb-${CANDIDATE_COLOR}" \
        --env-file "$candidate_env" \
        -f "$COMPOSE_FILE" \
        stop 2>/dev/null || docker stop "$CANDIDATE_CONTAINER" 2>/dev/null || true

    # --- Write promoted env: real ports, permanent data path ---
    sed -i \
        -e "s|^PORT_WEB=.*|PORT_WEB=${PORT_WEB_ACTIVE}|" \
        -e "s|^PORT_API=.*|PORT_API=${PORT_API_ACTIVE}|" \
        -e "s|^PULLDB_IMPORT_DUMP=.*|PULLDB_IMPORT_DUMP=|" \
        -e "s|^PULLDB_MYSQL_DATA_DIR=.*|PULLDB_MYSQL_DATA_DIR=${mysql_perm}|" \
        "$candidate_env"
    cp "$candidate_env" "$active_env"
    chmod 600 "$active_env"

    # --- Start candidate on real ports ---
    log_info "Promoting ${CANDIDATE_CONTAINER} to real ports (${PORT_WEB_ACTIVE}/${PORT_API_ACTIVE})..."
    docker compose \
        -p "pulldb-${CANDIDATE_COLOR}" \
        --env-file "$candidate_env" \
        -f "$COMPOSE_FILE" \
        up -d

    # --- Update state file ---
    echo "$CANDIDATE_COLOR" > "$ACTIVE_COLOR_FILE"
    log_info "Active color: ${CANDIDATE_COLOR}"

    # --- Wait for promoted container to be healthy ---
    log_info "Waiting for promoted container to be healthy..."
    local attempts=0
    until curl -fsk --max-time 5 "https://localhost:${PORT_API_ACTIVE}/api/health" >/dev/null 2>&1; do
        (( attempts++ )) || true
        if (( attempts >= 24 )); then
            log_warn "Health check not passing after 120s"
            log_warn "  docker logs ${CANDIDATE_CONTAINER}"
            break
        fi
        sleep 5
    done

    # --- Disable maintenance mode ---
    log_info "Disabling maintenance mode..."
    docker exec "$CANDIDATE_CONTAINER" pulldb-admin maintenance disable \
        || log_warn "Could not disable maintenance mode — run manually: pulldb-admin maintenance disable"

    ACTIVE_COLOR="$CANDIDATE_COLOR"
    ACTIVE_CONTAINER="$CANDIDATE_CONTAINER"
}

# =============================================================================
# Summary
# =============================================================================
print_summary() {
    local new_version
    new_version=$(echo "$NEW_IMAGE" | sed 's/.*://')

    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  pullDB Upgrade Complete — ${new_version}${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "  Active container:  ${CANDIDATE_CONTAINER}  (${PORT_WEB_ACTIVE}/${PORT_API_ACTIVE})"
    echo "  Previous (stopped, for rollback): pulldb-${ACTIVE_COLOR}"
    echo ""
    echo "  To roll back:  sudo ${SCRIPTS_DIR}/rollback.sh"
    echo "  To clean up previous container after confirming stable:"
    echo "    docker rm pulldb-${ACTIVE_COLOR}"
    echo ""
}

# =============================================================================
# Main
# =============================================================================
main() {
    echo ""
    echo -e "${BLUE}pullDB Blue/Green Upgrade${NC}"
    echo ""

    preflight

    phase1_cleanup
    phase2_drain
    phase3_snapshot
    phase4_candidate
    phase5_validate
    phase6_promote

    print_summary
}

main
