#!/bin/bash
set -e

# pullDB Client Installer
# Installs the pullDB CLI client for the pulldb_service user
#
# Usage: sudo ./install_client.sh [wheel_file]
#        sudo ./install_client.sh  (finds wheel in current directory)

INSTALL_PREFIX="/opt/pulldb.client"
BIN_DIR="/usr/local/bin"
SYSTEM_USER="pulldb_service"
SYSTEM_GROUP="pulldb_service"

# Check for root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root (use sudo)."
    exit 1
fi

# Check for python3
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not found."
    exit 1
fi

# Find wheel file
if [ -n "$1" ]; then
    WHEEL_FILE="$1"
else
    WHEEL_FILE=$(ls *.whl 2>/dev/null | head -n 1)
fi

if [ -z "$WHEEL_FILE" ] || [ ! -f "$WHEEL_FILE" ]; then
    echo "Error: No wheel file found. Provide path as argument or run from directory with .whl file."
    exit 1
fi

echo "Installing pullDB client from $WHEEL_FILE..."

# Create user/group if needed
if ! getent group "${SYSTEM_GROUP}" >/dev/null 2>&1; then
    addgroup --system "${SYSTEM_GROUP}"
fi
if ! id -u "${SYSTEM_USER}" >/dev/null 2>&1; then
    adduser --system --ingroup "${SYSTEM_GROUP}" --home "${INSTALL_PREFIX}" --shell /usr/sbin/nologin "${SYSTEM_USER}"
fi

# Create install directory
mkdir -p "${INSTALL_PREFIX}/dist"
cp "$WHEEL_FILE" "${INSTALL_PREFIX}/dist/"

# Create venv
if [ ! -d "${INSTALL_PREFIX}/venv" ]; then
    python3 -m venv "${INSTALL_PREFIX}/venv"
fi

# Install package
"${INSTALL_PREFIX}/venv/bin/pip" install --quiet --upgrade pip wheel
"${INSTALL_PREFIX}/venv/bin/pip" install --quiet --upgrade "${INSTALL_PREFIX}/dist"/*.whl

# Set ownership
chown -R "${SYSTEM_USER}:${SYSTEM_GROUP}" "${INSTALL_PREFIX}"

# Create symlink
ln -sf "${INSTALL_PREFIX}/venv/bin/pulldb" "${BIN_DIR}/pulldb"

echo ""
echo "Installation complete."
echo "  Install directory: ${INSTALL_PREFIX}"
echo "  Binary: ${BIN_DIR}/pulldb"
echo "  User: ${SYSTEM_USER}"
echo ""
echo "Run 'pulldb --help' to verify."
