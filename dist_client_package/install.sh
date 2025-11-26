#!/bin/bash
set -e

# Check for python3
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not found."
    exit 1
fi

# Check for pip
if ! command -v pip &> /dev/null && ! command -v pip3 &> /dev/null; then
    echo "Error: pip is required but not found."
    exit 1
fi

WHEEL_FILE=$(ls *.whl | head -n 1)

if [ -z "$WHEEL_FILE" ]; then
    echo "Error: No wheel file found in current directory."
    exit 1
fi

echo "Installing pullDB client from $WHEEL_FILE..."

# Try to install to user directory, handling PEP 668 if necessary
if pip install --user "$WHEEL_FILE" 2>&1 | grep -q "externally-managed-environment"; then
    echo "Detected externally managed environment. Attempting install with --break-system-packages..."
    pip install --user --break-system-packages "$WHEEL_FILE"
else
    # If the first attempt failed for other reasons, run it again to show error
    if [ $? -ne 0 ]; then
        pip install --user "$WHEEL_FILE"
    fi
fi

echo ""
echo "Installation complete."
echo "Ensure ~/.local/bin is in your PATH."
echo "Run 'pulldb --help' to verify."
