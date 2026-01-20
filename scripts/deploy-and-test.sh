#!/usr/bin/env bash
# =============================================================================
# pullDB Deployment and Test Script
# =============================================================================
# Goals:
#   1. Purge existing pulldb_service
#   2. make clean && make all
#   3. Install the .deb
#   4. Configure .env and .aws/config
#   5. Run tests as pulldb_service user
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_PREFIX="/opt/pulldb.service"
SERVICE_USER="pulldb_service"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

# =============================================================================
# Step 1: Purge existing installation
# =============================================================================
purge_existing() {
    log_info "Step 1: Purging existing pulldb installation..."
    
    # Stop services first
    systemctl stop pulldb-api.service 2>/dev/null || true
    systemctl stop pulldb-worker.service 2>/dev/null || true
    
    # Check what's installed
    if dpkg -l | grep -q "^ii.*pulldb "; then
        log_info "  Removing pulldb server package..."
        dpkg --purge pulldb 2>/dev/null || apt-get remove --purge -y pulldb || true
    fi
    
    if dpkg -l | grep -q "^ii.*pulldb-client"; then
        log_info "  Removing pulldb-client package..."
        dpkg --purge pulldb-client 2>/dev/null || apt-get remove --purge -y pulldb-client || true
    fi
    
    # Clean up any leftover files
    if [[ -d "$INSTALL_PREFIX" ]]; then
        log_info "  Removing leftover install directory..."
        rm -rf "$INSTALL_PREFIX"
    fi
    
    # Remove systemd units
    rm -f /etc/systemd/system/pulldb-*.service 2>/dev/null || true
    systemctl daemon-reload 2>/dev/null || true
    
    # Remove user/group if exists
    if id "$SERVICE_USER" &>/dev/null; then
        log_info "  Removing service user..."
        deluser --system "$SERVICE_USER" 2>/dev/null || true
    fi
    if getent group "$SERVICE_USER" &>/dev/null; then
        delgroup --system "$SERVICE_USER" 2>/dev/null || true
    fi
    
    log_success "  Purge complete"
}

# =============================================================================
# Step 2: Build packages
# =============================================================================
build_packages() {
    log_info "Step 2: Building packages..."
    
    cd "$PROJECT_ROOT"
    
    log_info "  Running make clean..."
    make clean
    
    log_info "  Running make all..."
    make all
    
    # Verify .deb was created
    if ls *.deb 1>/dev/null 2>&1; then
        log_success "  Build complete. Packages:"
        ls -la *.deb
    else
        log_error "  No .deb files created!"
        exit 1
    fi
}

# =============================================================================
# Step 3: Install the .deb package
# =============================================================================
install_package() {
    log_info "Step 3: Installing pulldb server package..."
    
    cd "$PROJECT_ROOT"
    
    # Find the server .deb (not client)
    SERVER_DEB=$(ls pulldb_*.deb 2>/dev/null | grep -v client | head -1)
    
    if [[ -z "$SERVER_DEB" ]]; then
        log_error "  Server .deb not found!"
        exit 1
    fi
    
    log_info "  Installing: $SERVER_DEB"
    
    # Use DEBIAN_FRONTEND=noninteractive to skip prompts
    DEBIAN_FRONTEND=noninteractive dpkg -i "$SERVER_DEB"
    
    log_success "  Package installed"
}

# =============================================================================
# Step 4: Configure .env and AWS
# =============================================================================
configure_environment() {
    log_info "Step 4: Configuring environment..."
    
    # Create .env with test-friendly settings
    cat > "${INSTALL_PREFIX}/.env" << 'EOF'
# =============================================================================
# pullDB Test Environment Configuration
# =============================================================================

# AWS Configuration (use EC2 instance profile)
PULLDB_AWS_PROFILE=pr-dev
PULLDB_S3_AWS_PROFILE=pr-staging
AWS_DEFAULT_REGION=us-east-1

# MySQL Coordination Database
# For testing, use local MySQL with test user
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_PORT=3306
PULLDB_MYSQL_DATABASE=pulldb_service

# Service-specific MySQL users
PULLDB_API_MYSQL_USER=pulldb_api
PULLDB_WORKER_MYSQL_USER=pulldb_worker

# Test credential overrides (for running tests without AWS)
PULLDB_TEST_MYSQL_HOST=localhost
PULLDB_TEST_MYSQL_USER=pulldb_test
PULLDB_TEST_MYSQL_PASSWORD=test123

# S3 Backup Locations
PULLDB_S3_BACKUP_LOCATIONS='[
  {
    "name": "staging",
    "bucket_path": "s3://pestroutesrdsdbs/daily/stg/",
    "profile": "pr-staging",
    "description": "Staging RDS daily backups"
  }
]'

# Myloader settings
PULLDB_MYLOADER_BINARY=/opt/pulldb.service/bin/myloader-0.19.3-3
PULLDB_MYLOADER_THREADS=4
PULLDB_MYLOADER_TIMEOUT_SECONDS=86400

# Directory paths
PULLDB_INSTALL_PREFIX=/opt/pulldb.service
PULLDB_WORK_DIR=/opt/pulldb.service/work
PULLDB_LOG_DIR=/opt/pulldb.service/logs
PULLDB_TMP_DIR=/tmp

# After-SQL directories
PULLDB_CUSTOMERS_AFTER_SQL_DIR=/opt/pulldb.service/after_sql/customer
PULLDB_QA_TEMPLATE_AFTER_SQL_DIR=/opt/pulldb.service/after_sql/quality

# Logging
PULLDB_LOG_LEVEL=INFO
EOF

    chown "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_PREFIX}/.env"
    chmod 600 "${INSTALL_PREFIX}/.env"
    log_success "  Created .env"
    
    # Create .aws/config
    mkdir -p "${INSTALL_PREFIX}/.aws"
    cat > "${INSTALL_PREFIX}/.aws/config" << 'EOF'
# AWS CLI Configuration for pullDB Service

[profile pr-dev]
region = us-east-1
output = json

[profile pr-staging]
role_arn = arn:aws:iam::333204494849:role/pulldb-staging-cross-account-readonly
credential_source = Ec2InstanceMetadata
region = us-east-1
output = json

[profile pr-prod]
role_arn = arn:aws:iam::448509429610:role/pulldb-cross-account-readonly
credential_source = Ec2InstanceMetadata
external_id = pulldb-dev-access-2025
region = us-east-1
output = json
EOF

    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_PREFIX}/.aws"
    chmod 700 "${INSTALL_PREFIX}/.aws"
    chmod 600 "${INSTALL_PREFIX}/.aws/config"
    log_success "  Created .aws/config"
    
    # Ensure work directories exist
    mkdir -p "${INSTALL_PREFIX}/work" "${INSTALL_PREFIX}/logs"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_PREFIX}/work" "${INSTALL_PREFIX}/logs"
    chmod 750 "${INSTALL_PREFIX}/work" "${INSTALL_PREFIX}/logs"
    log_success "  Created work directories"
}

# =============================================================================
# Step 5: Verify MySQL setup
# =============================================================================
verify_mysql() {
    log_info "Step 5: Verifying MySQL setup..."
    
    # Check if pulldb_test user exists and can connect
    if mysql -u pulldb_test -ptest123 -e "SELECT 1" &>/dev/null; then
        log_success "  pulldb_test user can connect"
    else
        log_warn "  pulldb_test user cannot connect, recreating..."
        mysql -e "DROP USER IF EXISTS 'pulldb_test'@'localhost';"
        mysql -e "CREATE USER 'pulldb_test'@'localhost' IDENTIFIED BY 'test123';"
        mysql -e "GRANT ALL PRIVILEGES ON *.* TO 'pulldb_test'@'localhost' WITH GRANT OPTION;"
        mysql -e "FLUSH PRIVILEGES;"
        log_success "  Recreated pulldb_test user"
    fi
    
    # Check pulldb_service database
    if mysql -e "USE pulldb_service" &>/dev/null; then
        log_success "  pulldb_service database exists"
    else
        log_warn "  pulldb_service database missing, will be created by tests"
    fi
}

# =============================================================================
# Step 6: Install test dependencies in venv
# =============================================================================
install_test_deps() {
    log_info "Step 6: Installing test dependencies..."
    
    VENV="${INSTALL_PREFIX}/venv"
    
    if [[ ! -f "${VENV}/bin/pip" ]]; then
        log_error "  Virtual environment not found!"
        exit 1
    fi
    
    # Install test dependencies
    "${VENV}/bin/pip" install --quiet pytest pytest-timeout moto boto3 >/dev/null 2>&1 || true
    
    # Install the source package in editable mode for testing
    cd "$PROJECT_ROOT"
    "${VENV}/bin/pip" install -e ".[dev]" --quiet >/dev/null 2>&1 || true
    
    log_success "  Test dependencies installed"
}

# =============================================================================
# Step 7: Run tests as pulldb_service user
# =============================================================================
run_tests() {
    log_info "Step 7: Running tests as ${SERVICE_USER}..."
    
    cd "$PROJECT_ROOT"
    
    # Make source directory readable by service user
    chmod -R o+rX "$PROJECT_ROOT"
    
    # Run tests as the service user
    log_info "  Executing pytest..."
    
    # Create a test runner script
    cat > /tmp/run_pulldb_tests.sh << 'TESTSCRIPT'
#!/bin/bash
set -e

cd /home/charleshandshy/Projects/pullDB

# Source the environment
export HOME=/opt/pulldb.service
source /opt/pulldb.service/.env

# Use the venv
source /opt/pulldb.service/venv/bin/activate

# Set test-specific variables
export PULLDB_TEST_MYSQL_HOST=localhost
export PULLDB_TEST_MYSQL_USER=pulldb_test
export PULLDB_TEST_MYSQL_PASSWORD=test123

# Run pytest
pytest pulldb/tests/ -v --tb=short --timeout=120 2>&1
TESTSCRIPT
    
    chmod +x /tmp/run_pulldb_tests.sh
    
    # Run as service user
    su -s /bin/bash "$SERVICE_USER" -c "/tmp/run_pulldb_tests.sh"
    
    log_success "  Tests completed!"
}

# =============================================================================
# Step 8: Verify service startup
# =============================================================================
verify_services() {
    log_info "Step 8: Verifying services can start..."
    
    # Try to start the API service
    log_info "  Starting pulldb-api..."
    systemctl start pulldb-api.service || {
        log_error "  Failed to start pulldb-api"
        journalctl -u pulldb-api.service --no-pager -n 20
        return 1
    }
    sleep 2
    
    if systemctl is-active --quiet pulldb-api.service; then
        log_success "  pulldb-api is running"
    else
        log_error "  pulldb-api failed to start"
        journalctl -u pulldb-api.service --no-pager -n 20
        return 1
    fi
    
    # Stop for now (don't leave running)
    systemctl stop pulldb-api.service
    log_success "  Service verification complete"
}

# =============================================================================
# Main
# =============================================================================
main() {
    echo ""
    echo "=========================================="
    echo "  pullDB Deployment and Test Script"
    echo "=========================================="
    echo ""
    
    check_root
    
    purge_existing
    build_packages
    install_package
    configure_environment
    verify_mysql
    install_test_deps
    run_tests
    verify_services
    
    echo ""
    log_success "=========================================="
    log_success "  All steps completed successfully!"
    log_success "=========================================="
    echo ""
}

main "$@"
