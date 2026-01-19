#!/usr/bin/env bash
set -euo pipefail

# Upgrade script for pullDB
# Refreshes the virtualenv with the latest installed wheel.
# Note: Schema upgrades are not supported - fresh installs only.

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
while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y)
            ASSUME_YES=1; shift ;;
        --help|-h)
            echo "Usage: upgrade_pulldb.sh [--yes]"
            echo "  --yes         Non-interactive mode"
            echo ""
            echo "Note: Schema upgrades are not supported. This script only updates"
            echo "the Python package. For schema changes, manual migration is required."
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
