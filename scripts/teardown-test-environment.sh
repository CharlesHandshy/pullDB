#!/usr/bin/env bash
set -euo pipefail

# Configuration matching setup-test-environment.sh
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ENV_DIR="${PROJECT_ROOT}/test-env"
# Database name follows pattern: pulldb_<username>
TEST_DB_USER_BASE="${SUDO_USER:-$USER}"
TEST_DB_NAME="pulldb_${TEST_DB_USER_BASE}"
TEST_DB_USER="pullDbService"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Check for root if needed for MySQL
if [[ $EUID -ne 0 ]]; then
    info "This script might need sudo for MySQL operations if you don't have access."
fi

info "Tearing down test environment at ${TEST_ENV_DIR}..."

# Remove directory
if [[ -d "$TEST_ENV_DIR" ]]; then
    rm -rf "$TEST_ENV_DIR"
    info "Removed test environment directory."
else
    info "Test environment directory not found."
fi

# Drop database
info "Dropping MySQL database and user..."
if command -v mysql >/dev/null; then
    # Try without sudo first, then with sudo if failed? 
    # Usually root access is needed to drop users.
    # We'll assume the user runs this script with sudo if needed, or we use sudo inside.
    
    MYSQL_CMD="mysql -u root"
    if [[ $EUID -ne 0 ]]; then
        MYSQL_CMD="sudo mysql -u root"
    fi
    
    $MYSQL_CMD <<EOF
DROP DATABASE IF EXISTS ${TEST_DB_NAME};
DROP USER IF EXISTS '${TEST_DB_USER}'@'localhost';
EOF
    info "Database and user dropped."
else
    error "mysql command not found. Skipping database cleanup."
fi

info "Teardown complete."
