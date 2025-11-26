#!/usr/bin/env bash
set -euo pipefail

# Uninstall script for pullDB
# Removes systemd service, virtualenv, and application files.

INSTALL_PREFIX="/opt/pulldb"
SERVICE_NAME="pulldb-worker.service"

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root."
   exit 1
fi

echo "Stopping $SERVICE_NAME..."
systemctl stop $SERVICE_NAME || true
systemctl disable $SERVICE_NAME || true
rm -f /etc/systemd/system/$SERVICE_NAME
systemctl daemon-reload

echo "Removing installation directory $INSTALL_PREFIX..."
read -p "Remove all data in $INSTALL_PREFIX (including logs)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "$INSTALL_PREFIX"
    echo "Removed $INSTALL_PREFIX"
else
    echo "Skipped removing $INSTALL_PREFIX"
fi

echo "Uninstall complete."
