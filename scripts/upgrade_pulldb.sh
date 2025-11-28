#!/usr/bin/env bash
set -euo pipefail

# Upgrade script for pullDB
# Applies database migrations and refreshes the virtualenv with the latest installed wheel.

INSTALL_PREFIX="${PULLDB_INSTALL_PREFIX:-/opt/pulldb.service}"
WORKER_SERVICE="pulldb-worker.service"
API_SERVICE="pulldb-api.service"

info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*" >&2; }
error() { echo "[ERROR] $*" >&2; }

if [[ $EUID -ne 0 ]]; then
   error "This script must be run as root."
   exit 1
fi

# Parse arguments
ASSUME_YES=0
SKIP_MIGRATE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y)
            ASSUME_YES=1; shift ;;
        --no-migrate)
            SKIP_MIGRATE=1; shift ;;
        --help|-h)
            echo "Usage: upgrade_pulldb.sh [--yes] [--no-migrate]"
            echo "  --yes         Non-interactive mode"
            echo "  --no-migrate  Skip database migrations"
            exit 0 ;;
        *)
            error "Unknown option: $1"; exit 1 ;;
    esac
done

info "Starting pullDB upgrade..."

# Stop services gracefully
info "Stopping services..."
systemctl stop $WORKER_SERVICE 2>/dev/null || true
systemctl stop $API_SERVICE 2>/dev/null || true

# Run database migrations first (before updating code)
if [[ $SKIP_MIGRATE -eq 0 ]]; then
    MIGRATE_SCRIPT="$INSTALL_PREFIX/scripts/pulldb-migrate.sh"
    if [[ -f "$MIGRATE_SCRIPT" ]] && [[ -f "$INSTALL_PREFIX/bin/dbmate" ]]; then
        info "Running database migrations..."
        
        # Source environment for migration credentials
        if [[ -f "$INSTALL_PREFIX/.env" ]]; then
            set -a
            source "$INSTALL_PREFIX/.env"
            set +a
        fi
        
        MIGRATE_FLAGS=""
        if [[ $ASSUME_YES -eq 1 ]]; then
            MIGRATE_FLAGS="--yes"
        fi
        
        if bash "$MIGRATE_SCRIPT" up $MIGRATE_FLAGS; then
            info "Migrations completed successfully"
        else
            warn "Migration failed - review and fix before restarting services"
            exit 1
        fi
    else
        warn "Migration tools not found, skipping migrations"
    fi
else
    warn "--no-migrate specified, skipping migrations"
fi

# Update virtual environment
info "Updating virtual environment..."

# Find the wheel file
WHEEL_FILE=""
for loc in "$INSTALL_PREFIX/dist" "$INSTALL_PREFIX"; do
    if compgen -G "${loc}/pulldb-*.whl" > /dev/null; then
        WHEEL_FILE=$(ls "${loc}"/pulldb-*.whl | sort -V | tail -n 1)
        break
    fi
done

if [[ -z "$WHEEL_FILE" ]]; then
    error "No wheel file found. The .deb package may not have installed correctly."
    exit 1
fi

info "Installing from: $WHEEL_FILE"
source "$INSTALL_PREFIX/venv/bin/activate"
pip install --upgrade "$WHEEL_FILE"

# Restart services
info "Restarting services..."
systemctl start $WORKER_SERVICE 2>/dev/null || warn "Failed to start $WORKER_SERVICE"
systemctl start $API_SERVICE 2>/dev/null || true  # API is optional

info "Upgrade complete."
info ""
info "Verify status:"
info "  systemctl status $WORKER_SERVICE"
info "  pulldb-migrate verify"
