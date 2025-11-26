#!/usr/bin/env bash
# ==============================================================================
# Phase 2: Unit Tests
# ==============================================================================
# Runs the pytest unit test suite with appropriate configuration
#
# Features:
#   - Uses auto-database creation from conftest.py
#   - Supports local MySQL override
#   - Reports pass/fail/skip counts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source common library
source "${SCRIPT_DIR}/../lib/validate-common.sh"

# ------------------------------------------------------------------------------
# Test Configuration
# ------------------------------------------------------------------------------

# Default MySQL test credentials (used when AWS not available)
MYSQL_TEST_HOST="${PULLDB_TEST_MYSQL_HOST:-localhost}"
MYSQL_TEST_USER="${PULLDB_TEST_MYSQL_USER:-pulldb_test}"
MYSQL_TEST_PASSWORD="${PULLDB_TEST_MYSQL_PASSWORD:-test123}"

# ------------------------------------------------------------------------------
# Test Functions
# ------------------------------------------------------------------------------

setup_test_mysql_user() {
    # Check if we need to create the test user
    if mysql -u "$MYSQL_TEST_USER" -p"$MYSQL_TEST_PASSWORD" -e "SELECT 1" &>/dev/null; then
        check_info "MySQL test user already configured"
        return 0
    fi
    
    # Try to create user with sudo mysql (auth_socket)
    if sudo mysql -e "SELECT 1" &>/dev/null; then
        check_info "Creating MySQL test user..."
        
        sudo mysql << EOF
CREATE USER IF NOT EXISTS '${MYSQL_TEST_USER}'@'localhost' IDENTIFIED WITH caching_sha2_password BY '${MYSQL_TEST_PASSWORD}';
GRANT ALL PRIVILEGES ON \`pulldb\`.* TO '${MYSQL_TEST_USER}'@'localhost';
GRANT CREATE ON *.* TO '${MYSQL_TEST_USER}'@'localhost';
FLUSH PRIVILEGES;
EOF
        
        if [[ $? -eq 0 ]]; then
            check_pass "MySQL test user created"
            return 0
        fi
    fi
    
    check_warn "Could not create MySQL test user (tests may fail)"
    return 0
}

run_pytest() {
    local venv_path="${VALIDATE_PREFIX:-${PROJECT_ROOT}}/venv"
    local pytest_bin="${venv_path}/bin/pytest"
    local test_dir="${PROJECT_ROOT}/pulldb/tests"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would run: pytest ${test_dir}"
        return 0
    fi
    
    # Use project venv if validation prefix doesn't have one
    if [[ ! -f "$pytest_bin" ]]; then
        pytest_bin="${PROJECT_ROOT}/venv/bin/pytest"
    fi
    
    if [[ ! -f "$pytest_bin" ]]; then
        check_fail "pytest not found in venv"
        return 1
    fi
    
    # Set up environment for tests
    export PULLDB_TEST_MYSQL_HOST="$MYSQL_TEST_HOST"
    export PULLDB_TEST_MYSQL_USER="$MYSQL_TEST_USER"
    export PULLDB_TEST_MYSQL_PASSWORD="$MYSQL_TEST_PASSWORD"
    
    # Run pytest with minimal output
    local test_output
    local exit_code=0
    
    check_info "Running pytest (this may take ~90 seconds)..."
    
    # Run tests and capture output
    test_output=$("$pytest_bin" "$test_dir" \
        --tb=no \
        -q \
        --timeout=120 \
        2>&1) || exit_code=$?
    
    # Log full output
    if [[ -n "${VALIDATE_LOG_FILE:-}" && -f "$VALIDATE_LOG_FILE" ]]; then
        echo "$test_output" >> "$VALIDATE_LOG_FILE"
    fi
    
    # Parse results from pytest output
    # Format: "227 passed, 1 skipped, 1 xfailed in 89.04s"
    local summary_line
    summary_line=$(echo "$test_output" | grep -E "^\d+ passed" | tail -1 || echo "")
    
    if [[ -n "$summary_line" ]]; then
        # Extract counts
        local passed skipped failed xfailed
        passed=$(echo "$summary_line" | grep -oP '\d+(?= passed)' || echo "0")
        skipped=$(echo "$summary_line" | grep -oP '\d+(?= skipped)' || echo "0")
        failed=$(echo "$summary_line" | grep -oP '\d+(?= failed)' || echo "0")
        xfailed=$(echo "$summary_line" | grep -oP '\d+(?= xfailed)' || echo "0")
        
        if [[ "$exit_code" -eq 0 ]] || [[ "$failed" -eq "0" ]]; then
            check_pass "${passed} passed, ${skipped} skipped, ${xfailed} xfailed"
            return 0
        else
            check_fail "${passed} passed, ${failed} FAILED, ${skipped} skipped"
            # Show failed test names
            echo ""
            echo "  Failed tests:"
            echo "$test_output" | grep -E "^FAILED" | head -10 | while read -r line; do
                echo "    ${line}"
            done
            return 1
        fi
    else
        # Couldn't parse output
        if [[ "$exit_code" -eq 0 ]]; then
            check_pass "Tests completed successfully"
            return 0
        else
            check_fail "Tests failed (exit code: ${exit_code})"
            echo ""
            echo "  Last 20 lines of output:"
            echo "$test_output" | tail -20 | while read -r line; do
                echo "    ${line}"
            done
            return 1
        fi
    fi
}

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

run_unit_tests() {
    phase_header "2" "Unit Tests"
    
    local failed=0
    
    setup_test_mysql_user
    run_pytest || ((failed++))
    
    return "$failed"
}

# Allow sourcing or direct execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    VALIDATE_LOG_FILE="${VALIDATE_LOG_FILE:-/tmp/pulldb-validate-unit-tests.log}"
    touch "$VALIDATE_LOG_FILE"
    run_unit_tests
fi
