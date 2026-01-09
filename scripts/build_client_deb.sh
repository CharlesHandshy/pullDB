#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# pullDB Client Package Builder
# =============================================================================
# Builds the lightweight client-only .deb package (CLI only, no services).
# Includes embedded Python 3.12 for Ubuntu 20.04 compatibility.
#
# Uses the SAME wheel as the server package (from dist/).
# Version is derived from pyproject.toml (single source of truth).
# GitHub Actions can override via PULLDB_VERSION environment variable.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Get version from environment (CI) or pyproject.toml (local build)
if [[ -n "${PULLDB_VERSION:-}" ]]; then
    VERSION="${PULLDB_VERSION}"
    echo "Using version from environment: ${VERSION}"
elif [[ -f "${PROJECT_ROOT}/pyproject.toml" ]]; then
    VERSION="$(grep -E '^version\s*=' "${PROJECT_ROOT}/pyproject.toml" | head -1 | sed 's/.*=\s*"\([^"]*\)".*/\1/')"
    if [[ -z "${VERSION}" ]]; then
        echo "[ERROR] Failed to extract version from pyproject.toml" >&2
        exit 1
    fi
    echo "Using version from pyproject.toml: ${VERSION}"
else
    echo "[ERROR] No version source found (set PULLDB_VERSION or ensure pyproject.toml exists)" >&2
    exit 1
fi

ARCH="amd64"
PKGNAME="pulldb-client_${VERSION}_${ARCH}.deb"

WORKDIR="${PROJECT_ROOT}/build/pulldb-client"
DEBIAN_DIR="$WORKDIR/DEBIAN"

rm -rf "$WORKDIR"
mkdir -p "$DEBIAN_DIR"

# =============================================================================
# Step 1: Download embedded Python if not present
# =============================================================================
EMBEDDED_PYTHON_DIR="${PROJECT_ROOT}/build/python-embedded/python"
if [[ ! -x "${EMBEDDED_PYTHON_DIR}/bin/python3" ]]; then
    echo "=== Downloading embedded Python ==="
    "${SCRIPT_DIR}/download_embedded_python.sh"
fi

if [[ ! -x "${EMBEDDED_PYTHON_DIR}/bin/python3" ]]; then
    echo "[ERROR] Embedded Python not found after download" >&2
    exit 1
fi

EMBEDDED_PYTHON_VERSION=$("${EMBEDDED_PYTHON_DIR}/bin/python3" --version 2>&1)
echo "Embedded Python: ${EMBEDDED_PYTHON_VERSION}"

# =============================================================================
# Step 2: Prepare DEBIAN control files
# =============================================================================
cp "${PROJECT_ROOT}/packaging/debian_client/control" "$DEBIAN_DIR/control"
sed -i "s/^Version:.*/Version: ${VERSION}/" "$DEBIAN_DIR/control"

cp "${PROJECT_ROOT}/packaging/debian_client/preinst" "$DEBIAN_DIR/preinst"
cp "${PROJECT_ROOT}/packaging/debian_client/postinst" "$DEBIAN_DIR/postinst"
cp "${PROJECT_ROOT}/packaging/debian_client/postrm" "$DEBIAN_DIR/postrm"
chmod 0755 "$DEBIAN_DIR/preinst" "$DEBIAN_DIR/postinst" "$DEBIAN_DIR/postrm"

# =============================================================================
# Step 3: Build client-specific wheel (minimal, no server components)
# =============================================================================
echo "=== Building client-specific wheel ==="

# Build a minimal wheel using pyproject-client.toml
# Strategy: Create a clean temp directory with only client files and client config
# This works because we put pyproject-client.toml as pyproject.toml in the temp dir
mkdir -p "${PROJECT_ROOT}/dist-client"

# Create temporary build directory
TEMP_BUILD="${PROJECT_ROOT}/build/temp-client-wheel"
rm -rf "${TEMP_BUILD}"
mkdir -p "${TEMP_BUILD}/pulldb/cli"

# Copy only client-needed modules (minimal CLI only)
cp "${PROJECT_ROOT}/pulldb/__init__.py" "${TEMP_BUILD}/pulldb/"
cp "${PROJECT_ROOT}/pulldb/cli/__init__.py" "${TEMP_BUILD}/pulldb/cli/"
cp "${PROJECT_ROOT}/pulldb/cli/__main__.py" "${TEMP_BUILD}/pulldb/cli/"
cp "${PROJECT_ROOT}/pulldb/cli/main.py" "${TEMP_BUILD}/pulldb/cli/"
cp "${PROJECT_ROOT}/pulldb/cli/auth.py" "${TEMP_BUILD}/pulldb/cli/"
cp "${PROJECT_ROOT}/pulldb/cli/parse.py" "${TEMP_BUILD}/pulldb/cli/"

# Copy client-specific config as pyproject.toml (with version substitution)
sed "s/^version = .*/version = \"${VERSION}\"/" \
    "${PROJECT_ROOT}/pyproject-client.toml" > "${TEMP_BUILD}/pyproject.toml"

# Build the wheel in the temp directory
cd "${TEMP_BUILD}"
python3 -m build --wheel --outdir="${PROJECT_ROOT}/dist-client"
cd "${PROJECT_ROOT}"

# Use client wheel if available, otherwise use server wheel
CLIENT_WHEEL=$(ls "${PROJECT_ROOT}"/dist-client/pulldb*client*.whl 2>/dev/null | head -1)
if [[ -n "$CLIENT_WHEEL" ]]; then
    echo "Using client-specific wheel: $(basename "$CLIENT_WHEEL")"
    WHEEL_SOURCE="${PROJECT_ROOT}/dist-client"
    WHEEL_PATTERN="pulldb*client*.whl"
else
    echo "[WARNING] Client wheel not found, using server wheel"
    WHEEL_SOURCE="${PROJECT_ROOT}/dist"
    WHEEL_PATTERN="pulldb-*.whl"
fi

# =============================================================================
# Step 4: Lay down application files
# =============================================================================
APP_ROOT="$WORKDIR/opt/pulldb.client"
mkdir -p "$APP_ROOT/dist"

# Copy embedded Python
echo "Copying embedded Python (~75MB)..."
cp -r "${EMBEDDED_PYTHON_DIR}" "$APP_ROOT/python"

# Copy wheel
if compgen -G "${WHEEL_SOURCE}/${WHEEL_PATTERN}" > /dev/null; then
    cp "${WHEEL_SOURCE}"/${WHEEL_PATTERN} "$APP_ROOT/dist/"
else
    echo "[ERROR] No wheel file found." >&2
    exit 1
fi

# =============================================================================
# Step 5: Documentation
# =============================================================================
DOC_DIR="$WORKDIR/usr/share/doc/pulldb-client"
mkdir -p "$DOC_DIR"
cp "${PROJECT_ROOT}/packaging/CLIENT-README.md" "$DOC_DIR/"
if [ -f "${PROJECT_ROOT}/LICENSE" ]; then
    cp "${PROJECT_ROOT}/LICENSE" "$DOC_DIR/copyright"
else
    echo "Copyright 2025 PestRoutes Engineering" > "$DOC_DIR/copyright"
fi

# Copy installer script (for reference, less needed now with embedded Python)
cp "${PROJECT_ROOT}/packaging/install-pulldb-client.sh" "$DOC_DIR/"

# =============================================================================
# Step 6: Build package
# =============================================================================
echo "=== Building package ==="
dpkg-deb --build "$WORKDIR" "${PROJECT_ROOT}/$PKGNAME"

# Show package size
PACKAGE_SIZE=$(du -h "${PROJECT_ROOT}/$PKGNAME" | cut -f1)
echo "Built $PKGNAME (Version=${VERSION}, Size=${PACKAGE_SIZE})"

# Also copy installer script alongside the deb for convenience
cp "${PROJECT_ROOT}/packaging/install-pulldb-client.sh" "${PROJECT_ROOT}/install-pulldb-client.sh"
echo "Installer script: install-pulldb-client.sh"

# GPG sign the package (if GPG_KEY_ID is set)
if [[ -n "${GPG_KEY_ID:-}" ]]; then
    if command -v dpkg-sig &>/dev/null; then
        echo "Signing package with GPG key: ${GPG_KEY_ID}"
        dpkg-sig --sign builder -k "${GPG_KEY_ID}" "${PROJECT_ROOT}/$PKGNAME"
        echo "Package signed successfully"
    else
        echo "[WARNING] dpkg-sig not found, skipping package signing"
        echo "Install with: sudo apt-get install dpkg-sig"
    fi
else
    echo "[INFO] GPG_KEY_ID not set, skipping package signing"
fi
