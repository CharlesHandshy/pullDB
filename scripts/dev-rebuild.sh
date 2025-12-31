#!/bin/bash
# dev-rebuild.sh - Complete clean rebuild and deploy for development
# Usage: ./scripts/dev-rebuild.sh

set -e

cd /home/charleshandshy/Projects/pullDB

echo "=== Cleaning build artifacts ==="
rm -rf dist/ build/ *.egg-info

echo "=== Building Python wheel ==="
python3 -m build

echo "=== Building Debian package ==="
./scripts/build_deb.sh

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
