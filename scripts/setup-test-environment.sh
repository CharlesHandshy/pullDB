#!/usr/bin/env bash
#
# Setup test environment for pullDB v0.0.1 usability testing
#
# This script creates an isolated test environment with:
# - Dedicated test directory structure
# - MySQL test database
# - AWS credentials verification
# - Package installation
# - Configuration validation
#
set -euo pipefail

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

fail() {
    error "$*"
    exit 1
}

# Configuration
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly TEST_ENV_DIR="${PROJECT_ROOT}/test-env"
readonly DEB_PACKAGE="${PROJECT_ROOT}/pulldb_0.0.1_amd64.deb"
readonly INSTALL_PREFIX="${TEST_ENV_DIR}/opt/pulldb"

# MySQL test database configuration
readonly TEST_DB_NAME="pulldb_test_coordination"
readonly TEST_DB_USER="pulldb_usability_test"
readonly TEST_DB_PASS="pulldb_test_$(openssl rand -hex 8)"

# Flags
DRY_RUN=false
SKIP_MYSQL=false
SKIP_AWS=false
CLEAN=false

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Setup test environment for pullDB v0.0.1 usability testing.

Options:
    --dry-run           Show what would be done without making changes
    --skip-mysql        Skip MySQL database setup (assume already configured)
    --skip-aws          Skip AWS credentials validation
    --clean             Remove existing test environment before setup
    -h, --help          Show this help message

Examples:
    # Full setup
    sudo $(basename "$0")

    # Clean and rebuild
    sudo $(basename "$0") --clean

    # Skip MySQL setup (already configured)
    sudo $(basename "$0") --skip-mysql

Environment Variables:
    AWS_PROFILE         AWS profile to use (default: from .env or 'default')
    MYSQL_ROOT_PASS     MySQL root password (default: prompt)

EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --skip-mysql)
                SKIP_MYSQL=true
                shift
                ;;
            --skip-aws)
                SKIP_AWS=true
                shift
                ;;
            --clean)
                CLEAN=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
}

check_prerequisites() {
    info "Checking prerequisites..."

    # Check if running as root
    if [[ $EUID -ne 0 ]] && [[ "$DRY_RUN" == false ]]; then
        fail "This script must be run as root (use sudo)"
    fi

    # Check for required commands
    local missing_cmds=()
    for cmd in dpkg mysql aws python3 openssl; do
        if ! command -v "$cmd" &>/dev/null; then
            missing_cmds+=("$cmd")
        fi
    done

    if [[ ${#missing_cmds[@]} -gt 0 ]]; then
        fail "Missing required commands: ${missing_cmds[*]}"
    fi

    # Check for .deb package
    if [[ ! -f "$DEB_PACKAGE" ]]; then
        fail "Debian package not found: $DEB_PACKAGE"
    fi

    success "All prerequisites satisfied"
}

clean_test_env() {
    if [[ "$CLEAN" == true ]]; then
        info "Cleaning existing test environment..."

        if [[ -d "$TEST_ENV_DIR" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                info "[DRY-RUN] Would remove: $TEST_ENV_DIR"
            else
                rm -rf "$TEST_ENV_DIR"
                success "Removed existing test environment"
            fi
        fi

        # Drop test database if exists
        if [[ "$SKIP_MYSQL" == false ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                info "[DRY-RUN] Would drop database: $TEST_DB_NAME"
            else
                mysql -u root -p -e "DROP DATABASE IF EXISTS ${TEST_DB_NAME}; DROP USER IF EXISTS '${TEST_DB_USER}'@'localhost';" 2>/dev/null || true
                success "Cleaned test database"
            fi
        fi
    fi
}

create_test_directories() {
    info "Creating test directory structure..."

    local dirs=(
        "$TEST_ENV_DIR"
        "$TEST_ENV_DIR/logs"
        "$TEST_ENV_DIR/config"
        "$TEST_ENV_DIR/backups"
        "$TEST_ENV_DIR/work"
    )

    for dir in "${dirs[@]}"; do
        if [[ "$DRY_RUN" == true ]]; then
            info "[DRY-RUN] Would create directory: $dir"
        else
            mkdir -p "$dir"
        fi
    done

    success "Test directory structure created"
}

setup_mysql_database() {
    if [[ "$SKIP_MYSQL" == true ]]; then
        info "Skipping MySQL setup (--skip-mysql flag set)"
        return
    fi

    info "Setting up MySQL test database..."

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would create database: $TEST_DB_NAME"
        info "[DRY-RUN] Would create user: ${TEST_DB_USER}@localhost"
        return
    fi

    # Create database
    mysql -u root -p <<EOF
CREATE DATABASE IF NOT EXISTS ${TEST_DB_NAME};
CREATE USER IF NOT EXISTS '${TEST_DB_USER}'@'localhost' IDENTIFIED BY '${TEST_DB_PASS}';
GRANT ALL PRIVILEGES ON ${TEST_DB_NAME}.* TO '${TEST_DB_USER}'@'localhost';
FLUSH PRIVILEGES;
EOF

    success "MySQL test database created"

    # Deploy schema if exists
    local schema_file="${PROJECT_ROOT}/schema/pulldb.sql"
    if [[ -f "$schema_file" ]]; then
        info "Deploying pullDB schema..."
        mysql -u "${TEST_DB_USER}" -p"${TEST_DB_PASS}" "${TEST_DB_NAME}" < "$schema_file"
        success "Schema deployed"
    else
        warn "Schema file not found: $schema_file"
        warn "You'll need to deploy the schema manually:"
        warn "  See docs/mysql-schema.md for schema definition"
    fi

    # Save credentials for later use
    cat > "${TEST_ENV_DIR}/config/mysql-credentials.txt" <<EOF
Database: ${TEST_DB_NAME}
User: ${TEST_DB_USER}
Password: ${TEST_DB_PASS}
Host: localhost
Port: 3306

Connection string: mysql://${TEST_DB_USER}:${TEST_DB_PASS}@localhost:3306/${TEST_DB_NAME}
EOF

    chmod 600 "${TEST_ENV_DIR}/config/mysql-credentials.txt"
    info "MySQL credentials saved to: ${TEST_ENV_DIR}/config/mysql-credentials.txt"
}

verify_aws_credentials() {
    if [[ "$SKIP_AWS" == true ]]; then
        info "Skipping AWS verification (--skip-aws flag set)"
        return
    fi

    info "Verifying AWS credentials..."

    local aws_profile="${AWS_PROFILE:-default}"

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would verify AWS profile: $aws_profile"
        return
    fi

    # Test AWS credentials
    if aws sts get-caller-identity --profile "$aws_profile" &>/dev/null; then
        local account_id=$(aws sts get-caller-identity --profile "$aws_profile" --query 'Account' --output text)
        success "AWS credentials valid (Account: $account_id, Profile: $aws_profile)"
    else
        warn "AWS credentials not configured or invalid"
        warn "Run: aws configure --profile $aws_profile"
        warn "Continuing anyway (AWS required for actual restore operations)"
    fi
}

install_package() {
    info "Installing pullDB package..."

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would install: $DEB_PACKAGE"
        return
    fi

    # Extract package to test environment (not system-wide install)
    dpkg-deb -x "$DEB_PACKAGE" "$TEST_ENV_DIR"

    success "Package extracted to test environment"
}

create_test_config() {
    info "Creating test configuration..."

    local env_file="${TEST_ENV_DIR}/.env"
    local aws_profile="${AWS_PROFILE:-default}"

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would create: $env_file"
        return
    fi

    cat > "$env_file" <<EOF
# pullDB Test Environment Configuration
# Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')

# AWS Configuration
PULLDB_AWS_PROFILE=${aws_profile}

# MySQL Coordination Database
PULLDB_MYSQL_CREDENTIAL_REF=test-local-mysql
PULLDB_MYSQL_HOST=localhost
PULLDB_MYSQL_PORT=3306
PULLDB_MYSQL_DATABASE=${TEST_DB_NAME}
PULLDB_MYSQL_USER=${TEST_DB_USER}
PULLDB_MYSQL_PASSWORD=${TEST_DB_PASS}

# S3 Backup Configuration (for testing)
# Development account staging backups (recommended for testing)
PULLDB_S3_BUCKET=pestroutesrdsdbs
PULLDB_S3_PREFIX=daily/stg/

# Logging
PULLDB_LOG_LEVEL=DEBUG

# Work Directory
PULLDB_WORK_DIR=${TEST_ENV_DIR}/work
EOF

    chmod 644 "$env_file"
    success "Test configuration created: $env_file"
}

create_test_venv() {
    info "Creating Python virtual environment..."

    local venv_dir="${TEST_ENV_DIR}/venv"

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would create venv: $venv_dir"
        return
    fi

    python3 -m venv "$venv_dir"

    # Install pulldb package in editable mode
    source "${venv_dir}/bin/activate"
    pip install --upgrade pip
    pip install -e "${PROJECT_ROOT}"
    pip install mypy-boto3-s3  # Type stubs for S3 operations
    deactivate

    success "Python virtual environment created"
}

create_convenience_scripts() {
    info "Creating convenience scripts..."

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would create: ${TEST_ENV_DIR}/activate-test-env.sh"
        info "[DRY-RUN] Would create: ${TEST_ENV_DIR}/run-quick-test.sh"
        return
    fi

    # Activation script
    cat > "${TEST_ENV_DIR}/activate-test-env.sh" <<'EOF'
#!/usr/bin/env bash
# Activate pullDB test environment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    export $(grep -v '^#' "${SCRIPT_DIR}/.env" | xargs)
    echo "✓ Environment variables loaded"
fi

# Activate Python venv
if [[ -f "${SCRIPT_DIR}/venv/bin/activate" ]]; then
    source "${SCRIPT_DIR}/venv/bin/activate"
    echo "✓ Python virtual environment activated"
fi

# Add convenience aliases
alias pulldb="${SCRIPT_DIR}/venv/bin/pulldb"
alias pulldb-status="pulldb status --json | jq"
alias pulldb-logs="tail -f ${SCRIPT_DIR}/logs/pulldb-worker.log"

echo ""
echo "pullDB Test Environment Ready!"
echo "================================"
echo "Config: ${SCRIPT_DIR}/.env"
echo "Logs: ${SCRIPT_DIR}/logs/"
echo "Work: ${SCRIPT_DIR}/work/"
echo ""
echo "Quick commands:"
echo "  pulldb --help"
echo "  pulldb-status"
echo "  pulldb-logs"
echo ""
echo "To deactivate: deactivate"
EOF

    chmod +x "${TEST_ENV_DIR}/activate-test-env.sh"

    # Quick test script
    cat > "${TEST_ENV_DIR}/run-quick-test.sh" <<'EOF'
#!/usr/bin/env bash
# Quick smoke test for pullDB installation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/activate-test-env.sh"

echo "Running quick smoke tests..."
echo ""

# Test 1: CLI help
echo "✓ Testing CLI help..."
pulldb --help >/dev/null || { echo "✗ CLI help failed"; exit 1; }

# Test 2: Database connectivity
echo "✓ Testing database connectivity..."
python3 -c "
import mysql.connector
import os
conn = mysql.connector.connect(
    host=os.environ['PULLDB_MYSQL_HOST'],
    user=os.environ['PULLDB_MYSQL_USER'],
    password=os.environ['PULLDB_MYSQL_PASSWORD'],
    database=os.environ['PULLDB_MYSQL_DATABASE']
)
cursor = conn.cursor()
cursor.execute('SELECT VERSION()')
print(f'  MySQL version: {cursor.fetchone()[0]}')
conn.close()
" || { echo "✗ Database connectivity failed"; exit 1; }

# Test 3: AWS credentials
echo "✓ Testing AWS credentials..."
aws sts get-caller-identity --profile "${PULLDB_AWS_PROFILE}" >/dev/null || {
    echo "✗ AWS credentials not configured"
    echo "  Run: aws configure --profile ${PULLDB_AWS_PROFILE}"
}

# Test 4: Import test
echo "✓ Testing Python imports..."
python3 -c "
from pulldb.cli import main
from pulldb.infra import mysql, s3, secrets
from pulldb.domain import config, models
print('  All imports successful')
" || { echo "✗ Import test failed"; exit 1; }

echo ""
echo "All smoke tests passed! ✓"
EOF

    chmod +x "${TEST_ENV_DIR}/run-quick-test.sh"

    success "Convenience scripts created"
}

print_summary() {
    cat <<EOF

${GREEN}╔════════════════════════════════════════════════════════════════╗
║          pullDB v0.0.1 Test Environment Ready!                  ║
╚════════════════════════════════════════════════════════════════╝${NC}

Test Environment: ${BLUE}${TEST_ENV_DIR}${NC}

${YELLOW}Next Steps:${NC}

1. Activate test environment:
   ${BLUE}source ${TEST_ENV_DIR}/activate-test-env.sh${NC}

2. Run quick smoke test:
   ${BLUE}bash ${TEST_ENV_DIR}/run-quick-test.sh${NC}

3. View MySQL credentials:
   ${BLUE}cat ${TEST_ENV_DIR}/config/mysql-credentials.txt${NC}

4. Review configuration:
   ${BLUE}cat ${TEST_ENV_DIR}/.env${NC}

5. Start usability testing:
   ${BLUE}pulldb --help${NC}
   ${BLUE}pulldb status${NC}

${YELLOW}Directory Structure:${NC}
  ${TEST_ENV_DIR}/
  ├── .env                  # Configuration
  ├── venv/                 # Python virtual environment
  ├── config/               # Credentials and settings
  ├── logs/                 # Application logs
  ├── work/                 # Working directory for restores
  ├── activate-test-env.sh  # Activation script
  └── run-quick-test.sh     # Smoke test script

${YELLOW}AWS Configuration:${NC}
  Profile: ${AWS_PROFILE:-default}
  Account: $(aws sts get-caller-identity --profile "${AWS_PROFILE:-default}" --query 'Account' --output text 2>/dev/null || echo "Not configured")

${YELLOW}MySQL Configuration:${NC}
  Database: ${TEST_DB_NAME}
  Host: localhost
  Credentials: ${TEST_ENV_DIR}/config/mysql-credentials.txt

${YELLOW}Documentation:${NC}
  - Testing Guide: ${PROJECT_ROOT}/docs/testing.md
  - AWS Setup: ${PROJECT_ROOT}/docs/aws-quickstart.md
  - README: ${PROJECT_ROOT}/README.md

EOF
}

main() {
    parse_args "$@"

    info "Setting up pullDB v0.0.1 test environment..."
    echo ""

    check_prerequisites
    clean_test_env
    create_test_directories
    setup_mysql_database
    verify_aws_credentials
    install_package
    create_test_config
    create_test_venv
    create_convenience_scripts

    if [[ "$DRY_RUN" == false ]]; then
        print_summary
    else
        info "[DRY-RUN] Setup complete (no changes made)"
    fi
}

main "$@"
