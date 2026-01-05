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
# Step 3: Lay down application files
# =============================================================================
APP_ROOT="$WORKDIR/opt/pulldb.client"
mkdir -p "$APP_ROOT/dist"

# Copy embedded Python
echo "Copying embedded Python (~75MB)..."
cp -r "${EMBEDDED_PYTHON_DIR}" "$APP_ROOT/python"

# Use the wheel from dist/ (built by main build process)
if compgen -G "${PROJECT_ROOT}/dist/pulldb-*.whl" > /dev/null; then
    cp "${PROJECT_ROOT}"/dist/pulldb-*.whl "$APP_ROOT/dist/"
else
    echo "[ERROR] No wheel file found in dist/." >&2
    echo "Run 'python3 -m build' or 'make server' first to build the wheel." >&2
    exit 1
fi

# =============================================================================
# Step 4: Documentation
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
# Step 5: Build package
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
