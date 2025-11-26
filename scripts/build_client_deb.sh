#!/usr/bin/env bash
set -euo pipefail

# Derive version from control file
VERSION="$(grep -E '^Version:' packaging/debian_client/control | awk '{print $2}')"
if [[ -z "${VERSION}" ]]; then
	echo "[ERROR] Failed to extract Version from packaging/debian_client/control" >&2
	exit 1
fi
ARCH="amd64"
PKGNAME="pulldb-client_${VERSION}_${ARCH}.deb"

WORKDIR="build/pulldb-client"
DEBIAN_DIR="$WORKDIR/DEBIAN"

rm -rf "$WORKDIR"
mkdir -p "$DEBIAN_DIR"

cp packaging/debian_client/control "$DEBIAN_DIR/control"
cp packaging/debian_client/postinst "$DEBIAN_DIR/postinst"
cp packaging/debian_client/postrm "$DEBIAN_DIR/postrm"
chmod 0755 "$DEBIAN_DIR/postinst" "$DEBIAN_DIR/postrm"

# Lay down application skeleton under /opt/pulldb.client
APP_ROOT="$WORKDIR/opt/pulldb.client"
mkdir -p "$APP_ROOT/dist"

# Build the wheel first (ensure we have the latest)
# We reuse the build_client_package logic but just grab the wheel
# Or we can just assume 'make client' ran. 
# Let's assume the wheel is in dist_client_package/ from a previous step or we build it here.
# To be safe, let's build the wheel here using the existing script but we need to extract it.
# Actually, let's just look for it in dist_client_package/ or build it.

if [ ! -d "dist_client_package" ]; then
    echo "Building client wheel..."
    ./scripts/build_client_package.sh
fi

# Copy the wheel file
if compgen -G "dist_client_package/*.whl" > /dev/null; then
    cp dist_client_package/*.whl "$APP_ROOT/dist/"
else
    echo "[ERROR] No wheel file found in dist_client_package/. Run './scripts/build_client_package.sh' first." >&2
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
