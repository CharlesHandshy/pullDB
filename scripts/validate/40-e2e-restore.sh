#!/usr/bin/env bash
# ==============================================================================
# Phase 4: End-to-End Restore Test
# ==============================================================================
# Performs a complete restore using a small staging backup
#
# This phase is optional and only runs with --e2e flag
#
# Uses: qatemplate (smallest customer database for testing)
# Safety: Uses staging S3 bucket, isolated test database

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source common library
source "${SCRIPT_DIR}/../lib/validate-common.sh"

# ------------------------------------------------------------------------------
# E2E Configuration
# ------------------------------------------------------------------------------

# Default test customer - smallest database for quick testing
E2E_TEST_CUSTOMER="${PULLDB_E2E_CUSTOMER:-qatemplate}"
E2E_TEST_TARGET="${PULLDB_E2E_TARGET:-pulldb_e2e_test}"
E2E_TIMEOUT="${PULLDB_E2E_TIMEOUT:-600}"  # 10 minutes max

# ------------------------------------------------------------------------------
# E2E Test Functions
# ------------------------------------------------------------------------------

find_suitable_backup() {
    local customer="$1"
    local s3_profile="${PULLDB_S3_AWS_PROFILE:-pr-staging}"
    local bucket_path="${PULLDB_S3_BUCKET_PATH:-pestroutesrdsdbs/daily/stg/}"
    
    # Extract bucket and prefix
    local bucket prefix
    bucket=$(echo "$bucket_path" | cut -d/ -f1)
    prefix=$(echo "$bucket_path" | cut -d/ -f2-)
    
    # Find most recent backup for customer
    local backup_path
    backup_path=$(aws s3 ls "s3://${bucket}/${prefix}${customer}/" \
        --profile "$s3_profile" \
        --recursive \
        2>/dev/null | grep -E '\.gz$|\.sql$' | sort -k1,2 | tail -1 | awk '{print $4}')
    
    if [[ -n "$backup_path" ]]; then
        echo "s3://${bucket}/${backup_path}"
        return 0
    fi
    
    return 1
}

cleanup_e2e_database() {
    local host="${PULLDB_TEST_MYSQL_HOST:-localhost}"
    local user="${PULLDB_TEST_MYSQL_USER:-pulldb_test}"
    local password="${PULLDB_TEST_MYSQL_PASSWORD:-test123}"
    local database="$E2E_TEST_TARGET"
    
    mysql -h "$host" -u "$user" -p"$password" \
        -e "DROP DATABASE IF EXISTS \`${database}\`" 2>/dev/null || true
}

run_e2e_restore() {
    phase_header "4" "End-to-End Restore Test"
    
    if [[ "${VALIDATE_E2E:-false}" != "true" ]]; then
        check_skip "E2E tests not enabled (use --e2e flag)"
        return 0
    fi
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would run E2E restore for ${E2E_TEST_CUSTOMER}"
        return 0
    fi
    
    local venv_path="${VALIDATE_PREFIX:-${PROJECT_ROOT}}/venv"
    local pulldb_bin="${venv_path}/bin/pulldb"
    
    if [[ ! -f "$pulldb_bin" ]]; then
        pulldb_bin="${PROJECT_ROOT}/venv/bin/pulldb"
    fi
    
    if [[ ! -f "$pulldb_bin" ]]; then
        check_fail "pulldb CLI not found - cannot run E2E test"
        return 1
    fi
    
    # Load environment
    if [[ -f "${PROJECT_ROOT}/.env" ]]; then
        set -a
        source "${PROJECT_ROOT}/.env"
        set +a
    fi
    
    check_info "E2E: Testing restore of ${E2E_TEST_CUSTOMER} → ${E2E_TEST_TARGET}"
    
    # Find suitable backup
    check_item "Finding backup for ${E2E_TEST_CUSTOMER}..."
    local backup_path
    if ! backup_path=$(find_suitable_backup "$E2E_TEST_CUSTOMER"); then
        check_warn "E2E: No backup found for ${E2E_TEST_CUSTOMER}"
        return 0
    fi
    check_pass "E2E: Found backup: ${backup_path}"
    
    # Clean up any previous test database
    cleanup_e2e_database
    check_info "E2E: Cleaned up previous test database"
    
    # Create restore request
    check_item "Creating restore request..."
    
    local request_output
    local request_id
    
    request_output=$("$pulldb_bin" restore request \
        --customer "$E2E_TEST_CUSTOMER" \
        --target-db "$E2E_TEST_TARGET" \
        --user "pulldb_validator" \
        --json \
        2>&1)
    
    if ! echo "$request_output" | python3 -m json.tool &>/dev/null; then
        check_fail "E2E: Failed to create restore request"
        echo "$request_output" >> "$VALIDATE_LOG_FILE"
        return 1
    fi
    
    request_id=$(echo "$request_output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('request_id',''))")
    
    if [[ -z "$request_id" ]]; then
        check_fail "E2E: No request ID returned"
        return 1
    fi
    
    check_pass "E2E: Created restore request ${request_id}"
    
    # Monitor progress
    check_item "Monitoring restore progress..."
    
    local start_time elapsed status
    start_time=$(date +%s)
    
    while true; do
        elapsed=$(($(date +%s) - start_time))
        
        if [[ "$elapsed" -gt "$E2E_TIMEOUT" ]]; then
            check_fail "E2E: Restore timed out after ${E2E_TIMEOUT}s"
            return 1
        fi
        
        status=$("$pulldb_bin" restore status "$request_id" --json 2>/dev/null | \
            python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
        
        case "$status" in
            completed|success)
                check_pass "E2E: Restore completed successfully (${elapsed}s)"
                break
                ;;
            failed|error)
                check_fail "E2E: Restore failed"
                "$pulldb_bin" restore status "$request_id" >> "$VALIDATE_LOG_FILE" 2>&1
                return 1
                ;;
            queued|pending|downloading|extracting|restoring)
                printf "\r  [%3ds] Status: %-15s" "$elapsed" "$status"
                sleep 5
                ;;
            *)
                check_warn "E2E: Unknown status: ${status}"
                sleep 5
                ;;
        esac
    done
    printf "\n"
    
    # Validate restore result
    check_item "Validating restored database..."
    
    local host="${PULLDB_TEST_MYSQL_HOST:-localhost}"
    local user="${PULLDB_TEST_MYSQL_USER:-pulldb_test}"
    local password="${PULLDB_TEST_MYSQL_PASSWORD:-test123}"
    
    local table_count
    table_count=$(mysql -h "$host" -u "$user" -p"$password" -N -e \
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${E2E_TEST_TARGET}'" 2>/dev/null || echo "0")
    
    if [[ "$table_count" -gt 0 ]]; then
        check_pass "E2E: Database ${E2E_TEST_TARGET} has ${table_count} tables"
    else
        check_fail "E2E: Database ${E2E_TEST_TARGET} has no tables"
        return 1
    fi
    
    # Cleanup
    check_item "Cleaning up test database..."
    cleanup_e2e_database
    check_pass "E2E: Test database cleaned up"
    
    check_pass "E2E restore test completed successfully"
    return 0
}

# Allow sourcing or direct execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    VALIDATE_LOG_FILE="${VALIDATE_LOG_FILE:-/tmp/pulldb-validate-e2e.log}"
    touch "$VALIDATE_LOG_FILE"
    VALIDATE_E2E="${VALIDATE_E2E:-true}"  # Assume E2E when run directly
    run_e2e_restore
fi
