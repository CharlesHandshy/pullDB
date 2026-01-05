#!/usr/bin/env bash
# =============================================================================
# Download Embedded Python for pulldb-client
# =============================================================================
# Downloads python-build-standalone (stripped) for embedding in the client deb.
# Only supports x86_64/amd64 architecture.
#
# Source: https://github.com/astral-sh/python-build-standalone
# =============================================================================
set -euo pipefail

# Configuration
RELEASE="20251217"
PYTHON_VERSION="3.12.12"
ARCH="x86_64"
TRIPLE="${ARCH}-unknown-linux-gnu"
VARIANT="install_only_stripped"

# Expected SHA256 for verification
EXPECTED_SHA256="9f5474351378aeca746ee8a2ff3b187edec71d791ef92827eca14ab5b0e15441"

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${PROJECT_ROOT}/build/python-embedded"
TARBALL_NAME="cpython-${PYTHON_VERSION}+${RELEASE}-${TRIPLE}-${VARIANT}.tar.gz"
DOWNLOAD_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${RELEASE}/${TARBALL_NAME}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Check if already downloaded and extracted
if [[ -x "${OUTPUT_DIR}/python/bin/python3" ]]; then
    EXISTING_VERSION=$("${OUTPUT_DIR}/python/bin/python3" --version 2>&1 || echo "unknown")
    log_info "Embedded Python already present: ${EXISTING_VERSION}"
    log_info "To re-download, remove: ${OUTPUT_DIR}"
    exit 0
fi

log_info "Downloading Python ${PYTHON_VERSION} (${VARIANT}) for ${ARCH}..."
log_info "URL: ${DOWNLOAD_URL}"

# Create output directory
mkdir -p "${OUTPUT_DIR}"
cd "${OUTPUT_DIR}"

# Download tarball
TARBALL_PATH="${OUTPUT_DIR}/${TARBALL_NAME}"
if [[ -f "${TARBALL_PATH}" ]]; then
    log_info "Tarball already downloaded, verifying..."
else
    log_info "Downloading (~32MB)..."
    curl -L --progress-bar -o "${TARBALL_PATH}" "${DOWNLOAD_URL}"
fi

# Verify SHA256
log_info "Verifying SHA256 checksum..."
ACTUAL_SHA256=$(sha256sum "${TARBALL_PATH}" | cut -d' ' -f1)

if [[ "${ACTUAL_SHA256}" != "${EXPECTED_SHA256}" ]]; then
    log_error "SHA256 mismatch!"
    log_error "Expected: ${EXPECTED_SHA256}"
    log_error "Actual:   ${ACTUAL_SHA256}"
    rm -f "${TARBALL_PATH}"
    exit 1
fi
log_info "SHA256 verified ✓"

# Extract (tarball extracts to 'python/' directory)
log_info "Extracting..."
tar -xzf "${TARBALL_PATH}"

# Verify extraction
if [[ ! -x "${OUTPUT_DIR}/python/bin/python3" ]]; then
    log_error "Extraction failed - python3 binary not found"
    exit 1
fi

# Show version
PYTHON_INSTALLED=$("${OUTPUT_DIR}/python/bin/python3" --version 2>&1)
log_info "Extracted: ${PYTHON_INSTALLED}"

# Clean up tarball to save space
rm -f "${TARBALL_PATH}"

log_info "Embedded Python ready at: ${OUTPUT_DIR}/python/"
log_info "Size: $(du -sh "${OUTPUT_DIR}/python" | cut -f1)"
