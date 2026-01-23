#!/usr/bin/env bash
# ==============================================================================
# Phase 3: Integration Tests
# ==============================================================================
# Tests AWS integration, S3 discovery, and CLI functionality
#
# Tests:
#   - Secrets Manager access
#   - S3 backup discovery
#   - CLI commands (status, --help)
#   - Database connectivity

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source common library
source "${SCRIPT_DIR}/../lib/validate-common.sh"

# ------------------------------------------------------------------------------
# Integration Test Functions
# ------------------------------------------------------------------------------

test_secrets_manager() {
    local profile="${PULLDB_AWS_PROFILE:-pr-dev}"
    local secret_id="/pulldb/mysql/coordination-db"
    
    if ! command_exists aws; then
        check_skip "AWS CLI not available - skipping Secrets Manager test"
        return 0
    fi
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would test Secrets Manager access"
        return 0
    fi
    
    # Try to describe the secret (doesn't retrieve value, just metadata)
    local result
    if result=$(aws secretsmanager describe-secret \
        --secret-id "$secret_id" \
        --profile "$profile" \
        --query 'Name' \
        --output text 2>&1); then
        check_pass "Secrets Manager: ${secret_id} accessible"
        return 0
    fi
    
    # Try with default/instance profile
    if result=$(aws secretsmanager describe-secret \
        --secret-id "$secret_id" \
        --query 'Name' \
        --output text 2>&1); then
        check_pass "Secrets Manager: ${secret_id} accessible (via instance profile)"
        return 0
    fi
    
    check_warn "Secrets Manager: ${secret_id} not accessible (${result})"
    return 0
}

test_s3_discovery() {
    local s3_profile="${PULLDB_S3_AWS_PROFILE:-pr-staging}"
    local bucket_path="${PULLDB_S3_BUCKET_PATH:-pestroutesrdsdbs/daily/stg/}"
    
    if ! command_exists aws; then
        check_skip "AWS CLI not available - skipping S3 discovery test"
        return 0
    fi
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would test S3 discovery"
        return 0
    fi
    
    # Extract bucket and prefix
    local bucket prefix
    bucket=$(echo "$bucket_path" | cut -d/ -f1)
    prefix=$(echo "$bucket_path" | cut -d/ -f2-)
    
    # Count objects in the prefix
    local count
    count=$(aws s3 ls "s3://${bucket}/${prefix}" \
        --profile "$s3_profile" \
        2>/dev/null | wc -l || echo "0")
    
    if [[ "$count" -gt 0 ]]; then
        check_pass "S3 Discovery: Found ${count} items in s3://${bucket}/${prefix}"
        return 0
    fi
    
    check_warn "S3 Discovery: No backups found in s3://${bucket}/${prefix}"
    return 0
}

test_cli_help() {
    local venv_path="${VALIDATE_PREFIX:-${PROJECT_ROOT}}/venv"
    local pulldb_bin="${venv_path}/bin/pulldb"
    
    if [[ ! -f "$pulldb_bin" ]]; then
        pulldb_bin="${PROJECT_ROOT}/venv/bin/pulldb"
    fi
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would test CLI help"
        return 0
    fi
    
    if [[ ! -f "$pulldb_bin" ]]; then
        check_fail "pulldb CLI not found"
        return 1
    fi
    
    # Test --help
    local log_file="${VALIDATE_LOG_FILE:-/dev/null}"
    if "$pulldb_bin" --help >> "$log_file" 2>&1; then
        check_pass "CLI: pulldb --help returns 0"
    else
        check_fail "CLI: pulldb --help failed"
        return 1
    fi
    
    # Test restore --help
    if "$pulldb_bin" restore --help >> "$log_file" 2>&1; then
        check_pass "CLI: pulldb restore --help returns 0"
    else
        check_warn "CLI: pulldb restore --help failed"
    fi
    
    return 0
}

test_cli_status() {
    local venv_path="${VALIDATE_PREFIX:-${PROJECT_ROOT}}/venv"
    local pulldb_bin="${venv_path}/bin/pulldb"
    
    if [[ ! -f "$pulldb_bin" ]]; then
        pulldb_bin="${PROJECT_ROOT}/venv/bin/pulldb"
    fi
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would test CLI status"
        return 0
    fi
    
    # Set MySQL credentials for status command
    export PULLDB_TEST_MYSQL_HOST="${PULLDB_TEST_MYSQL_HOST:-localhost}"
    export PULLDB_TEST_MYSQL_USER="${PULLDB_TEST_MYSQL_USER:-pulldb_test}"
    export PULLDB_TEST_MYSQL_PASSWORD="${PULLDB_TEST_MYSQL_PASSWORD:-test123}"
    
    # Source .env if exists
    if [[ -f "${PROJECT_ROOT}/.env" ]]; then
        set -a
        source "${PROJECT_ROOT}/.env"
        set +a
    fi
    
    # Test status command (may fail if DB not configured, that's OK)
    local status_output
    if status_output=$("$pulldb_bin" status --json 2>&1); then
        # Verify it's valid JSON
        if echo "$status_output" | python3 -m json.tool &>/dev/null; then
            check_pass "CLI: pulldb status returns valid JSON"
            return 0
        else
            check_warn "CLI: pulldb status output is not valid JSON"
            return 0
        fi
    else
        # Status command failed - check if it's a connectivity issue
        if echo "$status_output" | grep -qi "database\|connection\|mysql"; then
            check_warn "CLI: pulldb status failed (database connectivity)"
        else
            check_warn "CLI: pulldb status failed"
        fi
        local log_file="${VALIDATE_LOG_FILE:-/dev/null}"
        echo "$status_output" >> "$log_file"
        return 0
    fi
}

test_database_connectivity() {
    local host="${PULLDB_TEST_MYSQL_HOST:-localhost}"
    local user="${PULLDB_TEST_MYSQL_USER:-pulldb_test}"
    local password="${PULLDB_TEST_MYSQL_PASSWORD:-test123}"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would test database connectivity"
        return 0
    fi
    
    # Test MySQL connection
    if mysql -h "$host" -u "$user" -p"$password" -e "SELECT 1" &>/dev/null; then
        check_pass "Database: MySQL connection successful"
        return 0
    fi
    
    # Try with socket auth
    if sudo mysql -e "SELECT 1" &>/dev/null; then
        check_pass "Database: MySQL connection successful (socket auth)"
        return 0
    fi
    
    check_warn "Database: MySQL connection failed (tests will use fixtures)"
    return 0
}

test_schema_deployment() {
    local host="${PULLDB_TEST_MYSQL_HOST:-localhost}"
    local user="${PULLDB_TEST_MYSQL_USER:-pulldb_test}"
    local password="${PULLDB_TEST_MYSQL_PASSWORD:-test123}"
    local database="pulldb_service"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would test schema deployment"
        return 0
    fi
    
    # Check if database exists and has tables
    local table_count
    table_count=$(mysql -h "$host" -u "$user" -p"$password" -N -e \
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${database}'" 2>/dev/null || echo "0")
    
    if [[ "$table_count" -gt 0 ]]; then
        check_pass "Database: Schema deployed (${table_count} tables)"
        return 0
    fi
    
    check_info "Database: Schema will be created by test fixtures"
    return 0
}

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

run_integration_tests() {
    phase_header "3" "Integration Tests"
    
    local failed=0
    
    test_secrets_manager
    test_s3_discovery
    test_cli_help || ((failed++))
    test_cli_status
    test_database_connectivity
    test_schema_deployment
    
    return "$failed"
}

# Allow sourcing or direct execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    VALIDATE_LOG_FILE="${VALIDATE_LOG_FILE:-/tmp/pulldb-validate-integration.log}"
    touch "$VALIDATE_LOG_FILE"
    run_integration_tests
fi
