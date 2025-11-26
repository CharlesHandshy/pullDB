#!/usr/bin/env bash
# ==============================================================================
# Phase 5: Teardown and Report
# ==============================================================================
# Cleans up test artifacts and generates final validation report
#
# Actions:
#   - Kill any background processes started during validation
#   - Remove installation directory (if isolated install was used)
#   - Drop test databases
#   - Generate summary report

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source common library
source "${SCRIPT_DIR}/../lib/validate-common.sh"

# ------------------------------------------------------------------------------
# Cleanup Functions
# ------------------------------------------------------------------------------

kill_background_processes() {
    check_item "Checking for background processes..."
    
    # Find and kill any pulldb worker processes started during validation
    local pids
    pids=$(pgrep -f "pulldb.*worker" 2>/dev/null || true)
    
    if [[ -n "$pids" ]]; then
        check_warn "Found pulldb worker processes: ${pids}"
        if [[ "$VALIDATE_DRY_RUN" == true ]]; then
            check_info "[DRY-RUN] Would kill PIDs: ${pids}"
        else
            for pid in $pids; do
                if kill -0 "$pid" 2>/dev/null; then
                    kill "$pid" 2>/dev/null || true
                    check_info "Killed process $pid"
                fi
            done
        fi
    else
        check_pass "No orphan pulldb processes found"
    fi
}

remove_install_directory() {
    local install_dir="${VALIDATE_PREFIX:-}"
    
    if [[ -z "$install_dir" || "$install_dir" == "/" ]]; then
        check_info "No isolated install directory to remove"
        return 0
    fi
    
    if [[ ! -d "$install_dir" ]]; then
        check_info "Install directory already removed: ${install_dir}"
        return 0
    fi
    
    # Safety check - only remove if it's in /tmp
    if [[ "$install_dir" != /tmp/pulldb-* ]]; then
        check_warn "Not removing install directory (not in /tmp): ${install_dir}"
        return 0
    fi
    
    local size
    size=$(du -sh "$install_dir" 2>/dev/null | cut -f1 || echo "unknown")
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would remove ${install_dir} (${size})"
        return 0
    fi
    
    check_item "Removing install directory (${size})..."
    rm -rf "$install_dir"
    check_pass "Removed: ${install_dir}"
}

drop_test_databases() {
    local host="${PULLDB_TEST_MYSQL_HOST:-localhost}"
    local user="${PULLDB_TEST_MYSQL_USER:-pulldb_test}"
    local password="${PULLDB_TEST_MYSQL_PASSWORD:-test123}"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would drop test databases"
        return 0
    fi
    
    check_item "Cleaning up test databases..."
    
    # Drop E2E test database if exists
    local e2e_db="${PULLDB_E2E_TARGET:-pulldb_e2e_test}"
    if mysql -h "$host" -u "$user" -p"$password" \
        -e "DROP DATABASE IF EXISTS \`${e2e_db}\`" 2>/dev/null; then
        check_info "Dropped: ${e2e_db}"
    fi
    
    # Drop validation test database if exists
    local validate_db="pulldb_validate_test"
    if mysql -h "$host" -u "$user" -p"$password" \
        -e "DROP DATABASE IF EXISTS \`${validate_db}\`" 2>/dev/null; then
        check_info "Dropped: ${validate_db}"
    fi
    
    check_pass "Test databases cleaned up"
}

remove_temp_files() {
    check_item "Cleaning up temporary files..."
    
    local temp_files=(
        "/tmp/pulldb-validate-*.log"
        "/tmp/pulldb-test-*"
    )
    
    local count=0
    for pattern in "${temp_files[@]}"; do
        for file in $pattern; do
            if [[ -e "$file" ]]; then
                if [[ "$VALIDATE_DRY_RUN" == true ]]; then
                    check_info "[DRY-RUN] Would remove: ${file}"
                else
                    rm -rf "$file" 2>/dev/null && ((count++)) || true
                fi
            fi
        done
    done
    
    if [[ "$count" -gt 0 ]]; then
        check_pass "Removed ${count} temporary files"
    else
        check_info "No temporary files to remove"
    fi
}

# ------------------------------------------------------------------------------
# Report Generation
# ------------------------------------------------------------------------------

generate_summary_report() {
    local report_file="${VALIDATE_PREFIX:-/tmp}/pulldb-validation-report.md"
    local log_file="${VALIDATE_LOG_FILE:-/tmp/pulldb-validate.log}"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would generate report at ${report_file}"
        return 0
    fi
    
    cat > "$report_file" << EOF
# pullDB Validation Report

**Generated:** $(date -Iseconds)
**Host:** $(hostname)
**User:** $(whoami)

## Environment

| Component | Value |
|-----------|-------|
| OS | $(uname -s) $(uname -r) |
| Python | $(python3 --version 2>/dev/null | cut -d' ' -f2 || echo "N/A") |
| MySQL | $(mysql --version 2>/dev/null | head -1 || echo "N/A") |
| AWS CLI | $(aws --version 2>/dev/null | cut -d' ' -f1 || echo "N/A") |

## Validation Level

$(if [[ "${VALIDATE_E2E:-false}" == "true" ]]; then
    echo "**Level:** E2E (Full end-to-end restore test)"
elif [[ "${VALIDATE_FULL:-false}" == "true" ]]; then
    echo "**Level:** Full (Prerequisites + Unit + Integration)"
else
    echo "**Level:** Quick (Prerequisites + Unit tests only)"
fi)

## Phase Results

EOF

    # Parse log file for results
    if [[ -f "$log_file" ]]; then
        # Count passes, fails, warnings, skips
        local passed failed warnings skipped
        passed=$(grep -c '\[PASS\]' "$log_file" 2>/dev/null || echo "0")
        failed=$(grep -c '\[FAIL\]' "$log_file" 2>/dev/null || echo "0")
        warnings=$(grep -c '\[WARN\]' "$log_file" 2>/dev/null || echo "0")
        skipped=$(grep -c '\[SKIP\]' "$log_file" 2>/dev/null || echo "0")
        
        cat >> "$report_file" << EOF
| Result | Count |
|--------|-------|
| ✅ Passed | ${passed} |
| ❌ Failed | ${failed} |
| ⚠️ Warnings | ${warnings} |
| ⏭️ Skipped | ${skipped} |

## Overall Status

EOF
        
        if [[ "$failed" -gt 0 ]]; then
            echo "**❌ VALIDATION FAILED** - ${failed} check(s) failed" >> "$report_file"
        elif [[ "$warnings" -gt 0 ]]; then
            echo "**⚠️ VALIDATION PASSED WITH WARNINGS** - ${warnings} warning(s)" >> "$report_file"
        else
            echo "**✅ VALIDATION PASSED** - All checks successful" >> "$report_file"
        fi
        
        # Add failures section if any
        if [[ "$failed" -gt 0 ]]; then
            echo "" >> "$report_file"
            echo "## Failures" >> "$report_file"
            echo "" >> "$report_file"
            echo '```' >> "$report_file"
            grep '\[FAIL\]' "$log_file" >> "$report_file" 2>/dev/null || true
            echo '```' >> "$report_file"
        fi
        
        # Add warnings section if any
        if [[ "$warnings" -gt 0 ]]; then
            echo "" >> "$report_file"
            echo "## Warnings" >> "$report_file"
            echo "" >> "$report_file"
            echo '```' >> "$report_file"
            grep '\[WARN\]' "$log_file" >> "$report_file" 2>/dev/null || true
            echo '```' >> "$report_file"
        fi
    fi
    
    echo "" >> "$report_file"
    echo "---" >> "$report_file"
    echo "*Report generated by pulldb-validate*" >> "$report_file"
    
    check_pass "Report generated: ${report_file}"
    echo "$report_file"
}

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

run_teardown() {
    phase_header "5" "Teardown & Report"
    
    kill_background_processes
    drop_test_databases
    
    # Only remove install dir if it's an isolated test install
    if [[ "${VALIDATE_ISOLATED:-false}" == "true" ]]; then
        remove_install_directory
    fi
    
    local report_file
    report_file=$(generate_summary_report)
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  VALIDATION COMPLETE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    if [[ -f "$report_file" ]]; then
        echo "  📋 Report: ${report_file}"
    fi
    
    if [[ -f "${VALIDATE_LOG_FILE:-}" ]]; then
        echo "  📝 Log: ${VALIDATE_LOG_FILE}"
    fi
    
    echo ""
    
    return 0
}

# Allow sourcing or direct execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    VALIDATE_LOG_FILE="${VALIDATE_LOG_FILE:-/tmp/pulldb-validate.log}"
    touch "$VALIDATE_LOG_FILE"
    run_teardown
fi
