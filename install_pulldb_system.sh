#!/usr/bin/env bash
# =============================================================================
# pullDB System Installer — entry point
# =============================================================================
# This script delegates to install-pulldb-server.sh (server) or
# install-pulldb-client.sh (client), both of which are one-step installers.
#
# Usage:
#   sudo ./install_pulldb_system.sh
# =============================================================================
set -euo pipefail

echo "=== pullDB System Installer ==="
echo "1. Install Server (Service + API + Web UI)"
echo "2. Install Client (CLI only)"
echo "3. Install Both"
echo "4. Exit"
read -r -p "Select an option [1-4]: " OPTION

INSTALL_SERVER=false
INSTALL_CLIENT=false

case $OPTION in
    1) INSTALL_SERVER=true ;;
    2) INSTALL_CLIENT=true ;;
    3) INSTALL_SERVER=true; INSTALL_CLIENT=true ;;
    4) exit 0 ;;
    *) echo "Invalid option."; exit 1 ;;
esac

# Locate packages in the current directory
SERVER_DEB=$(ls -t pulldb_*.deb 2>/dev/null | head -n 1 || true)
CLIENT_DEB=$(ls -t pulldb-client_*.deb 2>/dev/null | head -n 1 || true)

if [[ "$INSTALL_SERVER" == true ]]; then
    if [[ -z "$SERVER_DEB" ]]; then
        echo "Error: No server package found (pulldb_*.deb)."
        echo "Build it first with: make server"
        exit 1
    fi

    if [[ ! -x "./install-pulldb-server.sh" ]]; then
        echo "Error: install-pulldb-server.sh not found or not executable."
        exit 1
    fi

    echo ""
    echo "--- Installing Server: $SERVER_DEB ---"
    ./install-pulldb-server.sh "$SERVER_DEB"
fi

if [[ "$INSTALL_CLIENT" == true ]]; then
    if [[ -z "$CLIENT_DEB" ]]; then
        echo "Error: No client package found (pulldb-client_*.deb)."
        echo "Build it first with: make client"
        exit 1
    fi

    if [[ ! -x "./install-pulldb-client.sh" ]]; then
        echo "Error: install-pulldb-client.sh not found or not executable."
        exit 1
    fi

    echo ""
    echo "--- Installing Client: $CLIENT_DEB ---"
    ./install-pulldb-client.sh "$CLIENT_DEB"
fi

echo ""
echo "Installation complete."
