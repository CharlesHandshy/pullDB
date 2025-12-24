#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# pullDB Client Package Builder
# =============================================================================
# Builds the lightweight client-only .deb package (CLI only, no services).
#
# Uses the SAME wheel as the server package (from dist/).
# Version is derived from pyproject.toml (single source of truth).
# GitHub Actions can override via PULLDB_VERSION environment variable.
# =============================================================================

# Get version from environment (CI) or pyproject.toml (local build)
if [[ -n "${PULLDB_VERSION:-}" ]]; then
    VERSION="${PULLDB_VERSION}"
    echo "Using version from environment: ${VERSION}"
elif [[ -f "pyproject.toml" ]]; then
    VERSION="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed 's/.*=\s*"\([^"]*\)".*/\1/')"
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

WORKDIR="build/pulldb-client"
DEBIAN_DIR="$WORKDIR/DEBIAN"

rm -rf "$WORKDIR"
mkdir -p "$DEBIAN_DIR"

# Copy control file and inject version
cp packaging/debian_client/control "$DEBIAN_DIR/control"
sed -i "s/^Version:.*/Version: ${VERSION}/" "$DEBIAN_DIR/control"

cp packaging/debian_client/postinst "$DEBIAN_DIR/postinst"
cp packaging/debian_client/postrm "$DEBIAN_DIR/postrm"
chmod 0755 "$DEBIAN_DIR/postinst" "$DEBIAN_DIR/postrm"

# Lay down application skeleton under /opt/pulldb.client
APP_ROOT="$WORKDIR/opt/pulldb.client"
mkdir -p "$APP_ROOT/dist"

# Use the wheel from dist/ (built by main build process)
# This is the SAME wheel used by the server package
if compgen -G "dist/pulldb-*.whl" > /dev/null; then
    cp dist/pulldb-*.whl "$APP_ROOT/dist/"
else
    echo "[ERROR] No wheel file found in dist/." >&2
    echo "Run 'python3 -m build' or 'make server' first to build the wheel." >&2
    exit 1
fi

# Install documentation to /usr/share/doc/pulldb-client
DOC_DIR="$WORKDIR/usr/share/doc/pulldb-client"
mkdir -p "$DOC_DIR"
cp packaging/CLIENT-README.md "$DOC_DIR/"
if [ -f LICENSE ]; then
    cp LICENSE "$DOC_DIR/copyright"
else
    echo "Copyright 2025 PestRoutes Engineering" > "$DOC_DIR/copyright"
fi

dpkg-deb --build "$WORKDIR" "$PKGNAME"
echo "Built $PKGNAME (Version=${VERSION})"

# GPG sign the package (if GPG_KEY_ID is set)
if [[ -n "${GPG_KEY_ID:-}" ]]; then
    if command -v dpkg-sig &>/dev/null; then
        echo "Signing package with GPG key: ${GPG_KEY_ID}"
        dpkg-sig --sign builder -k "${GPG_KEY_ID}" "$PKGNAME"
        echo "Package signed successfully"
    else
        echo "[WARNING] dpkg-sig not found, skipping package signing"
        echo "Install with: sudo apt-get install dpkg-sig"
    fi
else
    echo "[INFO] GPG_KEY_ID not set, skipping package signing"
fi
