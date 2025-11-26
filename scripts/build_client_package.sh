#!/bin/bash
set -e

# FAIL HARD: Ensure we are in the project root
if [ ! -f "pyproject.toml" ]; then
    echo "Error: Must run from project root"
    exit 1
fi

BUILD_DIR="build_client"
DIST_DIR="dist_client_package"
SRC_DIR="$BUILD_DIR/src/pulldb"

# Clean up previous builds
rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$SRC_DIR/cli"
mkdir -p "$DIST_DIR"

echo "Setting up client package structure..."

# Copy minimal source files
cp pulldb/__init__.py "$SRC_DIR/"
cp pulldb/cli/__init__.py "$SRC_DIR/cli/"
cp pulldb/cli/main.py "$SRC_DIR/cli/"
cp pulldb/cli/parse.py "$SRC_DIR/cli/"

# Create README
cat > "$BUILD_DIR/README.md" <<EOF
# pullDB Client

This is the standalone client CLI for pullDB.

## Installation

Run the provided install script:
./install.sh
EOF

# Create pyproject.toml
cat > "$BUILD_DIR/pyproject.toml" <<EOF
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "pulldb-client"
version = "0.0.1"
description = "Client CLI for pullDB"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "click>=8.1.0",
    "requests>=2.32.0",
]

[project.scripts]
pulldb = "pulldb.cli.main:main"

[tool.setuptools.packages.find]
where = ["src"]
EOF

echo "Building client wheel..."
# Ensure build is installed
if [ -d "test-env/venv" ]; then
    PYTHON_CMD="test-env/venv/bin/python"
    $PYTHON_CMD -m pip install --quiet build
else
    PYTHON_CMD="python3"
    $PYTHON_CMD -m pip install --quiet build --break-system-packages
fi

# Build the wheel
$PYTHON_CMD -m build "$BUILD_DIR" --outdir "$DIST_DIR"

# Copy install/uninstall/upgrade scripts
cp scripts/install_client.sh "$DIST_DIR/install.sh"
cp scripts/uninstall_client.sh "$DIST_DIR/uninstall.sh"
cp scripts/upgrade_client.sh "$DIST_DIR/upgrade.sh"
chmod +x "$DIST_DIR/install.sh" "$DIST_DIR/uninstall.sh" "$DIST_DIR/upgrade.sh"

# Create a tarball of the distribution directory
echo "Creating installer archive..."
tar -czf pulldb-client-installer.tar.gz -C "$DIST_DIR" .
mv pulldb-client-installer.tar.gz "$DIST_DIR/"

echo "Client package created in $DIST_DIR"
ls -l "$DIST_DIR"
