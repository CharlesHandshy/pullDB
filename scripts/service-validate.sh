#!/usr/bin/env bash
# ==============================================================================
# pullDB Production Service Validation
# ==============================================================================
# Comprehensive validation for production deployments.
#
# This script validates:
#   - System prerequisites (Python, MySQL, myloader)
#   - AWS credentials and permissions (Secrets Manager, S3)
#   - Service installation integrity
#   - Database connectivity
#   - End-to-end restore capability (optional)
#
# Usage:
#   sudo /opt/pulldb.service/validate/service-validate.sh [--quick|--full|--e2e]
#
# Exit Codes:
#   0 - All checks passed
#   1 - One or more checks failed
#   2 - Script error (invalid arguments, missing dependencies)
# ==============================================================================

set -uo pipefail
# Note: We don't use -e because we handle errors manually in validation checks

# Script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PREFIX="${PULLDB_INSTALL_PREFIX:-/opt/pulldb.service}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# Counters
PASSED=0
FAILED=0
WARNINGS=0
SKIPPED=0

# Options
RUN_E2E=false
RUN_FULL=true
DRY_RUN=false
LOG_FILE="/tmp/pulldb-service-validate-$(date +%Y%m%d_%H%M%S).log"

# ==============================================================================
# Output Functions
# ==============================================================================

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >> "$LOG_FILE"
}

check_pass() {
    echo -e "  ${GREEN}[✓]${NC} $*"
    log "[PASS] $*"
    ((PASSED++))
}

check_fail() {
    echo -e "  ${RED}[✗]${NC} $*"
    log "[FAIL] $*"
    ((FAILED++))
}

check_warn() {
    echo -e "  ${YELLOW}[!]${NC} $*"
    log "[WARN] $*"
    ((WARNINGS++))
}

check_skip() {
    echo -e "  ${BLUE}[○]${NC} $*"
    log "[SKIP] $*"
    ((SKIPPED++))
}

check_info() {
    echo -e "  ${BLUE}[i]${NC} $*"
    log "[INFO] $*"
}

phase_header() {
    local phase_num="$1"
    local phase_name="$2"
    echo ""
    echo -e "${BOLD}Phase ${phase_num}: ${phase_name}${NC}"
    log "=== Phase ${phase_num}: ${phase_name} ==="
}

banner() {
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  pullDB Production Service Validation${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# ==============================================================================
# Helper Functions
# ==============================================================================

command_exists() {
    command -v "$1" &>/dev/null
}

load_env() {
    local env_file="${INSTALL_PREFIX}/.env"
    if [[ -f "$env_file" ]]; then
        set -a
        # shellcheck source=/dev/null
        source "$env_file"
        set +a
        return 0
    fi
    return 1
}

# ==============================================================================
# Phase 0: Prerequisites
# ==============================================================================

validate_prerequisites() {
    phase_header "0" "Prerequisites"
    
    # Python version
    local python_bin="${INSTALL_PREFIX}/venv/bin/python3"
    if [[ -x "$python_bin" ]]; then
        local py_version
        py_version=$("$python_bin" --version 2>&1 | cut -d' ' -f2)
        check_pass "Python ${py_version} (${python_bin})"
    else
        check_fail "Python not found at ${python_bin}"
    fi
    
    # MySQL client
    if command_exists mysql; then
        local mysql_version
        mysql_version=$(mysql --version 2>&1 | head -1 | sed 's/.*Ver //' | cut -d' ' -f1 || echo "unknown")
        check_pass "MySQL client ${mysql_version}"
    else
        check_fail "MySQL client not installed"
    fi
    
    # myloader binary
    local myloader_bin="${PULLDB_MYLOADER_BINARY:-${INSTALL_PREFIX}/bin/myloader-0.19.3-3}"
    if [[ -x "$myloader_bin" ]]; then
        local myloader_version
        myloader_version=$("$myloader_bin" --version 2>&1 | head -1 || echo "unknown")
        check_pass "myloader: ${myloader_version}"
    else
        check_warn "myloader not found at ${myloader_bin}"
    fi
    
    # AWS CLI
    if command_exists aws; then
        local aws_version
        aws_version=$(aws --version 2>&1 | cut -d' ' -f1)
        check_pass "AWS CLI ${aws_version}"
    else
        check_fail "AWS CLI not installed"
    fi
    
    # Disk space
    local work_dir="${PULLDB_WORK_DIR:-${INSTALL_PREFIX}/work}"
    if [[ -d "$work_dir" ]]; then
        local available_gb
        available_gb=$(df -BG "$work_dir" 2>/dev/null | tail -1 | awk '{print $4}' | tr -d 'G')
        if [[ "$available_gb" -lt 50 ]]; then
            check_warn "Work directory has ${available_gb}GB (recommend 50GB+)"
        else
            check_pass "Work directory: ${available_gb}GB available"
        fi
    else
        check_warn "Work directory does not exist: ${work_dir}"
    fi
}

# ==============================================================================
# Phase 1: Installation Integrity
# ==============================================================================

validate_installation() {
    phase_header "1" "Installation Integrity"
    
    # Check installation directory
    if [[ -d "$INSTALL_PREFIX" ]]; then
        check_pass "Install directory: ${INSTALL_PREFIX}"
    else
        check_fail "Install directory missing: ${INSTALL_PREFIX}"
        return 1
    fi
    
    # Check .env file
    if [[ -f "${INSTALL_PREFIX}/.env" ]]; then
        check_pass ".env file present"
    else
        check_fail ".env file missing"
    fi
    
    # Check AWS config
    if [[ -f "${INSTALL_PREFIX}/.aws/config" ]]; then
        check_pass ".aws/config present"
    else
        check_warn ".aws/config not found (using default location)"
    fi
    
    # Check venv
    if [[ -d "${INSTALL_PREFIX}/venv" ]]; then
        check_pass "Virtual environment present"
    else
        check_fail "Virtual environment missing"
    fi
    
    # Check pulldb CLI
    local pulldb_bin="${INSTALL_PREFIX}/venv/bin/pulldb"
    if [[ -x "$pulldb_bin" ]]; then
        local version
        version=$("$pulldb_bin" --version 2>&1 || echo "unknown")
        check_pass "pulldb CLI: ${version}"
    else
        check_fail "pulldb CLI not found"
    fi
    
    # Check pulldb-worker
    local worker_bin="${INSTALL_PREFIX}/venv/bin/pulldb-worker"
    if [[ -x "$worker_bin" ]]; then
        check_pass "pulldb-worker binary present"
    else
        check_fail "pulldb-worker binary missing"
    fi
    
    # Check systemd unit
    if [[ -f "/etc/systemd/system/pulldb-worker.service" ]]; then
        local unit_status
        unit_status=$(systemctl is-enabled pulldb-worker 2>/dev/null || echo "disabled")
        check_pass "systemd unit installed (${unit_status})"
    else
        check_warn "systemd unit not installed"
    fi
    
    # Check required directories
    local dirs=(
        "${PULLDB_LOG_DIR:-${INSTALL_PREFIX}/logs}"
        "${PULLDB_WORK_DIR:-${INSTALL_PREFIX}/work}"
    )
    for dir in "${dirs[@]}"; do
        if [[ -d "$dir" ]]; then
            local owner
            owner=$(stat -c '%U:%G' "$dir" 2>/dev/null || echo "unknown")
            check_pass "Directory: ${dir} (${owner})"
        else
            check_warn "Directory missing: ${dir}"
        fi
    done
}

# ==============================================================================
# Phase 2: AWS Credentials
# ==============================================================================

validate_aws_credentials() {
    phase_header "2" "AWS Credentials"
    
    # Set AWS config path if using service directory
    if [[ -f "${INSTALL_PREFIX}/.aws/config" ]]; then
        export AWS_CONFIG_FILE="${INSTALL_PREFIX}/.aws/config"
    fi
    
    # Test pr-dev profile (Secrets Manager)
    local dev_account
    if dev_account=$(aws sts get-caller-identity --profile pr-dev --query 'Account' --output text 2>/dev/null); then
        if [[ "$dev_account" == "345321506926" ]]; then
            check_pass "pr-dev profile valid (Account: ${dev_account})"
        else
            check_warn "pr-dev profile: unexpected account ${dev_account} (expected 345321506926)"
        fi
    else
        check_fail "pr-dev profile: authentication failed"
    fi
    
    # Test pr-staging profile (S3 staging)
    local staging_account
    if staging_account=$(aws sts get-caller-identity --profile pr-staging --query 'Account' --output text 2>/dev/null); then
        if [[ "$staging_account" == "333204494849" ]]; then
            check_pass "pr-staging profile valid (Account: ${staging_account})"
        else
            check_warn "pr-staging profile: unexpected account ${staging_account}"
        fi
    else
        check_warn "pr-staging profile: authentication failed (staging S3 unavailable)"
    fi
    
    # Test pr-prod profile (S3 production)
    local prod_account
    if prod_account=$(aws sts get-caller-identity --profile pr-prod --query 'Account' --output text 2>/dev/null); then
        if [[ "$prod_account" == "448509429610" ]]; then
            check_pass "pr-prod profile valid (Account: ${prod_account})"
        else
            check_warn "pr-prod profile: unexpected account ${prod_account}"
        fi
    else
        check_warn "pr-prod profile: authentication failed (production S3 unavailable)"
    fi
}

# ==============================================================================
# Phase 3: Secrets Manager
# ==============================================================================

validate_secrets_manager() {
    phase_header "3" "Secrets Manager"
    
    local secrets=(
        "/pulldb/mysql/coordination-db"
        "/pulldb/mysql/localhost-test"
    )
    
    for secret in "${secrets[@]}"; do
        if aws secretsmanager describe-secret --secret-id "$secret" --profile pr-dev &>/dev/null; then
            check_pass "Secret exists: ${secret}"
            
            # Try to get the value
            local secret_value
            if secret_value=$(aws secretsmanager get-secret-value --secret-id "$secret" --profile pr-dev --query 'SecretString' --output text 2>/dev/null); then
                # Validate JSON structure
                if echo "$secret_value" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'host' in d and 'password' in d" 2>/dev/null; then
                    check_pass "Secret valid: ${secret} (has host, password)"
                else
                    check_warn "Secret structure: ${secret} (missing host or password)"
                fi
            else
                check_fail "Secret not readable: ${secret}"
            fi
        else
            check_warn "Secret not found: ${secret}"
        fi
    done
}

# ==============================================================================
# Phase 4: S3 Access
# ==============================================================================

validate_s3_access() {
    phase_header "4" "S3 Backup Access"
    
    # Staging bucket
    local stg_bucket="pestroutesrdsdbs"
    local stg_prefix="daily/stg/"
    local stg_result
    stg_result=$(aws s3 ls "s3://${stg_bucket}/${stg_prefix}" --profile pr-staging 2>&1 || true)
    if [[ -n "$stg_result" && ! "$stg_result" =~ "error" && ! "$stg_result" =~ "denied" ]]; then
        local stg_count
        stg_count=$(echo "$stg_result" | wc -l)
        check_pass "S3 staging: ${stg_count} items in s3://${stg_bucket}/${stg_prefix}"
    else
        check_warn "S3 staging not accessible: s3://${stg_bucket}/${stg_prefix}"
    fi
    
    # Production bucket
    local prod_bucket="pestroutes-rds-backup-prod-vpc-us-east-1-s3"
    local prod_prefix="daily/prod/"
    local prod_result
    prod_result=$(aws s3 ls "s3://${prod_bucket}/${prod_prefix}" --profile pr-prod 2>&1 || true)
    if [[ -n "$prod_result" && ! "$prod_result" =~ "error" && ! "$prod_result" =~ "denied" ]]; then
        local prod_count
        prod_count=$(echo "$prod_result" | wc -l)
        check_pass "S3 production: ${prod_count} items in s3://${prod_bucket}/${prod_prefix}"
    else
        check_warn "S3 production not accessible: s3://${prod_bucket}/${prod_prefix}"
    fi
}

# ==============================================================================
# Phase 5: Database Connectivity
# ==============================================================================

validate_database() {
    phase_header "5" "Database Connectivity"
    
    local python_bin="${INSTALL_PREFIX}/venv/bin/python3"
    
    # Test credential resolution
    local cred_test
    if cred_test=$("$python_bin" << 'PYEOF' 2>&1
import os
import sys
os.chdir(os.environ.get('PULLDB_INSTALL_PREFIX', '/opt/pulldb.service'))

try:
    from pulldb.infra.secrets import CredentialResolver
    resolver = CredentialResolver()
    
    secret_ref = os.environ.get('PULLDB_COORDINATION_SECRET', 'aws-secretsmanager:/pulldb/mysql/coordination-db')
    creds = resolver.resolve(secret_ref)
    
    print(f"host={creds.host}")
    print(f"user={creds.username}")
    print(f"port={creds.port}")
    sys.exit(0)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
PYEOF
    ); then
        local db_host db_user db_port
        db_host=$(echo "$cred_test" | grep '^host=' | cut -d= -f2)
        db_user=$(echo "$cred_test" | grep '^user=' | cut -d= -f2)
        db_port=$(echo "$cred_test" | grep '^port=' | cut -d= -f2)
        check_pass "Credential resolution: ${db_user}@${db_host}:${db_port}"
        
        # Test MySQL connection
        if "$python_bin" << 'PYEOF' 2>/dev/null
import os
os.chdir(os.environ.get('PULLDB_INSTALL_PREFIX', '/opt/pulldb.service'))

from pulldb.infra.secrets import CredentialResolver
from pulldb.infra.mysql import MySQLConnectionManager

resolver = CredentialResolver()
secret_ref = os.environ.get('PULLDB_COORDINATION_SECRET', 'aws-secretsmanager:/pulldb/mysql/coordination-db')
creds = resolver.resolve(secret_ref)

with MySQLConnectionManager(creds) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    cursor.fetchone()
    print("OK")
PYEOF
        then
            check_pass "MySQL connection successful"
        else
            check_fail "MySQL connection failed"
        fi
    else
        check_fail "Credential resolution failed: ${cred_test}"
    fi
    
    # Check schema
    if "$python_bin" << 'PYEOF' 2>/dev/null
import os
os.chdir(os.environ.get('PULLDB_INSTALL_PREFIX', '/opt/pulldb.service'))

from pulldb.infra.secrets import CredentialResolver
from pulldb.infra.mysql import MySQLConnectionManager

resolver = CredentialResolver()
secret_ref = os.environ.get('PULLDB_COORDINATION_SECRET', 'aws-secretsmanager:/pulldb/mysql/coordination-db')
creds = resolver.resolve(secret_ref)

with MySQLConnectionManager(creds) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'pulldb'")
    count = cursor.fetchone()[0]
    if count >= 5:
        print(f"OK: {count} tables")
    else:
        raise Exception(f"Only {count} tables found")
PYEOF
    then
        check_pass "Database schema deployed"
    else
        check_warn "Database schema may be incomplete"
    fi
}

# ==============================================================================
# Phase 6: Service Status
# ==============================================================================

validate_service() {
    phase_header "6" "Service Status"
    
    # Check systemd service
    if systemctl is-active --quiet pulldb-worker 2>/dev/null; then
        check_pass "pulldb-worker service: running"
    else
        local status
        status=$(systemctl is-active pulldb-worker 2>/dev/null || echo "not-found")
        check_warn "pulldb-worker service: ${status}"
    fi
    
    # Check for recent errors in journal
    local recent_errors
    recent_errors=$(journalctl -u pulldb-worker -p err --since "1 hour ago" --no-pager 2>/dev/null | wc -l || echo "0")
    if [[ "$recent_errors" -eq 0 ]]; then
        check_pass "No errors in last hour"
    else
        check_warn "${recent_errors} error(s) in last hour"
    fi
    
    # Check CLI functionality
    local pulldb_bin="${INSTALL_PREFIX}/venv/bin/pulldb"
    if "$pulldb_bin" --help &>/dev/null; then
        check_pass "CLI: pulldb --help"
    else
        check_fail "CLI: pulldb --help failed"
    fi
}

# ==============================================================================
# Phase 7: E2E Restore Test (Optional)
# ==============================================================================

validate_e2e_restore() {
    phase_header "7" "E2E Restore Test"
    
    if [[ "$RUN_E2E" != "true" ]]; then
        check_skip "E2E test not enabled (use --e2e flag)"
        return 0
    fi
    
    local customer="${PULLDB_E2E_CUSTOMER:-qatemplate}"
    local target="${PULLDB_E2E_TARGET:-pulldb_e2e_test}"
    local timeout="${PULLDB_E2E_TIMEOUT:-600}"
    local pulldb_bin="${INSTALL_PREFIX}/venv/bin/pulldb"
    
    check_info "Testing restore: ${customer} → ${target}"
    
    # Create restore request
    local request_output
    if ! request_output=$("$pulldb_bin" restore request \
        --customer "$customer" \
        --target-db "$target" \
        --user "service-validator" \
        --json 2>&1); then
        check_fail "Failed to create restore request"
        echo "    Error: ${request_output}" | head -3
        return 1
    fi
    
    local request_id
    request_id=$(echo "$request_output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('request_id',''))" 2>/dev/null)
    
    if [[ -z "$request_id" ]]; then
        check_fail "No request ID returned"
        return 1
    fi
    
    check_pass "Restore request created: ${request_id}"
    
    # Monitor progress
    local start_time elapsed status
    start_time=$(date +%s)
    
    while true; do
        elapsed=$(($(date +%s) - start_time))
        
        if [[ "$elapsed" -gt "$timeout" ]]; then
            check_fail "Restore timed out after ${timeout}s"
            return 1
        fi
        
        status=$("$pulldb_bin" restore status "$request_id" --json 2>/dev/null | \
            python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
        
        case "$status" in
            completed|success)
                check_pass "Restore completed in ${elapsed}s"
                break
                ;;
            failed|error)
                check_fail "Restore failed"
                "$pulldb_bin" restore status "$request_id" 2>&1 | head -10
                return 1
                ;;
            queued|pending|downloading|extracting|restoring)
                printf "\r  [%3ds] Status: %-15s" "$elapsed" "$status"
                sleep 5
                ;;
            *)
                check_warn "Unknown status: ${status}"
                sleep 5
                ;;
        esac
    done
    printf "\n"
    
    # Verify restored database
    local python_bin="${INSTALL_PREFIX}/venv/bin/python3"
    local table_count
    if table_count=$("$python_bin" << PYEOF 2>/dev/null
import os
os.chdir(os.environ.get('PULLDB_INSTALL_PREFIX', '/opt/pulldb.service'))

from pulldb.infra.secrets import CredentialResolver
from pulldb.infra.mysql import MySQLConnectionManager

resolver = CredentialResolver()
secret_ref = os.environ.get('PULLDB_TARGET_SECRET', 'aws-secretsmanager:/pulldb/mysql/localhost-test')
creds = resolver.resolve(secret_ref)

with MySQLConnectionManager(creds) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '${target}'")
    print(cursor.fetchone()[0])
PYEOF
    ); then
        if [[ "$table_count" -gt 0 ]]; then
            check_pass "Restored database has ${table_count} tables"
        else
            check_fail "Restored database is empty"
        fi
    else
        check_warn "Could not verify restored database"
    fi
    
    # Cleanup
    check_info "Cleaning up test database..."
    "$python_bin" << PYEOF 2>/dev/null || true
import os
os.chdir(os.environ.get('PULLDB_INSTALL_PREFIX', '/opt/pulldb.service'))

from pulldb.infra.secrets import CredentialResolver
from pulldb.infra.mysql import MySQLConnectionManager

resolver = CredentialResolver()
secret_ref = os.environ.get('PULLDB_TARGET_SECRET', 'aws-secretsmanager:/pulldb/mysql/localhost-test')
creds = resolver.resolve(secret_ref)

with MySQLConnectionManager(creds) as conn:
    cursor = conn.cursor()
    cursor.execute("DROP DATABASE IF EXISTS \`${target}\`")
PYEOF
    check_pass "Test database cleaned up"
}

# ==============================================================================
# Usage and Argument Parsing
# ==============================================================================

usage() {
    cat << 'EOF'
pullDB Production Service Validation

Usage:
  sudo ./service-validate.sh [OPTIONS]

Options:
  --quick       Quick validation (skip S3 and E2E tests)
  --full        Full validation (default)
  --e2e         Include E2E restore test
  --dry-run     Show what would be done
  --help        Show this help

Examples:
  sudo ./service-validate.sh              # Full validation
  sudo ./service-validate.sh --quick      # Quick validation
  sudo ./service-validate.sh --e2e        # Full + E2E restore test
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --quick)
                RUN_FULL=false
                shift
                ;;
            --full)
                RUN_FULL=true
                shift
                ;;
            --e2e)
                RUN_E2E=true
                shift
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                usage
                exit 2
                ;;
        esac
    done
}

# ==============================================================================
# Main
# ==============================================================================

main() {
    parse_args "$@"
    
    banner
    
    echo "  Configuration:"
    echo "    Install Prefix: ${INSTALL_PREFIX}"
    echo "    Full Tests:     ${RUN_FULL}"
    echo "    E2E Test:       ${RUN_E2E}"
    echo "    Log File:       ${LOG_FILE}"
    echo ""
    
    # Load environment
    if load_env; then
        check_info "Loaded environment from ${INSTALL_PREFIX}/.env"
    else
        check_warn "No .env file found"
    fi
    
    # Run validation phases
    validate_prerequisites
    validate_installation
    validate_aws_credentials
    validate_secrets_manager
    
    if [[ "$RUN_FULL" == "true" ]]; then
        validate_s3_access
    fi
    
    validate_database
    validate_service
    
    if [[ "$RUN_E2E" == "true" ]]; then
        validate_e2e_restore
    fi
    
    # Summary
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "  VALIDATION SUMMARY"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  ${GREEN}Passed:${NC}   ${PASSED}"
    echo -e "  ${RED}Failed:${NC}   ${FAILED}"
    echo -e "  ${YELLOW}Warnings:${NC} ${WARNINGS}"
    echo -e "  ${BLUE}Skipped:${NC}  ${SKIPPED}"
    echo ""
    echo "  Log: ${LOG_FILE}"
    echo ""
    
    if [[ "$FAILED" -gt 0 ]]; then
        echo -e "${RED}${BOLD}❌ VALIDATION FAILED${NC}"
        echo ""
        exit 1
    elif [[ "$WARNINGS" -gt 0 ]]; then
        echo -e "${YELLOW}${BOLD}⚠️  VALIDATION PASSED WITH WARNINGS${NC}"
        echo ""
        exit 0
    else
        echo -e "${GREEN}${BOLD}✅ VALIDATION PASSED${NC}"
        echo ""
        exit 0
    fi
}

main "$@"
