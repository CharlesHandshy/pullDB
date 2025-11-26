#!/usr/bin/env bash
set -euo pipefail

# Upgrade script for pullDB
# Refreshes the virtualenv with the latest installed wheel and restarts the service.

INSTALL_PREFIX="/opt/pulldb.service"
SERVICE_NAME="pulldb-worker.service"

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root."
   exit 1
fi

echo "Stopping $SERVICE_NAME..."
systemctl stop $SERVICE_NAME || true

echo "Updating virtual environment..."
# Re-run the install script to update pip packages
# We assume the new wheel has already been placed in /opt/pulldb.service/dist/ by the .deb install
"$INSTALL_PREFIX/scripts/install_pulldb.sh" --yes --no-systemd

echo "Restarting $SERVICE_NAME..."
systemctl start $SERVICE_NAME

echo "Upgrade complete."
