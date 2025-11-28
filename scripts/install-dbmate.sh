#!/usr/bin/env bash
# install-dbmate.sh - Download and install dbmate binary
#
# Installs dbmate, a lightweight database migration tool, to the pullDB
# installation directory. Supports Linux amd64/arm64 architectures.
#
# Usage:
#   sudo ./install-dbmate.sh                    # Install to default location
#   PULLDB_INSTALL_PREFIX=/custom ./install-dbmate.sh  # Custom location

set -euo pipefail

# === Configuration ===
DBMATE_VERSION="${DBMATE_VERSION:-2.24.1}"
INSTALL_PREFIX="${PULLDB_INSTALL_PREFIX:-/opt/pulldb.service}"
BIN_DIR="${INSTALL_PREFIX}/bin"

# Detect architecture
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)
        DBMATE_ARCH="amd64"
        ;;
    aarch64|arm64)
        DBMATE_ARCH="arm64"
        ;;
    *)
        echo "[ERROR] Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
if [[ "$OS" != "linux" ]]; then
    echo "[ERROR] This script only supports Linux. Found: $OS"
    exit 1
fi

DBMATE_URL="https://github.com/amacneil/dbmate/releases/download/v${DBMATE_VERSION}/dbmate-${OS}-${DBMATE_ARCH}"
DBMATE_BIN="${BIN_DIR}/dbmate"

# === Functions ===
info() { echo "[INFO] $*"; }
error() { echo "[ERROR] $*" >&2; }

# === Main ===
info "Installing dbmate v${DBMATE_VERSION} for ${OS}-${DBMATE_ARCH}"

# Create bin directory
mkdir -p "$BIN_DIR"

# Download dbmate
info "Downloading from: $DBMATE_URL"
if command -v curl &>/dev/null; then
    curl -fsSL "$DBMATE_URL" -o "$DBMATE_BIN"
elif command -v wget &>/dev/null; then
    wget -q "$DBMATE_URL" -O "$DBMATE_BIN"
else
    error "Neither curl nor wget available. Please install one."
    exit 1
fi

# Make executable
chmod +x "$DBMATE_BIN"

# Verify installation
if "$DBMATE_BIN" --version &>/dev/null; then
    info "Successfully installed: $("$DBMATE_BIN" --version)"
    info "Location: $DBMATE_BIN"
else
    error "Installation verification failed"
    exit 1
fi
