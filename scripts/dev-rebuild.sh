#!/bin/bash
# dev-rebuild.sh - Complete clean rebuild and deploy for production
# Usage: ./scripts/dev-rebuild.sh

set -e

cd /home/charleshandshy/Projects/pullDB

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

echo "=== Stopping services ==="
sudo systemctl stop pulldb-web pulldb-api pulldb-worker@1 pulldb-worker@2 pulldb-worker@3 2>/dev/null || true

echo "=== Removing and purging existing package ==="
sudo dpkg -r pulldb 2>/dev/null || true
sudo dpkg -P pulldb 2>/dev/null || true

echo "=== Installing new package ==="
sudo DEBIAN_FRONTEND=noninteractive dpkg -i "$DEB_FILE"

echo "=== Enabling services ==="
sudo systemctl enable pulldb-api pulldb-web pulldb-worker@1 pulldb-worker@2 pulldb-worker@3

echo "=== Starting services ==="
sudo systemctl start pulldb-api
sudo systemctl start pulldb-web
sudo systemctl start pulldb-worker@1
sudo systemctl start pulldb-worker@2
sudo systemctl start pulldb-worker@3

echo "=== Checking service status ==="
echo ""
echo "API:"
sudo systemctl is-active pulldb-api || true
echo "Web:"
sudo systemctl is-active pulldb-web || true
echo "Worker 1:"
sudo systemctl is-active pulldb-worker@1 || true
echo "Worker 2:"
sudo systemctl is-active pulldb-worker@2 || true
echo "Worker 3:"
sudo systemctl is-active pulldb-worker@3 || true

echo ""
echo "=== Done! ==="
echo ""
echo "Packages built:"
ls -lh pulldb_*.deb pulldb-client_*.deb 2>/dev/null || true
echo ""
echo "Wheels built:"
ls -lh dist/*.whl dist-client/*.whl 2>/dev/null || true
