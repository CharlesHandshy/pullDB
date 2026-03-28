#!/usr/bin/env bash
# =============================================================================
# pullDB 1.3.0 — Post-Upgrade Production Settings Injection
# =============================================================================
# Applies migration 014 to the live 1.3.0 container. Run this once after the
# 1.2.0→1.3.0 upgrade completes to:
#
#   1. Remove the spurious localhost db_host seeded during the dump-import upgrade
#   2. Remove the orphaned expiring_notice_days setting left by migration 011
#   3. Set default_dbhost to the aurora-test alias
#   4. Seed granular myloader settings for 1.3.0's settings-driven arg builder
#
# Usage:
#   sudo ./inject-production-settings.sh [--container NAME] [--dry-run]
#
# Options:
#   --container NAME   Running 1.3.0 container name (default: pulldb)
#   --dry-run          Print SQL only, make no changes
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION="${SCRIPT_DIR}/migrations/014_inject_production_settings.sql"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC}  $*"; }
die()  { echo -e "${RED}  ✗ FATAL:${NC} $*"; exit 1; }
log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*"; }

CONTAINER="pulldb"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --container) CONTAINER="$2"; shift 2 ;;
        --dry-run)   DRY_RUN=true; shift ;;
        --help)      grep '^#' "$0" | head -20 | sed 's/^# \{0,2\}//'; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

[[ -f "$MIGRATION" ]] || die "Migration file not found: $MIGRATION"

log "=== pullDB 1.3.0 Production Settings Injection ==="
log "Container : $CONTAINER"
log "Migration : $MIGRATION"

# Check container is running
docker inspect --format='{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true \
    || die "Container '$CONTAINER' is not running"
ok "Container is running"

# Resolve MySQL socket and database from container's .env
MYSQL_SOCK=$(docker exec "$CONTAINER" bash -c \
    'set -a; source /opt/pulldb.service/.env 2>/dev/null; echo "${PULLDB_MYSQL_SOCKET:-/tmp/mysql.sock}"' 2>/dev/null || echo "/tmp/mysql.sock")
MYSQL_DB=$(docker exec "$CONTAINER" bash -c \
    'set -a; source /opt/pulldb.service/.env 2>/dev/null; echo "${PULLDB_MYSQL_DATABASE:-pulldb_service}"' 2>/dev/null || echo "pulldb_service")

log "MySQL socket : $MYSQL_SOCK"
log "Database     : $MYSQL_DB"

if $DRY_RUN; then
    echo ""
    warn "DRY-RUN — SQL that would be applied:"
    echo "---"
    cat "$MIGRATION"
    echo "---"
    exit 0
fi

# Apply migration
log "Applying migration 014..."
docker exec -i "$CONTAINER" \
    mysql -u root -S "$MYSQL_SOCK" "$MYSQL_DB" \
    < "$MIGRATION"
ok "Migration 014 applied"

# Verify: localhost db_host removed
LOCALHOST_COUNT=$(docker exec "$CONTAINER" \
    mysql -u root -S "$MYSQL_SOCK" -N -e \
    "SELECT COUNT(*) FROM db_hosts WHERE hostname='localhost' AND id='550e8400-e29b-41d4-a716-446655440003';" \
    "$MYSQL_DB" 2>/dev/null || echo "?")
[[ "$LOCALHOST_COUNT" == "0" ]] \
    && ok "Verified: spurious localhost db_host removed" \
    || warn "localhost db_host still present (count=$LOCALHOST_COUNT) — check manually"

# Verify: expiring_notice_days removed
NOTICE_COUNT=$(docker exec "$CONTAINER" \
    mysql -u root -S "$MYSQL_SOCK" -N -e \
    "SELECT COUNT(*) FROM settings WHERE setting_key='expiring_notice_days';" \
    "$MYSQL_DB" 2>/dev/null || echo "?")
[[ "$NOTICE_COUNT" == "0" ]] \
    && ok "Verified: orphaned expiring_notice_days removed" \
    || warn "expiring_notice_days still present — check manually"

# Verify: default_dbhost updated
DEFAULT_HOST=$(docker exec "$CONTAINER" \
    mysql -u root -S "$MYSQL_SOCK" -N -e \
    "SELECT setting_value FROM settings WHERE setting_key='default_dbhost';" \
    "$MYSQL_DB" 2>/dev/null || echo "?")
ok "default_dbhost = '$DEFAULT_HOST'"

# Verify: new myloader settings present
NEW_SETTINGS_COUNT=$(docker exec "$CONTAINER" \
    mysql -u root -S "$MYSQL_SOCK" -N -e \
    "SELECT COUNT(*) FROM settings WHERE setting_key IN (
        'default_retention_days','myloader_max_threads_per_table',
        'myloader_max_threads_post_actions','myloader_retry_count',
        'myloader_optimize_keys','myloader_drop_table_mode',
        'myloader_verbose','myloader_local_infile','myloader_ignore_errors'
    );" \
    "$MYSQL_DB" 2>/dev/null || echo "?")
ok "New 1.3.0 settings seeded: $NEW_SETTINGS_COUNT / 9 core settings present"

# Show final counts
DB_HOST_COUNT=$(docker exec "$CONTAINER" \
    mysql -u root -S "$MYSQL_SOCK" -N -e \
    "SELECT COUNT(*) FROM db_hosts;" "$MYSQL_DB" 2>/dev/null || echo "?")
SETTINGS_COUNT=$(docker exec "$CONTAINER" \
    mysql -u root -S "$MYSQL_SOCK" -N -e \
    "SELECT COUNT(*) FROM settings;" "$MYSQL_DB" 2>/dev/null || echo "?")

log "=== COMPLETE ==="
ok "db_hosts : $DB_HOST_COUNT"
ok "settings : $SETTINGS_COUNT"
log "Run 'docker exec $CONTAINER mysql -u root -S $MYSQL_SOCK $MYSQL_DB -e \"SELECT setting_key, setting_value FROM settings ORDER BY setting_key;\"' to review all settings"
