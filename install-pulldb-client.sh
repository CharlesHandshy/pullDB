#!/usr/bin/env bash
# =============================================================================
# pullDB Client Installer
# =============================================================================
# Installs Python 3.12 from deadsnakes PPA (preserves system Python) and
# installs the pulldb-client deb package.
#
# Usage:
#   sudo ./install-pulldb-client.sh [path/to/pulldb-client_*.deb]
#
# If no deb path provided, looks for pulldb-client_*.deb in current directory.
# =============================================================================
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Check root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (use sudo)"
    exit 1
fi

# Find deb package
DEB_PATH="${1:-}"
if [[ -z "$DEB_PATH" ]]; then
    DEB_PATH=$(ls pulldb-client_*.deb 2>/dev/null | head -n 1 || true)
fi

if [[ -z "$DEB_PATH" || ! -f "$DEB_PATH" ]]; then
    log_error "No pulldb-client deb package found."
    echo "Usage: sudo $0 [path/to/pulldb-client_*.deb]"
    exit 1
fi

log_info "Installing pulldb-client from: $DEB_PATH"

# =============================================================================
# Step 1: Check/Install Python 3.12
# =============================================================================
log_info "Checking Python 3.12..."

if command -v python3.12 &>/dev/null; then
    PYTHON_VERSION=$(python3.12 --version 2>&1)
    log_info "Python 3.12 already installed: $PYTHON_VERSION"
else
    log_info "Python 3.12 not found. Installing from deadsnakes PPA..."
    
    # Detect Ubuntu version
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        log_info "Detected: $NAME $VERSION_ID"
    fi
    
    # Install prerequisites
    apt-get update -qq
    apt-get install -y software-properties-common
    
    # Add deadsnakes PPA
    log_info "Adding deadsnakes PPA..."
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
    
    # Install Python 3.12
    log_info "Installing Python 3.12..."
    apt-get install -y python3.12 python3.12-venv
    
    log_info "Python 3.12 installed successfully"
fi

# Verify system python is untouched
SYSTEM_PYTHON=$(python3 --version 2>&1)
log_info "System Python (unchanged): $SYSTEM_PYTHON"
log_info "pulldb will use: $(python3.12 --version 2>&1)"

# =============================================================================
# Step 2: Install pulldb-client deb package
# =============================================================================
log_info "Installing pulldb-client package..."

# Install dependencies and package
apt-get install -y -f  # Fix any broken dependencies first
dpkg -i "$DEB_PATH" || apt-get install -y -f

# =============================================================================
# Step 3: Verify installation
# =============================================================================
log_info "Verifying installation..."

if command -v pulldb &>/dev/null; then
    PULLDB_VERSION=$(pulldb --version 2>&1 || echo "unknown")
    log_info "pulldb CLI installed: $PULLDB_VERSION"
else
    log_error "pulldb command not found after installation"
    exit 1
fi

# =============================================================================
# Done
# =============================================================================
echo ""
log_info "=============================================="
log_info "pulldb-client installed successfully!"
log_info "=============================================="
echo ""
echo "  System Python: $SYSTEM_PYTHON (unchanged)"
echo "  pulldb Python: $(python3.12 --version 2>&1)"
echo "  pulldb CLI:    $(which pulldb)"
echo ""
echo "  Run 'pulldb --help' to get started."
echo ""
