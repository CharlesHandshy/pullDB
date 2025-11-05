#!/usr/bin/env bash
set -euo pipefail

# Derive version from control file to avoid manual drift.
VERSION="$(grep -E '^Version:' packaging/debian/control | awk '{print $2}')"
if [[ -z "${VERSION}" ]]; then
	echo "[ERROR] Failed to extract Version from packaging/debian/control" >&2
	exit 1
fi
ARCH="amd64"
PKGNAME="pulldb_${VERSION}_${ARCH}.deb"

WORKDIR="build/pulldb"
DEBIAN_DIR="$WORKDIR/DEBIAN"

rm -rf build
mkdir -p "$DEBIAN_DIR"

cp packaging/debian/control "$DEBIAN_DIR/control"
cp packaging/debian/postinst "$DEBIAN_DIR/postinst"
cp packaging/debian/prerm "$DEBIAN_DIR/prerm"
cp packaging/debian/postrm "$DEBIAN_DIR/postrm"
chmod 0755 "$DEBIAN_DIR/postinst" "$DEBIAN_DIR/prerm" "$DEBIAN_DIR/postrm"

# Lay down application skeleton under /opt/pulldb (installed path)
APP_ROOT="$WORKDIR/opt/pulldb"
mkdir -p "$APP_ROOT/scripts"
cp scripts/install_pulldb.sh "$APP_ROOT/scripts/"
cp packaging/systemd/pulldb-worker.service "$APP_ROOT/scripts/"

dpkg-deb --build "$WORKDIR" "$PKGNAME"
echo "Built $PKGNAME (Version=${VERSION})"
