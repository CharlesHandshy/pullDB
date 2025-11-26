#!/usr/bin/env bash
set -euo pipefail

# Uninstall script for pullDB
# Removes systemd service, virtualenv, and application files.
# PRESERVES: .env and .aws/config files (contain user configuration)

INSTALL_PREFIX="/opt/pulldb.service"
WORKER_SERVICE="pulldb-worker.service"
API_SERVICE="pulldb-api.service"

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root."
   exit 1
fi

echo "Stopping services..."
systemctl stop $WORKER_SERVICE || true
systemctl disable $WORKER_SERVICE || true
systemctl stop $API_SERVICE || true
systemctl disable $API_SERVICE || true
rm -f /etc/systemd/system/$WORKER_SERVICE /etc/systemd/system/$API_SERVICE
systemctl daemon-reload

# Check for preserved files
PRESERVED_FILES=()
if [[ -f "${INSTALL_PREFIX}/.env" ]]; then
    PRESERVED_FILES+=("${INSTALL_PREFIX}/.env")
fi
if [[ -f "${INSTALL_PREFIX}/.aws/config" ]]; then
    PRESERVED_FILES+=("${INSTALL_PREFIX}/.aws/config")
fi

if [[ ${#PRESERVED_FILES[@]} -gt 0 ]]; then
    echo ""
    echo "The following configuration files will be PRESERVED:"
    for f in "${PRESERVED_FILES[@]}"; do
        echo "  - $f"
    done
    echo ""
fi

echo "Removing installation directory $INSTALL_PREFIX..."
read -p "Remove application files in $INSTALL_PREFIX? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Remove everything EXCEPT .env and .aws/config
    cd "$INSTALL_PREFIX" 2>/dev/null || { echo "Install directory not found."; exit 0; }
    
    # Remove known directories
    rm -rf venv dist scripts systemd logs work 2>/dev/null || true
    
    # Remove known files (but not .env)
    rm -f AWS-SETUP.md SERVICE-README.md env.example aws.config.example 2>/dev/null || true
    
    # Remove .aws directory contents except config
    if [[ -d ".aws" ]]; then
        find .aws -type f ! -name 'config' -delete 2>/dev/null || true
        # Remove .aws if only config remains and we're not preserving it
        if [[ ! -f ".aws/config" ]]; then
            rm -rf .aws 2>/dev/null || true
        fi
    fi
    
    # Check if directory is now empty (or only has preserved files)
    REMAINING=$(find . -type f ! -name '.env' ! -path './.aws/config' 2>/dev/null | wc -l)
    if [[ $REMAINING -eq 0 ]]; then
        if [[ ${#PRESERVED_FILES[@]} -eq 0 ]]; then
            # Nothing preserved, remove the whole directory
            cd /
            rm -rf "$INSTALL_PREFIX"
            echo "Removed $INSTALL_PREFIX completely."
        else
            echo "Removed application files. Preserved configuration files remain in $INSTALL_PREFIX"
        fi
    else
        echo "Removed most files. Some files remain in $INSTALL_PREFIX"
    fi
else
    echo "Skipped removing $INSTALL_PREFIX"
fi

echo ""
echo "Uninstall complete."
if [[ ${#PRESERVED_FILES[@]} -gt 0 ]]; then
    echo ""
    echo "To remove preserved configuration files, run:"
    echo "  sudo rm -rf $INSTALL_PREFIX"
fi
