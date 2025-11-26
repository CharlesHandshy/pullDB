#!/bin/bash
set -e

echo "Starting full build..."

# Check for make
if command -v make &> /dev/null; then
    make all
else
    echo "Make not found, running scripts manually..."
    ./scripts/build_client_package.sh
    
    echo "Building Server Package..."
    pip install --quiet build --break-system-packages || pip install --quiet build
    python3 -m build .
    ./scripts/build_deb.sh
fi

echo "Build complete."
