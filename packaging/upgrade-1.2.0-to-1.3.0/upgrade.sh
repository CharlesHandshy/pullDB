#!/usr/bin/env bash
# =============================================================================
# pullDB  1.2.0 → 1.3.0  Upgrade Script
# =============================================================================
# Usage:
#   sudo ./upgrade.sh [OPTIONS]
#
# Options:
#   --blue-container NAME    Running 1.2.0 container name   (default: pulldb-blue)
#   --green-container NAME   New 1.3.0 container name       (default: pulldb-green)
#   --image-tar PATH         Path to pulldb-1.3.0.tar.gz image archive
#                            (if omitted, script builds from .deb in this dir)
#   --deb PATH               Path to pulldb_1.3.0_amd64.deb
#                            (if omitted, looks in script directory)
#   --config-dir PATH        Host path containing service.env + aws/  (default: auto-detected)
#   --data-root PATH         Root for /mnt/data mounts               (default: /mnt/data)
#   --green-web-port PORT    Temporary web port for green             (default: 8002)
#   --green-api-port PORT    Temporary API port for green             (default: 8082)
#   --skip-cutover           Stop after green is healthy (no port swap)
#   --dry-run                Print what would happen, make no changes
#   --help
#
# What this script does (all steps are logged to upgrade-<timestamp>.log):
#   1.  Pre-flight: verify blue is healthy, check disk space, detect ports
#   2.  Dump MySQL from blue (locked dump, consistent snapshot)
#   3.  Load 1.3.0 image (from tar or build from .deb + Dockerfile)
#   4.  Start green on temporary ports, passing the dump for import
#   5.  Wait for green to finish importing and reach RUNNING state
#   6.  Run 1.2.0→1.3.0 migration SQL (idempotent, guarded ALTER/UPDATE statements)
#   7.  Health-check green API and web endpoints
#   8.  Cutover: stop blue, restart green on blue's original ports
#   9.  Write rollback marker so rollback.sh can restore blue if needed
#
# Rollback: run  sudo ./rollback.sh  (uses the marker written in step 9)
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/upgrade-$(date +%Y%m%d-%H%M%S).log"

# ── colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*" | tee -a "$LOG_FILE"; }
ok()   { echo -e "${GREEN}  ✓${NC} $*" | tee -a "$LOG_FILE"; }
warn() { echo -e "${YELLOW}  ⚠${NC}  $*" | tee -a "$LOG_FILE"; }
die()  { echo -e "${RED}  ✗ FATAL:${NC} $*" | tee -a "$LOG_FILE"; exit 1; }

# ── defaults ─────────────────────────────────────────────────────────────────
BLUE_CONTAINER="pulldb"
GREEN_CONTAINER="pulldb"
IMAGE_TAR=""
DEB_PATH=""
CONFIG_DIR=""
DATA_ROOT="/mnt/data"
GREEN_WEB_PORT="8002"
GREEN_API_PORT="8082"
SKIP_CUTOVER=false
DRY_RUN=false

# ── argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --blue-container)  BLUE_CONTAINER="$2";  shift 2 ;;
        --green-container) GREEN_CONTAINER="$2"; shift 2 ;;
        --image-tar)       IMAGE_TAR="$2";       shift 2 ;;
        --deb)             DEB_PATH="$2";         shift 2 ;;
        --config-dir)      CONFIG_DIR="$2";       shift 2 ;;
        --data-root)       DATA_ROOT="$2";        shift 2 ;;
        --green-web-port)  GREEN_WEB_PORT="$2";   shift 2 ;;
        --green-api-port)  GREEN_API_PORT="$2";   shift 2 ;;
        --skip-cutover)    SKIP_CUTOVER=true;     shift ;;
        --dry-run)         DRY_RUN=true;          shift ;;
        --help)
            grep '^#' "$0" | head -40 | sed 's/^# \{0,2\}//'
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

# If green's final name would collide with blue's name, use a temp name during
# the upgrade (steps 3-6). At cutover, the container is recreated under GREEN_CONTAINER.
GREEN_TMP_CONTAINER="${GREEN_CONTAINER}-upgrade"

run() {
    if $DRY_RUN; then
        echo -e "${YELLOW}  [DRY-RUN]${NC} $*" | tee -a "$LOG_FILE"
    else
        "$@" >> "$LOG_FILE" 2>&1
    fi
}

# =============================================================================
# STEP 0: Sanity checks
# =============================================================================
log "=== pullDB 1.2.0 → 1.3.0 Upgrade  (log: $LOG_FILE) ==="

[[ $EUID -eq 0 ]] || die "Must run as root (sudo ./upgrade.sh)"
command -v docker >/dev/null 2>&1 || die "docker is not installed"

# ── verify blue is running ────────────────────────────────────────────────────
log "STEP 0: Pre-flight checks"
docker inspect --format='{{.State.Running}}' "$BLUE_CONTAINER" 2>/dev/null \
    | grep -q "true" || die "Container '$BLUE_CONTAINER' is not running"
ok "Blue container '$BLUE_CONTAINER' is running"

# ── detect blue image version ─────────────────────────────────────────────────
BLUE_IMAGE=$(docker inspect --format='{{.Config.Image}}' "$BLUE_CONTAINER")
log "  Blue image: $BLUE_IMAGE"

# ── detect blue's ports ───────────────────────────────────────────────────────
BLUE_WEB_PORT=$(docker inspect --format='{{range $p,$conf := .NetworkSettings.Ports}}{{if eq $p "8000/tcp"}}{{(index $conf 0).HostPort}}{{end}}{{end}}' "$BLUE_CONTAINER" 2>/dev/null || echo "")
BLUE_API_PORT=$(docker inspect --format='{{range $p,$conf := .NetworkSettings.Ports}}{{if eq $p "8080/tcp"}}{{(index $conf 0).HostPort}}{{end}}{{end}}' "$BLUE_CONTAINER" 2>/dev/null || echo "")
[[ -n "$BLUE_WEB_PORT" ]] || die "Could not detect web port for '$BLUE_CONTAINER'"
[[ -n "$BLUE_API_PORT" ]] || die "Could not detect API port for '$BLUE_CONTAINER'"
ok "Blue ports: web=$BLUE_WEB_PORT  api=$BLUE_API_PORT"

# ── detect blue's volumes ─────────────────────────────────────────────────────
# Config dir: the host path mounted to /etc/pulldb inside blue
CONFIG_DIR_DETECTED=$(docker inspect --format='{{range .Mounts}}{{if eq .Destination "/etc/pulldb"}}{{.Source}}{{end}}{{end}}' "$BLUE_CONTAINER" 2>/dev/null || echo "")
if [[ -z "$CONFIG_DIR" ]]; then
    CONFIG_DIR="$CONFIG_DIR_DETECTED"
fi
[[ -n "$CONFIG_DIR" && -d "$CONFIG_DIR" ]] || die "Could not detect config dir (tried '$CONFIG_DIR'). Pass --config-dir."
ok "Config dir: $CONFIG_DIR"

# MySQL volume: named volume or bind-mount for /var/lib/mysql
MYSQL_VOL_BLUE=$(docker inspect --format='{{range .Mounts}}{{if eq .Destination "/var/lib/mysql"}}{{if .Name}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' "$BLUE_CONTAINER" 2>/dev/null || echo "")
[[ -n "$MYSQL_VOL_BLUE" ]] || die "Could not detect MySQL volume for '$BLUE_CONTAINER'"
ok "Blue MySQL volume: $MYSQL_VOL_BLUE"

# Data dir mount
DATA_MOUNT_BLUE=$(docker inspect --format='{{range .Mounts}}{{if eq .Destination "/mnt/data"}}{{.Source}}{{end}}{{end}}' "$BLUE_CONTAINER" 2>/dev/null || echo "")
[[ -n "$DATA_MOUNT_BLUE" ]] || DATA_MOUNT_BLUE="${DATA_ROOT}/${BLUE_CONTAINER}"
ok "Blue data dir: $DATA_MOUNT_BLUE"

# ── health check blue before touching anything ────────────────────────────────
HEALTH=$(curl -fsk "https://localhost:${BLUE_API_PORT}/api/health" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "unreachable")
[[ "$HEALTH" == "healthy" ]] || warn "Blue health check returned '$HEALTH' (continuing anyway)"
ok "Blue API health: $HEALTH"

# ── check green port availability ─────────────────────────────────────────────
for PORT in "$GREEN_WEB_PORT" "$GREEN_API_PORT"; do
    ss -tlnp "sport = :${PORT}" 2>/dev/null | grep -q LISTEN && \
        die "Port $PORT is already in use — choose different green ports with --green-web-port / --green-api-port"
done
ok "Green ports $GREEN_WEB_PORT/$GREEN_API_PORT are free"

# ── disk space (need ~4× the MySQL data size for dump + import) ───────────────
MYSQL_SIZE_MB=$(docker exec "$BLUE_CONTAINER" \
    du -sm /var/lib/mysql 2>/dev/null | awk '{print $1}' || echo 0)
FREE_MB=$(df -m "$DATA_ROOT" | awk 'NR==2{print $4}')
NEEDED_MB=$(( MYSQL_SIZE_MB * 4 ))
if (( FREE_MB < NEEDED_MB )); then
    warn "Disk space may be tight: need ~${NEEDED_MB}MB, have ${FREE_MB}MB on $DATA_ROOT"
else
    ok "Disk space OK: ${FREE_MB}MB free, ~${NEEDED_MB}MB needed"
fi

# =============================================================================
# STEP 1: Dump MySQL from blue
# =============================================================================
log "STEP 1: Dumping MySQL from '$BLUE_CONTAINER'"

DUMP_DIR="${DATA_ROOT}/upgrade-dumps"
DUMP_FILE="${DUMP_DIR}/pulldb_service_$(date +%Y%m%d-%H%M%S).sql"
run mkdir -p "$DUMP_DIR"

if ! $DRY_RUN; then
    # Determine MySQL creds inside blue
    MYSQL_PASS=$(docker exec "$BLUE_CONTAINER" bash -c \
        'set -a; source /opt/pulldb.service/.env 2>/dev/null; echo "${PULLDB_MYSQL_PASSWORD:-}"' 2>/dev/null || echo "")
    MYSQL_SOCK=$(docker exec "$BLUE_CONTAINER" bash -c \
        'set -a; source /opt/pulldb.service/.env 2>/dev/null; echo "${PULLDB_MYSQL_SOCKET:-/tmp/mysql.sock}"' 2>/dev/null || echo "/tmp/mysql.sock")
    MYSQL_DB=$(docker exec "$BLUE_CONTAINER" bash -c \
        'set -a; source /opt/pulldb.service/.env 2>/dev/null; echo "${PULLDB_MYSQL_DATABASE:-pulldb_service}"' 2>/dev/null || echo "pulldb_service")

    # Always dump as root via socket — root has full privileges needed for
    # --single-transaction, SHOW VIEW, PROCESS, etc. The socket bypasses auth.
    MYSQL_DUMP_CMD="mysqldump -u root -S \"${MYSQL_SOCK}\" --single-transaction --routines --triggers --no-tablespaces \"${MYSQL_DB}\""

    log "  Dumping $MYSQL_DB → $DUMP_FILE"
    docker exec "$BLUE_CONTAINER" bash -c "$MYSQL_DUMP_CMD" > "$DUMP_FILE" 2>>"$LOG_FILE" \
        || die "mysqldump failed — check $LOG_FILE"

    DUMP_ROWS=$(wc -l < "$DUMP_FILE")
    DUMP_SIZE=$(du -sh "$DUMP_FILE" | cut -f1)
    ok "Dump complete: $DUMP_FILE  ($DUMP_SIZE, ${DUMP_ROWS} lines)"

    # Quick sanity — check auth_users row count
    USER_COUNT=$(docker exec "$BLUE_CONTAINER" mysql -u root -S "$MYSQL_SOCK" -N \
        -e "SELECT COUNT(*) FROM ${MYSQL_DB}.auth_users;" 2>/dev/null || echo "?")
    ok "auth_users row count in blue: $USER_COUNT"
fi

# =============================================================================
# STEP 2: Load / build the 1.3.0 Docker image
# =============================================================================
log "STEP 2: Loading 1.3.0 Docker image"

IMAGE_NAME="pulldb:1.3.0"

if ! $DRY_RUN; then
    if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
        ok "Image $IMAGE_NAME already present"
    elif [[ -n "$IMAGE_TAR" && -f "$IMAGE_TAR" ]]; then
        log "  Loading from $IMAGE_TAR ..."
        docker load -i "$IMAGE_TAR" >> "$LOG_FILE" 2>&1 || die "docker load failed"
        ok "Loaded $IMAGE_NAME from $IMAGE_TAR"
    else
        # Build from .deb + Dockerfile
        if [[ -z "$DEB_PATH" ]]; then
            DEB_PATH=$(ls "${SCRIPT_DIR}"/pulldb_1.3.0_amd64.deb 2>/dev/null | head -1 || echo "")
        fi
        [[ -n "$DEB_PATH" && -f "$DEB_PATH" ]] || \
            die "No 1.3.0 image found. Pass --image-tar pulldb-1.3.0.tar.gz  OR  --deb pulldb_1.3.0_amd64.deb"

        BUILD_DIR=$(mktemp -d)
        cp "$DEB_PATH" "${BUILD_DIR}/pulldb_1.3.0_amd64.deb"
        # Dockerfile must be in the same directory as the .deb
        DOCKERFILE_SRC="${SCRIPT_DIR}/Dockerfile"
        [[ -f "$DOCKERFILE_SRC" ]] || die "Dockerfile not found at $DOCKERFILE_SRC"
        cp "$DOCKERFILE_SRC" "${BUILD_DIR}/Dockerfile"
        # Copy other files needed by Dockerfile
        for f in entrypoint.sh wait-for-mysql.sh pulldb-mysql.cnf install-pulldb-docker.sh; do
            [[ -f "${SCRIPT_DIR}/$f" ]] && cp "${SCRIPT_DIR}/$f" "${BUILD_DIR}/$f"
        done

        log "  Building $IMAGE_NAME from $(basename "$DEB_PATH") ..."
        docker build -t "$IMAGE_NAME" "$BUILD_DIR" >> "$LOG_FILE" 2>&1 \
            || die "docker build failed — check $LOG_FILE"
        rm -rf "$BUILD_DIR"
        ok "Built $IMAGE_NAME"
    fi
fi

# =============================================================================
# STEP 3: Start green container with dump import
# =============================================================================
log "STEP 3: Starting green container '$GREEN_TMP_CONTAINER' on ports $GREEN_WEB_PORT/$GREEN_API_PORT"

GREEN_DATA_DIR="${DATA_ROOT}/${GREEN_TMP_CONTAINER}"
run mkdir -p "${GREEN_DATA_DIR}/logs/pulldb" "${GREEN_DATA_DIR}/work/pulldb.service" "${GREEN_DATA_DIR}/tmp"
run chmod -R 777 "$GREEN_DATA_DIR"

# Copy the dump into green's data dir so the container can reach it at /mnt/data/
if ! $DRY_RUN; then
    cp "$DUMP_FILE" "${GREEN_DATA_DIR}/import.sql"
fi

GREEN_MYSQL_VOL="pulldb-green-mysql-$(date +%Y%m%d)"
run docker volume create "$GREEN_MYSQL_VOL"

if ! $DRY_RUN; then
    docker run -d \
        --name "$GREEN_TMP_CONTAINER" \
        -p "${GREEN_WEB_PORT}:8000" \
        -p "${GREEN_API_PORT}:8080" \
        -v "${CONFIG_DIR}:/etc/pulldb:ro" \
        -v "${GREEN_DATA_DIR}:/mnt/data" \
        -v "${GREEN_MYSQL_VOL}:/var/lib/mysql" \
        -e "PULLDB_IMPORT_DUMP=/mnt/data/import.sql" \
        --entrypoint /bin/bash \
        "$IMAGE_NAME" \
        -c 'grep -q "^PULLDB_AWS_PROFILE=" /opt/pulldb.service/.env 2>/dev/null \
            || cat /etc/pulldb/service.env >> /opt/pulldb.service/.env; \
            exec /entrypoint.sh' \
        >> "$LOG_FILE" 2>&1 || die "docker run for green failed"
    ok "Green container started (import in progress)"
fi

# =============================================================================
# STEP 4: Wait for green to become healthy
# =============================================================================
log "STEP 4: Waiting for green to finish import and come online"

if ! $DRY_RUN; then
    MAX_WAIT=300   # 5 minutes
    ELAPSED=0
    INTERVAL=10
    while (( ELAPSED < MAX_WAIT )); do
        STATUS=$(docker inspect --format='{{.State.Running}}' "$GREEN_TMP_CONTAINER" 2>/dev/null || echo "gone")
        if [[ "$STATUS" != "true" ]]; then
            # Container exited — check for restart vs fatal
            EXIT_CODE=$(docker inspect --format='{{.State.ExitCode}}' "$GREEN_TMP_CONTAINER" 2>/dev/null || echo "?")
            die "Green container exited (code=$EXIT_CODE). Last logs:\n$(docker logs --tail 20 "$GREEN_TMP_CONTAINER" 2>&1)"
        fi

        GREEN_HEALTH=$(curl -fsk "https://localhost:${GREEN_API_PORT}/api/health" 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null \
            || echo "pending")

        if [[ "$GREEN_HEALTH" == "healthy" || "$GREEN_HEALTH" == "ok" ]]; then
            ok "Green is healthy after ${ELAPSED}s"
            break
        fi

        log "  Green not ready yet (${ELAPSED}s / ${MAX_WAIT}s) — status: $GREEN_HEALTH"
        sleep $INTERVAL
        ELAPSED=$(( ELAPSED + INTERVAL ))
    done

    [[ "$GREEN_HEALTH" == "healthy" || "$GREEN_HEALTH" == "ok" ]] || \
        die "Green did not become healthy within ${MAX_WAIT}s. Check: docker logs $GREEN_TMP_CONTAINER"
fi

# =============================================================================
# STEP 5: Run 1.2.0 → 1.3.0 migration SQL
# =============================================================================
log "STEP 5: Applying 1.2.0 → 1.3.0 schema migrations"

MIGRATIONS_DIR="${SCRIPT_DIR}/migrations"
[[ -d "$MIGRATIONS_DIR" ]] || die "migrations/ directory not found at $SCRIPT_DIR"

if ! $DRY_RUN; then
    GREEN_MYSQL_SOCK=$(docker exec "$GREEN_TMP_CONTAINER" bash -c \
        'set -a; source /opt/pulldb.service/.env 2>/dev/null; echo "${PULLDB_MYSQL_SOCKET:-/tmp/mysql.sock}"' 2>/dev/null || echo "/tmp/mysql.sock")
    GREEN_MYSQL_DB=$(docker exec "$GREEN_TMP_CONTAINER" bash -c \
        'set -a; source /opt/pulldb.service/.env 2>/dev/null; echo "${PULLDB_MYSQL_DATABASE:-pulldb_service}"' 2>/dev/null || echo "pulldb_service")

    MIGRATION_OK=true
    for migration in $(ls "${MIGRATIONS_DIR}"/*.sql | sort); do
        mname=$(basename "$migration")
        log "  Applying migration: $mname"
        docker exec -i "$GREEN_TMP_CONTAINER" \
            mysql -u root -S "$GREEN_MYSQL_SOCK" "$GREEN_MYSQL_DB" \
            < "$migration" >> "$LOG_FILE" 2>&1 || {
                warn "Migration $mname reported an error (may be idempotent — check log)"
                MIGRATION_OK=false
            }
        ok "  $mname done"
    done

    if ! $MIGRATION_OK; then
        warn "One or more migrations had warnings. Review $LOG_FILE before proceeding."
        read -r -p "Continue anyway? [y/N] " CONT
        [[ "$CONT" =~ ^[Yy]$ ]] || die "Aborted by user after migration warnings"
    fi

    # Verify key column exists after migration
    ORIGIN_CHECK=$(docker exec "$GREEN_TMP_CONTAINER" \
        mysql -u root -S "$GREEN_MYSQL_SOCK" -N -e \
        "SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA='${GREEN_MYSQL_DB}' AND TABLE_NAME='jobs' AND COLUMN_NAME='origin';" 2>/dev/null || echo "0")
    [[ "$ORIGIN_CHECK" == "1" ]] || die "Migration check failed: jobs.origin column not found after migration"
    ok "Migration verified: jobs.origin exists"

    SUBDOMAIN_CHECK=$(docker exec "$GREEN_TMP_CONTAINER" \
        mysql -u root -S "$GREEN_MYSQL_SOCK" -N -e \
        "SELECT COUNT(*) FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA='${GREEN_MYSQL_DB}' AND TABLE_NAME='overlord_tracking' AND COLUMN_NAME='current_subdomain';" 2>/dev/null || echo "0")
    [[ "$SUBDOMAIN_CHECK" == "1" ]] || die "Migration check failed: overlord_tracking.current_subdomain not found"
    ok "Migration verified: overlord_tracking.current_subdomain exists"
fi

# =============================================================================
# STEP 6: Final health check on green
# =============================================================================
log "STEP 6: Final green health checks"

if ! $DRY_RUN; then
    # API health (green is still on temp ports at this point)
    GREEN_HEALTH=$(curl -fsk "https://localhost:${GREEN_API_PORT}/api/health" 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null \
        || echo "unreachable")
    [[ "$GREEN_HEALTH" == "healthy" || "$GREEN_HEALTH" == "ok" ]] || die "Green API not healthy: $GREEN_HEALTH"
    ok "Green API health: $GREEN_HEALTH"

    # Web UI responds
    WEB_STATUS=$(curl -fsk -o /dev/null -w "%{http_code}" \
        "https://localhost:${GREEN_WEB_PORT}/" 2>/dev/null || echo "000")
    [[ "$WEB_STATUS" =~ ^(200|302|303)$ ]] || die "Green web UI returned HTTP $WEB_STATUS"
    ok "Green web UI: HTTP $WEB_STATUS"

    # Row count parity check
    BLUE_MYSQL_SOCK=$(docker exec "$BLUE_CONTAINER" bash -c \
        'set -a; source /opt/pulldb.service/.env 2>/dev/null; echo "${PULLDB_MYSQL_SOCKET:-/tmp/mysql.sock}"' 2>/dev/null || echo "/tmp/mysql.sock")
    for TABLE in auth_users jobs db_hosts settings; do
        BLUE_CNT=$(docker exec "$BLUE_CONTAINER" mysql -u root -S "$BLUE_MYSQL_SOCK" -N \
            -e "SELECT COUNT(*) FROM ${MYSQL_DB}.${TABLE};" 2>/dev/null || echo "?")
        GREEN_CNT=$(docker exec "$GREEN_TMP_CONTAINER" mysql -u root -S "$GREEN_MYSQL_SOCK" -N \
            -e "SELECT COUNT(*) FROM ${GREEN_MYSQL_DB}.${TABLE};" 2>/dev/null || echo "?")
        if [[ "$BLUE_CNT" == "$GREEN_CNT" ]]; then
            ok "  $TABLE: blue=$BLUE_CNT green=$GREEN_CNT ✓"
        else
            warn "  $TABLE: blue=$BLUE_CNT green=$GREEN_CNT — mismatch (check if writes happened during dump)"
        fi
    done
fi

# =============================================================================
# STEP 7: Cutover — swap green to blue's ports
# =============================================================================
if $SKIP_CUTOVER; then
    warn "STEP 7: Skipped (--skip-cutover). Green is running on ports $GREEN_WEB_PORT/$GREEN_API_PORT."
    warn "  When ready, run:  sudo ./cutover.sh --blue $BLUE_CONTAINER --green $GREEN_TMP_CONTAINER"
    exit 0
fi

log "STEP 7: Cutover — stopping blue, restarting green on blue's ports"
log "  Blue was on: web=$BLUE_WEB_PORT  api=$BLUE_API_PORT"
log "  Downtime window starts NOW"

if ! $DRY_RUN; then
    # If blue and green share the same name, rename blue to free up the name for the new container.
    # This must happen before docker run or Docker will refuse the duplicate name.
    BLUE_FINAL_NAME="$BLUE_CONTAINER"
    if [[ "$BLUE_CONTAINER" == "$GREEN_CONTAINER" ]]; then
        BLUE_FINAL_NAME="${BLUE_CONTAINER}-prev"
        docker rename "$BLUE_CONTAINER" "$BLUE_FINAL_NAME" >> "$LOG_FILE" 2>&1 \
            || die "Failed to rename blue container to $BLUE_FINAL_NAME"
        log "  Blue renamed: $BLUE_CONTAINER → $BLUE_FINAL_NAME"
    fi

    # Write rollback marker BEFORE stopping blue
    cat > "${SCRIPT_DIR}/rollback-state.env" << EOF
# Written by upgrade.sh on $(date)
BLUE_CONTAINER=${BLUE_FINAL_NAME}
BLUE_IMAGE=${BLUE_IMAGE}
BLUE_WEB_PORT=${BLUE_WEB_PORT}
BLUE_API_PORT=${BLUE_API_PORT}
BLUE_MYSQL_VOL=${MYSQL_VOL_BLUE}
BLUE_CONFIG_DIR=${CONFIG_DIR}
BLUE_DATA_DIR=${DATA_MOUNT_BLUE}
GREEN_CONTAINER=${GREEN_CONTAINER}
GREEN_MYSQL_VOL=${GREEN_MYSQL_VOL}
GREEN_DATA_DIR=${GREEN_DATA_DIR}
DUMP_FILE=${DUMP_FILE}
EOF
    ok "Rollback state written to rollback-state.env"

    # Stop blue (now possibly under its renamed name)
    docker stop "$BLUE_FINAL_NAME" >> "$LOG_FILE" 2>&1
    ok "Blue stopped"

    # Stop the temp upgrade container, then start final container under GREEN_CONTAINER name
    docker stop "$GREEN_TMP_CONTAINER" >> "$LOG_FILE" 2>&1
    docker rm   "$GREEN_TMP_CONTAINER" >> "$LOG_FILE" 2>&1

    docker run -d \
        --name "$GREEN_CONTAINER" \
        -p "${BLUE_WEB_PORT}:8000" \
        -p "${BLUE_API_PORT}:8080" \
        -v "${CONFIG_DIR}:/etc/pulldb:ro" \
        -v "${GREEN_DATA_DIR}:/mnt/data" \
        -v "${GREEN_MYSQL_VOL}:/var/lib/mysql" \
        --entrypoint /bin/bash \
        "$IMAGE_NAME" \
        -c 'grep -q "^PULLDB_AWS_PROFILE=" /opt/pulldb.service/.env 2>/dev/null \
            || cat /etc/pulldb/service.env >> /opt/pulldb.service/.env; \
            exec /entrypoint.sh' \
        >> "$LOG_FILE" 2>&1 || die "Failed to restart green on production ports"

    # Wait for green to be healthy on production ports
    MAX_WAIT=120; ELAPSED=0
    while (( ELAPSED < MAX_WAIT )); do
        GH=$(curl -fsk "https://localhost:${BLUE_API_PORT}/api/health" 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null \
            || echo "pending")
        [[ "$GH" == "healthy" || "$GH" == "ok" ]] && break
        sleep 5; ELAPSED=$(( ELAPSED + 5 ))
    done
    [[ "$GH" == "healthy" || "$GH" == "ok" ]] || die "Green did not recover on port $BLUE_API_PORT within ${MAX_WAIT}s"

    log "  Downtime window ends NOW"
    ok "Green is live on production ports (web=$BLUE_WEB_PORT  api=$BLUE_API_PORT)"
fi

# =============================================================================
# DONE
# =============================================================================
echo ""
log "=== UPGRADE COMPLETE ==="
log "  New container : $GREEN_CONTAINER  (pulldb 1.3.0)"
log "  Web port      : $BLUE_WEB_PORT"
log "  API port      : $BLUE_API_PORT"
log "  MySQL volume  : $GREEN_MYSQL_VOL"
log "  Old container : ${BLUE_FINAL_NAME:-$BLUE_CONTAINER}  (stopped, NOT removed)"
log "  Dump file     : $DUMP_FILE"
log "  Log           : $LOG_FILE"
echo ""
log "To roll back:  sudo ./rollback.sh"
log "To clean up:   docker rm ${BLUE_FINAL_NAME:-$BLUE_CONTAINER} && docker volume rm $MYSQL_VOL_BLUE"
