#!/bin/bash
set -e

echo "=== pullDB System Installer ==="
echo "1. Install Server (Service)"
echo "2. Install Client (CLI)"
echo "3. Install Both"
echo "4. Exit"
read -p "Select an option [1-4]: " OPTION

INSTALL_SERVER=false
INSTALL_CLIENT=false

case $OPTION in
    1)
        INSTALL_SERVER=true
        ;;
    2)
        INSTALL_CLIENT=true
        ;;
    3)
        INSTALL_SERVER=true
        INSTALL_CLIENT=true
        ;;
    4)
        exit 0
        ;;
    *)
        echo "Invalid option."
        exit 1
        ;;
esac

# Configuration for Server
if [ "$INSTALL_SERVER" = true ]; then
    read -p "Enter service user [default: pulldb_service]: " INPUT_USER
    export SERVICE_USER=${INPUT_USER:-pulldb_service}
    echo "Service user set to: $SERVICE_USER"
fi

# Build packages
echo "Building packages..."
if [ "$INSTALL_SERVER" = true ]; then
    make server
fi

if [ "$INSTALL_CLIENT" = true ]; then
    make client
fi

# Install Server
if [ "$INSTALL_SERVER" = true ]; then
    echo "--- Installing Server ---"
    SERVER_DEB=$(ls pulldb_*.deb | head -n 1)
    if [ -z "$SERVER_DEB" ]; then
        echo "Error: Server package not found."
        exit 1
    fi
    
    sudo dpkg -i "$SERVER_DEB"
    sudo apt-get install -f -y
    
    echo "Server installation and configuration complete."
fi

# Install Client
if [ "$INSTALL_CLIENT" = true ]; then
    echo "--- Installing Client ---"
    CLIENT_DEB=$(ls pulldb-client_*.deb | head -n 1)
    if [ -z "$CLIENT_DEB" ]; then
        echo "Error: Client package not found."
        exit 1
    fi
    sudo dpkg -i "$CLIENT_DEB"
    sudo apt-get install -f -y
fi

echo "Installation Complete."
