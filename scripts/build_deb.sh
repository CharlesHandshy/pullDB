#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# pullDB Server Package Builder
# =============================================================================
# Builds the full server .deb package including CLI, worker, and API.
#
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
PKGNAME="pulldb_${VERSION}_${ARCH}.deb"

WORKDIR="build/pulldb"
DEBIAN_DIR="$WORKDIR/DEBIAN"

rm -rf build
mkdir -p "$DEBIAN_DIR"

# Copy control file and inject version
cp packaging/debian/control "$DEBIAN_DIR/control"
sed -i "s/^Version:.*/Version: ${VERSION}/" "$DEBIAN_DIR/control"
cp packaging/debian/postinst "$DEBIAN_DIR/postinst"
cp packaging/debian/prerm "$DEBIAN_DIR/prerm"
cp packaging/debian/postrm "$DEBIAN_DIR/postrm"

# Allow overriding the service user via environment variable
SERVICE_USER=${SERVICE_USER:-pulldb_service}
sed -i "s/SYSTEM_USER=\"pulldb_service\"/SYSTEM_USER=\"${SERVICE_USER}\"/" "$DEBIAN_DIR/postinst"
sed -i "s/SYSTEM_GROUP=\"pulldb_service\"/SYSTEM_GROUP=\"${SERVICE_USER}\"/" "$DEBIAN_DIR/postinst"

chmod 0755 "$DEBIAN_DIR/postinst" "$DEBIAN_DIR/prerm" "$DEBIAN_DIR/postrm"

# Lay down application skeleton under /opt/pulldb.service (installed path)
APP_ROOT="$WORKDIR/opt/pulldb.service"
mkdir -p "$APP_ROOT/scripts"
mkdir -p "$APP_ROOT/systemd"
mkdir -p "$APP_ROOT/dist"

# Copy install scripts
cp scripts/install_pulldb.sh "$APP_ROOT/scripts/"
cp scripts/uninstall_pulldb.sh "$APP_ROOT/scripts/"
cp scripts/upgrade_pulldb.sh "$APP_ROOT/scripts/"
cp scripts/configure_server.sh "$APP_ROOT/scripts/"
cp scripts/monitor_jobs.py "$APP_ROOT/scripts/"
cp scripts/service-validate.sh "$APP_ROOT/scripts/"
chmod +x "$APP_ROOT/scripts/"*.sh "$APP_ROOT/scripts/"*.py

# Copy systemd unit files to dedicated directory
cp packaging/systemd/pulldb-worker.service "$APP_ROOT/systemd/"
cp packaging/systemd/pulldb-api.service "$APP_ROOT/systemd/"

# Copy documentation and example config files to package root
cp docs/AWS-SETUP.md "$APP_ROOT/"
cp packaging/SERVICE-README.md "$APP_ROOT/"
cp packaging/env.example "$APP_ROOT/"
cp packaging/aws.config.example "$APP_ROOT/"

# Copy the wheel file (fail if not found)
if compgen -G "dist/pulldb-*.whl" > /dev/null; then
    cp dist/pulldb-*.whl "$APP_ROOT/dist/"
else
    echo "[ERROR] No wheel file found in dist/. Run 'make server' or 'python3 -m build' first." >&2
    exit 1
fi

# Install documentation to /usr/share/doc/pulldb
DOC_DIR="$WORKDIR/usr/share/doc/pulldb"
mkdir -p "$DOC_DIR"
cp docs/AWS-SETUP.md "$DOC_DIR/"
cp packaging/SERVICE-README.md "$DOC_DIR/"
# Create a basic copyright file if none exists (Debian policy)
if [ -f LICENSE ]; then
    cp LICENSE "$DOC_DIR/copyright"
else
    echo "Copyright 2025 PestRoutes Engineering" > "$DOC_DIR/copyright"
fi
# Compress changelog if it exists (Debian policy recommendation, but optional for internal)
if [ -f CHANGELOG.md ]; then
    cp CHANGELOG.md "$DOC_DIR/changelog"
    gzip -9 "$DOC_DIR/changelog"
fi

dpkg-deb --build "$WORKDIR" "$PKGNAME"
echo "Built $PKGNAME (Version=${VERSION})"
