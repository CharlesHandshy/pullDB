#!/usr/bin/env bash
set -euo pipefail

# Upgrade script for pullDB
# Applies database migrations and refreshes the virtualenv with the latest installed wheel.

INSTALL_PREFIX="${PULLDB_INSTALL_PREFIX:-/opt/pulldb.service}"
WORKER_SERVICE="pulldb-worker.service"
API_SERVICE="pulldb-api.service"
WEB_SERVICE="pulldb-web.service"

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
systemctl stop $WEB_SERVICE 2>/dev/null || true

# Note: Schema updates are now handled automatically by postinst during dpkg install
# The schema_migrations table tracks which files have been applied
if [[ $SKIP_MIGRATE -eq 0 ]]; then
    info "Schema updates are applied automatically during package installation."
    info "To verify: mysql -e 'SELECT * FROM pulldb_service.schema_migrations ORDER BY applied_at'"
else
    warn "--no-migrate specified (schema updates happen during dpkg install anyway)"
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
systemctl start $WEB_SERVICE 2>/dev/null || true  # Web is optional

info "Upgrade complete."
info ""
info "Verify status:"
info "  systemctl status $WORKER_SERVICE"
info "  systemctl status $API_SERVICE"
info "  systemctl status $WEB_SERVICE"
info "  mysql -e 'SELECT * FROM pulldb_service.schema_migrations ORDER BY applied_at'"
