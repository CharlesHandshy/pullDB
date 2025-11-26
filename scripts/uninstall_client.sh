#!/bin/bash
set -e

echo "Uninstalling pullDB client..."

# Try uninstall
if pip uninstall -y pulldb-client 2>&1 | grep -q "externally-managed-environment"; then
    echo "Detected externally managed environment. Attempting uninstall with --break-system-packages..."
    pip uninstall -y --break-system-packages pulldb-client
else
    # If failed, try again to show error or just assume it worked if it didn't complain about external env
    if [ $? -ne 0 ]; then
         pip uninstall -y pulldb-client
    fi
fi

echo "Uninstallation complete."
