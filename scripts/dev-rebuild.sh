#!/bin/bash
# dev-rebuild.sh - Clean rebuild and upgrade-deploy for development
# Usage: ./scripts/dev-rebuild.sh [NUM_WORKERS]
#
# NUM_WORKERS defaults to 3. Uses pulldb-worker@N template instances.
#
# This performs an UPGRADE install (dpkg -i), NOT a purge-reinstall.
# Configuration (.env, TLS certs, AWS config) is preserved.
# Use 'dpkg -P pulldb' manually if you truly need a clean-slate install.

# Re-exec under bash if invoked via sh/dash
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
NUM_WORKERS="${1:-3}"

cd "$PROJECT_ROOT"

echo "=== Running make clean ==="
make clean

echo "=== Building all packages ==="
echo "  - Python wheel (server)"
echo "  - Server .deb (with full dependencies)"
echo "  - Client .deb (minimal wheel, CLI only)"
make all

# Get the version from the built package
DEB_FILE=$(ls -t pulldb_*.deb 2>/dev/null | head -1)
if [ -z "$DEB_FILE" ]; then
    echo "ERROR: No .deb file found"
    exit 1
fi
echo "=== Built: $DEB_FILE ==="

# Build worker instance list
WORKER_INSTANCES=""
for i in $(seq 1 "$NUM_WORKERS"); do
    WORKER_INSTANCES="$WORKER_INSTANCES pulldb-worker@${i}"
done

echo "=== Stopping services ==="
# shellcheck disable=SC2086
sudo systemctl stop pulldb-web pulldb-api $WORKER_INSTANCES 2>/dev/null || true
# Also stop the single-instance worker if it was running (migration path)
sudo systemctl disable --now pulldb-worker.service 2>/dev/null || true

echo "=== Installing new package (upgrade) ==="
sudo DEBIAN_FRONTEND=noninteractive dpkg -i "$DEB_FILE"

# The postinst starts pulldb-worker.service (single instance).
# We use @N template instances instead, so disable the single one.
sudo systemctl disable --now pulldb-worker.service 2>/dev/null || true

echo "=== Enabling services (${NUM_WORKERS} workers) ==="
# shellcheck disable=SC2086
sudo systemctl enable pulldb-api pulldb-web $WORKER_INSTANCES pulldb-retention.timer 2>/dev/null || true

echo "=== Restarting services ==="
sudo systemctl restart pulldb-api
sudo systemctl restart pulldb-web
for i in $(seq 1 "$NUM_WORKERS"); do
    sudo systemctl restart "pulldb-worker@${i}"
done
sudo systemctl start pulldb-retention.timer 2>/dev/null || true

echo "=== Verifying services ==="
echo ""
# Wait up to 10 seconds for services to become active
FAILED=0
for svc in pulldb-api pulldb-web; do
    for attempt in 1 2 3 4 5; do
        state=$(sudo systemctl is-active "$svc" 2>/dev/null || true)
        [ "$state" = "active" ] && break
        sleep 2
    done
    printf "  %-24s %s\n" "$svc" "$state"
    if [ "$state" != "active" ]; then
        FAILED=1
    fi
done
for i in $(seq 1 "$NUM_WORKERS"); do
    svc="pulldb-worker@${i}"
    state=$(sudo systemctl is-active "$svc" 2>/dev/null || true)
    printf "  %-24s %s\n" "$svc" "$state"
    if [ "$state" != "active" ]; then
        FAILED=1
    fi
done

# Verify HTTPS endpoints (retry up to 5 times with 2s delay)
echo ""
echo "=== Verifying HTTPS ==="
API_STATUS="000"
WEB_STATUS="000"
for attempt in 1 2 3 4 5; do
    [ "$API_STATUS" = "000" ] && API_STATUS=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost:8080/api/health 2>/dev/null || echo "000")
    [ "$WEB_STATUS" = "000" ] && WEB_STATUS=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost:8000/web/login 2>/dev/null || echo "000")
    [ "$API_STATUS" != "000" ] && [ "$WEB_STATUS" != "000" ] && break
    sleep 2
done
printf "  %-24s %s\n" "API /api/health" "$API_STATUS"
printf "  %-24s %s\n" "Web /web/login" "$WEB_STATUS"

if [ "$API_STATUS" != "200" ] || [ "$WEB_STATUS" != "200" ]; then
    FAILED=1
fi

echo ""
echo "=== Packages built ==="
ls -lh pulldb_*.deb pulldb-client_*.deb 2>/dev/null || true
echo ""
echo "=== Wheels built ==="
ls -lh dist/*.whl dist-client/*.whl 2>/dev/null || true

if [ "$FAILED" -eq 1 ]; then
    echo ""
    echo "WARNING: Some checks failed. Review service logs:"
    echo "  sudo journalctl -u pulldb-api --no-pager -n 20"
    echo "  sudo journalctl -u pulldb-web --no-pager -n 20"
    echo "  sudo journalctl -u pulldb-worker@1 --no-pager -n 20"
    exit 1
fi

echo ""
echo "=== Deploy complete ==="
