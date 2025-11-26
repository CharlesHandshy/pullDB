#!/usr/bin/env bash
# ==============================================================================
# Phase 0: Prerequisites Check
# ==============================================================================
# Validates system requirements before proceeding with validation
#
# Checks:
#   - Python version (3.10+)
#   - MySQL server running
#   - AWS credentials (pr-dev for secrets)
#   - S3 access (pr-staging for backups) - optional
#   - Disk space requirements

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source common library
source "${SCRIPT_DIR}/../lib/validate-common.sh"

# ------------------------------------------------------------------------------
# Check Functions
# ------------------------------------------------------------------------------

check_python() {
    if ! command_exists python3; then
        check_fail "Python 3 not found"
        return 1
    fi
    
    local version
    version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)
    
    if [[ "$major" -lt 3 ]] || [[ "$major" -eq 3 && "$minor" -lt 10 ]]; then
        check_fail "Python ${version} found, need 3.10+"
        return 1
    fi
    
    check_pass "Python ${version} found"
    return 0
}

check_mysql_server() {
    # Check if MySQL client is available
    if ! command_exists mysql; then
        check_fail "MySQL client not found"
        return 1
    fi
    
    # Check if MySQL server is running
    if command_exists systemctl; then
        if systemctl is-active --quiet mysql 2>/dev/null || systemctl is-active --quiet mariadb 2>/dev/null; then
            local version
            version=$(mysql --version 2>/dev/null | head -1 | grep -oP '\d+\.\d+\.\d+' | head -1 || echo "unknown")
            check_pass "MySQL ${version} running"
            return 0
        fi
    fi
    
    # Fallback: try to connect
    if mysql -u root -e "SELECT 1" &>/dev/null || sudo mysql -u root -e "SELECT 1" &>/dev/null; then
        check_pass "MySQL server accessible"
        return 0
    fi
    
    check_fail "MySQL server not running or not accessible"
    return 1
}

check_aws_credentials_dev() {
    local profile="${PULLDB_AWS_PROFILE:-pr-dev}"
    
    # Check if AWS CLI is available
    if ! command_exists aws; then
        check_warn "AWS CLI not installed (some tests will be skipped)"
        return 0
    fi
    
    # Try to get caller identity
    local account_id
    if account_id=$(aws sts get-caller-identity --profile "$profile" --query 'Account' --output text 2>/dev/null); then
        check_pass "AWS profile '${profile}' valid (Account: ${account_id})"
        return 0
    fi
    
    # Try default/instance profile
    if account_id=$(aws sts get-caller-identity --query 'Account' --output text 2>/dev/null); then
        check_pass "AWS credentials valid via default chain (Account: ${account_id})"
        return 0
    fi
    
    check_warn "AWS credentials not configured (integration tests will use local overrides)"
    return 0
}

check_aws_s3_access() {
    local bucket="pestroutesrdsdbs"
    
    if ! command_exists aws; then
        check_skip "AWS CLI not installed - skipping S3 check"
        return 0
    fi
    
    # Try pr-staging first (staging backups)
    local stg_result
    stg_result=$(aws s3 ls "s3://${bucket}/daily/stg/" --profile pr-staging 2>&1 || true)
    if [[ -n "$stg_result" && ! "$stg_result" =~ "error" && ! "$stg_result" =~ "denied" ]]; then
        check_pass "S3 staging bucket accessible via 'pr-staging'"
        return 0
    fi
    
    # Try pr-prod (production backups)
    local prod_result
    prod_result=$(aws s3 ls "s3://${bucket}/daily/prod/" --profile pr-prod 2>&1 || true)
    if [[ -n "$prod_result" && ! "$prod_result" =~ "error" && ! "$prod_result" =~ "denied" ]]; then
        check_pass "S3 production bucket accessible via 'pr-prod'"
        return 0
    fi
    
    # Try with PULLDB_S3_AWS_PROFILE if set
    local s3_profile="${PULLDB_S3_AWS_PROFILE:-}"
    if [[ -n "$s3_profile" ]]; then
        local custom_result
        custom_result=$(aws s3 ls "s3://${bucket}/" --profile "$s3_profile" 2>&1 || true)
        if [[ -n "$custom_result" && ! "$custom_result" =~ "error" && ! "$custom_result" =~ "denied" ]]; then
            check_pass "S3 bucket accessible via '${s3_profile}'"
            return 0
        fi
    fi
    
    check_warn "S3 bucket not accessible (E2E tests will be skipped)"
    check_info "  Tried profiles: pr-staging, pr-prod${s3_profile:+, $s3_profile}"
    return 0
}

check_disk_space() {
    local required_gb="${1:-10}"
    local check_path="${2:-/tmp}"
    
    local available_gb
    available_gb=$(check_disk_space_gb "$check_path")
    
    if [[ "$available_gb" -lt "$required_gb" ]]; then
        check_fail "Disk space: ${available_gb}GB available at ${check_path} (need ${required_gb}GB)"
        return 1
    fi
    
    check_pass "Disk space: ${available_gb}GB available at ${check_path}"
    return 0
}

check_project_structure() {
    # Verify we're in a valid pulldb project
    local required_files=(
        "pyproject.toml"
        "pulldb/__init__.py"
        "pulldb/tests/conftest.py"
        "schema/pulldb"
        ".env"
    )
    
    local missing=0
    for file in "${required_files[@]}"; do
        if [[ ! -e "${PROJECT_ROOT}/${file}" ]]; then
            check_fail "Missing required file: ${file}"
            ((missing++))
        fi
    done
    
    if [[ "$missing" -eq 0 ]]; then
        check_pass "Project structure valid"
        return 0
    fi
    
    return 1
}

check_venv_or_create() {
    local venv_path="${PROJECT_ROOT}/venv"
    
    if [[ -d "$venv_path" && -f "$venv_path/bin/activate" ]]; then
        # Verify pulldb is installed
        if "$venv_path/bin/python" -c "import pulldb" &>/dev/null; then
            check_pass "Virtual environment exists with pulldb installed"
            return 0
        else
            check_warn "Virtual environment exists but pulldb not installed"
        fi
    fi
    
    check_info "Virtual environment will be created/updated during installation phase"
    return 0
}

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

run_prerequisites() {
    phase_header "0" "Prerequisites"
    
    local failed=0
    
    check_python || ((failed++))
    check_mysql_server || ((failed++))
    check_aws_credentials_dev
    check_aws_s3_access
    check_disk_space 10 "/tmp"
    check_project_structure || ((failed++))
    check_venv_or_create
    
    return "$failed"
}

# Allow sourcing or direct execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    run_prerequisites
fi
