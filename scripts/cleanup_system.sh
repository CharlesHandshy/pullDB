#!/bin/bash
set -e

echo "=== pullDB System Cleanup ==="
echo "This script will remove pullDB server and client installations."
echo "It detects both package-based and manual installations."

if [[ $EUID -ne 0 ]]; then
   echo "Error: This script must be run as root."
   exit 1
fi

# 1. Remove Debian Packages
if dpkg -l | grep -q "^ii  pulldb "; then
    echo "Detected 'pulldb' package. Removing..."
    apt-get remove -y pulldb
    apt-get purge -y pulldb
fi

if dpkg -l | grep -q "^ii  pulldb-client "; then
    echo "Detected 'pulldb-client' package. Removing..."
    apt-get remove -y pulldb-client
    apt-get purge -y pulldb-client
fi

# 2. Clean up Manual Server Installations
SERVICES=("pulldb-worker.service" "pulldb-api.service" "pulldb-web.service" "pulldb-retention.timer" "pulldb-retention.service" "pulldb-worker@*.service")
PATHS=("/opt/pulldb" "/opt/pulldb.service")

for SERVICE in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$SERVICE" || systemctl is-enabled --quiet "$SERVICE"; then
        echo "Stopping and disabling $SERVICE..."
        systemctl stop "$SERVICE" || true
        systemctl disable "$SERVICE" || true
        rm -f "/etc/systemd/system/$SERVICE"
        systemctl daemon-reload
    fi
done

for PATH_DIR in "${PATHS[@]}"; do
    if [ -d "$PATH_DIR" ]; then
        echo "Removing directory: $PATH_DIR"
        rm -rf "$PATH_DIR"
    fi
done

# 3. Clean up Manual Client Installations
CLIENT_PATHS=("/opt/pulldb.client")
BIN_LINKS=("/usr/local/bin/pulldb")

for PATH_DIR in "${CLIENT_PATHS[@]}"; do
    if [ -d "$PATH_DIR" ]; then
        echo "Removing directory: $PATH_DIR"
        rm -rf "$PATH_DIR"
    fi
done

for LINK in "${BIN_LINKS[@]}"; do
    if [ -L "$LINK" ] || [ -f "$LINK" ]; then
        echo "Removing binary link: $LINK"
        rm -f "$LINK"
    fi
done

# Remove pulldb CA certificate from system trust store
if [ -f /usr/local/share/ca-certificates/pulldb-service.crt ]; then
    echo "Removing pulldb CA certificate..."
    rm -f /usr/local/share/ca-certificates/pulldb-service.crt
    update-ca-certificates 2>/dev/null || true
fi

# Remove sudoers rule
rm -f /etc/sudoers.d/pulldb-admin 2>/dev/null || true

# Remove systemd unit symlinks
rm -f /etc/systemd/system/pulldb-*.service 2>/dev/null || true
rm -f /etc/systemd/system/pulldb-*.timer 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true

echo "Cleanup complete. All pullDB components should be removed."
