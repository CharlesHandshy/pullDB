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
readonly RED=$'\033[0;31m'
readonly GREEN=$'\033[0;32m'
readonly YELLOW=$'\033[1;33m'
readonly BLUE=$'\033[0;34m'
readonly NC=$'\033[0m' # No Color

# Global state
DETECTED_AWS_ACCOUNT=""
DETECTED_AWS_PROFILE=""

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
readonly INSTALL_PREFIX="${TEST_ENV_DIR}/opt/pulldb.service"
readonly LOG_FILE="$(pwd)/setup-test-env.log"

# MySQL test database configuration
# Database name follows pattern: pulldb_<username>
readonly TEST_DB_USER_BASE="${SUDO_USER:-$USER}"
readonly TEST_DB_NAME="pulldb_${TEST_DB_USER_BASE}"
readonly TEST_DB_USER="pullDbService"
readonly TEST_DB_PASS="pulldb_test_$(openssl rand -hex 8)"

# Flags
DRY_RUN=false
SKIP_MYSQL=false
SKIP_AWS=false
CLEAN=false
NORMALIZE_PERMS=false

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Setup test environment for pullDB v0.0.1 usability testing.

Options:
    --dry-run           Show what would be done without making changes
    --skip-mysql        Skip MySQL database setup (assume already configured)
    --skip-aws          Skip AWS credentials validation
    --clean             Remove existing test environment before setup
    --normalize-perms   Normalize ownership & permissions after setup (Development File Ownership Principle)
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
            --normalize-perms)
                NORMALIZE_PERMS=true
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

install_system_dependencies() {
    info "Checking and installing system dependencies..."

    if [[ $EUID -ne 0 ]] && [[ "$DRY_RUN" == false ]]; then
        fail "This script must be run as root (use sudo)"
    fi

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would update apt and install: python3 python3-venv python3-pip mysql-server mysql-client jq curl unzip openssl"
        return
    fi

    # Update apt
    apt-get update || warn "Failed to update apt cache"

    # Install packages
    # Note: python3-full includes venv and pip on some distros, but listing explicitly is safer
    local packages=(python3 python3-venv python3-pip mysql-server mysql-client jq curl unzip openssl)
    local to_install=()

    for pkg in "${packages[@]}"; do
        if ! dpkg -l | grep -q "^ii  $pkg "; then
            to_install+=("$pkg")
        fi
    done

    if [[ ${#to_install[@]} -gt 0 ]]; then
        info "Installing missing packages: ${to_install[*]}"
        apt-get install -y "${to_install[@]}"
    else
        success "System packages already installed"
    fi
    
    # Ensure MySQL service is running
    if ! systemctl is-active --quiet mysql; then
        info "Starting MySQL service..."
        systemctl start mysql
    fi
}

install_aws_cli() {
    if command -v aws &>/dev/null; then
        success "AWS CLI already installed"
        return
    fi

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would install AWS CLI v2"
        return
    fi

    info "Installing AWS CLI v2..."
    rm -rf aws awscliv2.zip
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip -q awscliv2.zip
    ./aws/install
    rm -rf aws awscliv2.zip
    success "AWS CLI installed"
}

ensure_deb_package() {
    if [[ -f "$DEB_PACKAGE" ]]; then
        success "Debian package found: $DEB_PACKAGE"
        return
    fi

    info "Debian package not found. Building..."
    
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would run scripts/build_deb.sh"
        return
    fi

    # Build as non-root if possible to avoid root ownership of build artifacts
    local build_script="${PROJECT_ROOT}/scripts/build_deb.sh"
    if [[ -n "${SUDO_USER:-}" ]]; then
        sudo -u "$SUDO_USER" "$build_script"
    else
        "$build_script"
    fi

    if [[ ! -f "$DEB_PACKAGE" ]]; then
        fail "Failed to build Debian package at $DEB_PACKAGE"
    fi
    success "Debian package built"
}

teardown_test_env() {
    local reason="$1"
    info "Cleaning existing test environment (${reason})..."

    # Kill any running processes from the test environment
    if pgrep -f "${TEST_ENV_DIR}/venv/bin/pulldb" >/dev/null; then
        if [[ "$DRY_RUN" == true ]]; then
            info "[DRY-RUN] Would kill running pullDB processes"
        else
            info "Killing running pullDB processes..."
            pkill -f "${TEST_ENV_DIR}/venv/bin/pulldb" || true
            sleep 1
        fi
    fi

    if [[ -d "$TEST_ENV_DIR" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            info "[DRY-RUN] Would remove: $TEST_ENV_DIR"
        else
            rm -rf "$TEST_ENV_DIR"
            success "Removed existing test environment"
        fi
    fi

    if [[ "$SKIP_MYSQL" == false ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            info "[DRY-RUN] Would drop database: $TEST_DB_NAME"
        else
            local mysql_cmd="mysql -u root"
            if [[ -n "${MYSQL_ROOT_PASS:-}" ]]; then
                mysql_cmd+=" -p\"${MYSQL_ROOT_PASS}\""
            fi
            eval "$mysql_cmd" <<EOF
DROP DATABASE IF EXISTS ${TEST_DB_NAME};
DROP USER IF EXISTS '${TEST_DB_USER}'@'localhost';
EOF
            success "Cleaned test database"
        fi
    fi
}

clean_test_env() {
    if [[ "$CLEAN" == true ]]; then
        teardown_test_env "--clean flag"
    fi
}

auto_cleanup_previous_env() {
    if [[ -d "$TEST_ENV_DIR" && "$CLEAN" == false ]]; then
        warn "Existing test environment detected at $TEST_ENV_DIR; tearing it down before proceeding"
        teardown_test_env "previous environment detected"
    fi
}

create_test_directories() {
    info "Creating test directory structure..."

    # Ensure secure work directory base exists
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would create directory: /mnt/data/tmp"
    else
        mkdir -p /mnt/data/tmp
        chmod 1777 /mnt/data/tmp
    fi

    local work_dir="/mnt/data/tmp/${SUDO_USER:-$USER}/pulldb-work"

    local dirs=(
        "$TEST_ENV_DIR"
        "$TEST_ENV_DIR/logs"
        "$TEST_ENV_DIR/config"
        "$TEST_ENV_DIR/backups"
        "$work_dir"
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
    # Use socket authentication when possible; only append -p if MYSQL_ROOT_PASS is set.
    local mysql_cmd="mysql -u root"
    if [[ -n "${MYSQL_ROOT_PASS:-}" ]]; then
        mysql_cmd+=" -p\"${MYSQL_ROOT_PASS}\""
    fi
    # Execute creation commands
    eval "$mysql_cmd" <<EOF
CREATE DATABASE IF NOT EXISTS ${TEST_DB_NAME};
CREATE USER IF NOT EXISTS '${TEST_DB_USER}'@'localhost' IDENTIFIED BY '${TEST_DB_PASS}';
-- Grant on specific database
GRANT ALL PRIVILEGES ON ${TEST_DB_NAME}.* TO '${TEST_DB_USER}'@'localhost';
-- Grant on all pulldb_ prefixed databases (for multi-user support)
GRANT ALL PRIVILEGES ON \`pulldb_%\`.* TO '${TEST_DB_USER}'@'localhost';
FLUSH PRIVILEGES;
EOF

    success "MySQL test database created"

    # Deploy schema if exists
    local schema_dir="${PROJECT_ROOT}/schema/pulldb"
    if [[ -d "$schema_dir" ]] && compgen -G "${schema_dir}/*.sql" > /dev/null; then
        info "Deploying pullDB schema from ${schema_dir}..."
        for sql_file in "${schema_dir}"/*.sql; do
            info "  -> $(basename "$sql_file")"
            mysql -u "${TEST_DB_USER}" -p"${TEST_DB_PASS}" "${TEST_DB_NAME}" < "$sql_file"
        done
        success "Schema deployed"
    else
        warn "Schema directory not found or empty: $schema_dir"
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

    local aws_profile="${AWS_PROFILE:-pr-dev}"
    DETECTED_AWS_PROFILE="$aws_profile"

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would verify AWS profile: $aws_profile"
        return
    fi

    # Helper to run aws command, potentially dropping privileges to SUDO_USER to find credentials
    run_aws() {
        local profile_arg="$1"
        shift
        
        local cmd="aws"
        if [[ -n "${SUDO_USER:-}" ]]; then
            cmd="sudo -u $SUDO_USER $cmd"
        fi
        
        if [[ -n "$profile_arg" ]]; then
            $cmd --profile "$profile_arg" "$@"
        else
            $cmd "$@"
        fi
    }

    # 1. Try explicit profile (default: pr-dev)
    local account_id=""
    if [[ "$DRY_RUN" == false ]]; then
        echo "DEBUG: Attempting AWS auth with profile '$aws_profile' (User: ${SUDO_USER:-root})" >> "$LOG_FILE"
    fi
    
    account_id=$(run_aws "$aws_profile" sts get-caller-identity --query 'Account' --output text 2>>"$LOG_FILE" || true)
    
    if [[ -n "$account_id" ]]; then
        DETECTED_AWS_ACCOUNT="$account_id"
        success "AWS credentials valid (Account: $account_id, Profile: $aws_profile)"
        return
    fi

    # 2. Fallback: Try default provider chain (no profile specified)
    # This catches instance metadata (IMDS) or default profile
    if [[ "$DRY_RUN" == false ]]; then
        echo "DEBUG: Attempting AWS auth with default provider chain" >> "$LOG_FILE"
    fi

    account_id=$(run_aws "" sts get-caller-identity --query 'Account' --output text 2>>"$LOG_FILE" || true)
    
    if [[ -n "$account_id" ]]; then
        DETECTED_AWS_ACCOUNT="$account_id"
        DETECTED_AWS_PROFILE="default/IMDS"
        success "AWS credentials valid via default chain (Account: $account_id)"
        return
    fi

    warn "AWS credentials unavailable. Expected role: arn:aws:iam::333204494849:role/pulldb-staging-cross-account-readonly"
    warn "If running on EC2, verify instance profile permissions. For local testing either configure a source profile with sts:AssumeRole or rerun with --skip-aws"
    warn "Continuing anyway (AWS required for actual restore operations)"
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
    local aws_profile="${AWS_PROFILE:-pr-dev}"

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would create: $env_file"
        return
    fi

    cat > "$env_file" <<EOF
# pullDB Test Environment Configuration
# Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')

# AWS Configuration
PULLDB_AWS_PROFILE=${aws_profile}
PULLDB_S3_AWS_PROFILE=pr-staging

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
PULLDB_WORK_DIR=/mnt/data/tmp/${SUDO_USER:-$USER}/pulldb-work
EOF

    chmod 644 "$env_file"
    success "Test configuration created: $env_file"
}

create_test_venv() {
    info "Creating Python virtual environment..."

    local venv_dir="${TEST_ENV_DIR}/venv"
    local requirements_test_file="${PROJECT_ROOT}/requirements-test.txt"

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would create venv: $venv_dir"
        return
    fi

    python3 -m venv "$venv_dir"

    # Normalize ownership if running under sudo so non-root user can modify venv
    if [[ -n "${SUDO_USER:-}" ]]; then
        chown -R "${SUDO_USER}:${SUDO_USER}" "$venv_dir" || warn "Failed to chown venv (continuing)"
    fi

    # Install pulldb package in editable mode
    source "${venv_dir}/bin/activate"
    pip install --upgrade pip
    pip install -e "${PROJECT_ROOT}"
    if [[ -f "${requirements_test_file}" ]]; then
        pip install -r "${requirements_test_file}"
    else
        warn "requirements-test.txt not found; skipping automated test dependency installation"
    fi
    deactivate

    # Verify venv writable
    if [[ ! -w "$venv_dir/pyvenv.cfg" ]]; then
        warn "Virtual environment appears non-writable; ownership or permissions may be incorrect"
    fi

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
echo "Work: /mnt/data/tmp/${SUDO_USER:-$USER}/pulldb-work/"
echo ""
echo "Quick commands:"
echo "  pulldb --help"
echo "  pulldb-status"
echo "  pulldb-logs"
echo ""
echo "To deactivate: deactivate"
EOF

    chmod +x "${TEST_ENV_DIR}/activate-test-env.sh"

    # Copy scripts from source
    if [[ -f "${PROJECT_ROOT}/scripts/run-quick-test.sh" ]]; then
        cp "${PROJECT_ROOT}/scripts/run-quick-test.sh" "${TEST_ENV_DIR}/run-quick-test.sh"
        chmod +x "${TEST_ENV_DIR}/run-quick-test.sh"
    else
        warn "scripts/run-quick-test.sh not found; skipping copy"
    fi

    if [[ -f "${PROJECT_ROOT}/scripts/start-test-services.sh" ]]; then
        cp "${PROJECT_ROOT}/scripts/start-test-services.sh" "${TEST_ENV_DIR}/start-test-services.sh"
        chmod +x "${TEST_ENV_DIR}/start-test-services.sh"
    else
        warn "scripts/start-test-services.sh not found; skipping copy"
    fi

    success "Convenience scripts created"
}

# Normalize permissions according to Development File Ownership Principle
normalize_permissions() {
    if [[ "$NORMALIZE_PERMS" == false ]]; then
        return
    fi
    info "Normalizing ownership & permissions (Development File Ownership Principle)"
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would chown -R ${SUDO_USER:-$USER}:${SUDO_USER:-$USER} $TEST_ENV_DIR"
        info "[DRY-RUN] Would set directory modes to 750, scripts/bin to 750, regular files to 640, credentials to 600"
        return
    fi
    local owner="${SUDO_USER:-$USER}"; local group="${SUDO_USER:-$USER}"
    chown -R "$owner:$group" "$TEST_ENV_DIR" || warn "Ownership normalization encountered an error"
    # Directories
    find "$TEST_ENV_DIR" -type d -exec chmod 750 {} +
    # Scripts & executables
    find "$TEST_ENV_DIR" -type f -name '*.sh' -exec chmod 750 {} +
    find "$TEST_ENV_DIR/venv/bin" -type f -exec chmod 750 {} + 2>/dev/null || true
    # Credentials tightened
    if [[ -f "$TEST_ENV_DIR/config/mysql-credentials.txt" ]]; then chmod 600 "$TEST_ENV_DIR/config/mysql-credentials.txt"; fi
    # Regular files (exclude executables already handled)
    find "$TEST_ENV_DIR" -type f -not -path "*/venv/bin/*" -not -name '*.sh' -exec chmod 640 {} +
    success "Permissions normalized"
}

# Ensure final ownership reverts to invoking user so interactive work does not require sudo.
restore_test_env_ownership() {
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would chown -R ${SUDO_USER:-$USER}:${SUDO_USER:-$USER} $TEST_ENV_DIR"
        return
    fi

    if [[ ! -d "$TEST_ENV_DIR" ]]; then
        warn "Test environment directory not found during ownership restoration"
        return
    fi

    local owner="${SUDO_USER:-$USER}"
    if [[ -z "$owner" ]]; then
        warn "Unable to determine invoking user for ownership restoration"
        return
    fi

    if chown -R "$owner:$owner" "$TEST_ENV_DIR"; then
        success "Restored test-env ownership to ${owner}:${owner}"
    else
        warn "Failed to restore test-env ownership; manual chown may be required"
    fi
}

# Run smoke tests automatically unless DRY_RUN
post_setup_self_test() {
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would execute post-setup smoke tests"
        return
    fi
    info "Executing post-setup smoke tests..."
    if bash "${TEST_ENV_DIR}/run-quick-test.sh" >/dev/null 2>&1; then
        success "Post-setup smoke tests passed"
    else
        fail "Post-setup smoke tests failed – environment not ready"
    fi
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

3. Start services:
   ${BLUE}bash ${TEST_ENV_DIR}/start-test-services.sh${NC}

4. View MySQL credentials:
   ${BLUE}cat ${TEST_ENV_DIR}/config/mysql-credentials.txt${NC}

5. Review configuration:
   ${BLUE}cat ${TEST_ENV_DIR}/.env${NC}

6. Start usability testing:
   ${BLUE}pulldb --help${NC}
   ${BLUE}pulldb status${NC}

${YELLOW}Directory Structure:${NC}
  ${TEST_ENV_DIR}/
  ├── .env                  # Configuration
  ├── venv/                 # Python virtual environment
  ├── config/               # Credentials and settings
  ├── logs/                 # Application logs
  ├── activate-test-env.sh  # Activation script
  └── run-quick-test.sh     # Smoke test script

${YELLOW}Work Directory:${NC}
  /mnt/data/tmp/${SUDO_USER:-$USER}/pulldb-work/

${YELLOW}AWS Configuration:${NC}
  Profile: ${DETECTED_AWS_PROFILE:-Not configured}
  Account: ${DETECTED_AWS_ACCOUNT:-Not configured}

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

run_step() {
    local msg="$1"
    shift
    
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] $msg"
        "$@"
        return
    fi

    printf "${BLUE}[INFO]${NC} %-50s" "$msg..."
    
    # Run command in background, redirecting output to log
    {
        echo ">>> START: $msg"
        "$@"
        local ret=$?
        echo ">>> END: $msg (Exit Code: $ret)"
        return $ret
    } >> "$LOG_FILE" 2>&1 &
    local pid=$!
    
    local delay=0.1
    local spinstr='|/-\'
    
    # Hide cursor
    tput civis 2>/dev/null || true
    
    while kill -0 $pid 2>/dev/null; do
        local temp=${spinstr#?}
        printf "[%c]" "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b"
    done
    
    wait $pid
    local exit_code=$?
    
    # Restore cursor
    tput cnorm 2>/dev/null || true
    
    # Clear spinner
    printf "   \b\b\b"
    
    if [ $exit_code -eq 0 ]; then
        printf "${GREEN}[DONE]${NC}\n"
    else
        printf "${RED}[FAIL]${NC}\n"
        echo -e "${RED}Error details in ${LOG_FILE}${NC}"
        exit $exit_code
    fi
}

main() {
    parse_args "$@"

    # Initialize log
    if [[ "$DRY_RUN" == false ]]; then
        echo "pullDB Setup Log - $(date)" > "$LOG_FILE"
        echo "========================================" >> "$LOG_FILE"
        info "Setting up pullDB v0.0.1 test environment..."
        echo "Logs will be written to $LOG_FILE"
    else
        info "Setting up pullDB v0.0.1 test environment (DRY RUN)..."
    fi
    echo ""

    run_step "Installing system dependencies" install_system_dependencies
    run_step "Installing AWS CLI" install_aws_cli
    run_step "Building/Checking Debian package" ensure_deb_package
    run_step "Cleaning previous environment" clean_test_env
    run_step "Checking for existing environment" auto_cleanup_previous_env
    run_step "Creating directory structure" create_test_directories
    run_step "Setting up MySQL database" setup_mysql_database
    run_step "Verifying AWS credentials" verify_aws_credentials
    run_step "Installing pullDB package" install_package
    run_step "Creating configuration" create_test_config
    run_step "Creating virtual environment" create_test_venv
    run_step "Creating convenience scripts" create_convenience_scripts
    run_step "Normalizing permissions" normalize_permissions
    run_step "Running post-setup smoke tests" post_setup_self_test
    run_step "Restoring ownership" restore_test_env_ownership

    if [[ "$DRY_RUN" == false ]]; then
        print_summary
    else
        info "[DRY-RUN] Setup complete (no changes made)"
    fi
}

main "$@"
