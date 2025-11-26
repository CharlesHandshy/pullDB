#!/usr/bin/env bash
# ==============================================================================
# pulldb-validate - Comprehensive Validation Framework
# ==============================================================================
#
# A complete validation framework for pullDB that tests everything from
# prerequisites through installation, unit tests, integration tests, and
# optional end-to-end restore testing.
#
# Usage:
#   ./pulldb-validate.sh [--quick|--full|--e2e] [--dry-run] [--no-teardown]
#
# Test Levels:
#   --quick     Prerequisites + Unit tests (default)
#   --full      Prerequisites + Unit + Integration tests
#   --e2e       Prerequisites + Unit + Integration + E2E restore test
#
# Options:
#   --dry-run      Show what would be done without executing
#   --no-teardown  Skip cleanup phase (keep test artifacts)
#   --isolated     Use isolated install directory (/tmp/pulldb-validate-*)
#   --help         Show this help message
#
# Environment Variables:
#   PULLDB_AWS_PROFILE       AWS profile for Secrets Manager (default: pr-dev)
#   PULLDB_S3_AWS_PROFILE    AWS profile for S3 (default: pr-staging)
#   PULLDB_S3_BUCKET_PATH    S3 bucket/prefix (default: pestroutesrdsdbs/daily/stg/)
#   PULLDB_TEST_MYSQL_HOST   MySQL host (default: localhost)
#   PULLDB_TEST_MYSQL_USER   MySQL user (default: pulldb_test)
#   PULLDB_TEST_MYSQL_PASSWORD  MySQL password (default: test123)
#   PULLDB_E2E_CUSTOMER      Customer for E2E test (default: qatemplate)
#   PULLDB_E2E_TARGET        Target database for E2E (default: pulldb_e2e_test)
#
# ==============================================================================

set -euo pipefail

# Script location and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Validation scripts directory
VALIDATE_DIR="${SCRIPT_DIR}/validate"

# Export for child scripts
export PROJECT_ROOT
export SCRIPT_DIR

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------

# Validation level
VALIDATE_QUICK=true
VALIDATE_FULL=false
VALIDATE_E2E=false
export VALIDATE_E2E

# Options
VALIDATE_DRY_RUN=false
VALIDATE_TEARDOWN=true
VALIDATE_ISOLATED=false
export VALIDATE_DRY_RUN
export VALIDATE_ISOLATED

# Paths
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
VALIDATE_PREFIX="/tmp/pulldb-validate-${TIMESTAMP}"
VALIDATE_LOG_FILE="${VALIDATE_PREFIX}/validate.log"
export VALIDATE_PREFIX
export VALIDATE_LOG_FILE

# ------------------------------------------------------------------------------
# Colors and Output
# ------------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }

banner() {
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  pullDB Validation Framework${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# ------------------------------------------------------------------------------
# Help
# ------------------------------------------------------------------------------

show_help() {
    cat << 'EOF'
pulldb-validate - Comprehensive Validation Framework

Usage:
  ./pulldb-validate.sh [OPTIONS]

Test Levels:
  --quick       Prerequisites + Unit tests (default)
  --full        Prerequisites + Unit + Integration tests  
  --e2e         Prerequisites + Unit + Integration + E2E restore test

Options:
  --dry-run     Show what would be done without executing
  --no-teardown Skip cleanup phase (keep test artifacts)
  --isolated    Use isolated install directory (/tmp/pulldb-validate-*)
  --help        Show this help message

Phases:
  Phase 0: Prerequisites    System requirements check (Python, MySQL, AWS, disk)
  Phase 1: Installation     Non-root installation simulation (when --isolated)
  Phase 2: Unit Tests       pytest execution against pulldb/tests/
  Phase 3: Integration      AWS Secrets, S3 discovery, CLI tests (--full, --e2e)
  Phase 4: E2E Restore      Full restore using staging backup (--e2e only)
  Phase 5: Teardown         Cleanup and report generation

Examples:
  ./pulldb-validate.sh                  # Quick validation
  ./pulldb-validate.sh --full           # Full validation with integration tests
  ./pulldb-validate.sh --e2e            # Complete E2E validation with restore test
  ./pulldb-validate.sh --dry-run        # Preview what would be done
  ./pulldb-validate.sh --full --isolated # Full test with isolated install
EOF
}

# ------------------------------------------------------------------------------
# Argument Parsing
# ------------------------------------------------------------------------------

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --quick)
                VALIDATE_QUICK=true
                VALIDATE_FULL=false
                VALIDATE_E2E=false
                shift
                ;;
            --full)
                VALIDATE_QUICK=false
                VALIDATE_FULL=true
                VALIDATE_E2E=false
                export VALIDATE_FULL
                shift
                ;;
            --e2e)
                VALIDATE_QUICK=false
                VALIDATE_FULL=true
                VALIDATE_E2E=true
                export VALIDATE_FULL
                export VALIDATE_E2E
                shift
                ;;
            --dry-run)
                VALIDATE_DRY_RUN=true
                export VALIDATE_DRY_RUN
                shift
                ;;
            --no-teardown)
                VALIDATE_TEARDOWN=false
                shift
                ;;
            --isolated)
                VALIDATE_ISOLATED=true
                export VALIDATE_ISOLATED
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# ------------------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------------------

setup_validation() {
    # Create validation directory and log file
    mkdir -p "$VALIDATE_PREFIX"
    touch "$VALIDATE_LOG_FILE"
    
    # Log start
    {
        echo "================================================================================"
        echo "pullDB Validation Started: $(date -Iseconds)"
        echo "Level: $(if $VALIDATE_E2E; then echo "E2E"; elif $VALIDATE_FULL; then echo "Full"; else echo "Quick"; fi)"
        echo "Dry Run: $VALIDATE_DRY_RUN"
        echo "Isolated: $VALIDATE_ISOLATED"
        echo "Log: $VALIDATE_LOG_FILE"
        echo "================================================================================"
        echo ""
    } >> "$VALIDATE_LOG_FILE"
}

# ------------------------------------------------------------------------------
# Phase Runners
# ------------------------------------------------------------------------------

run_phase() {
    local phase_script="$1"
    local phase_name="$2"
    local phase_func="$3"
    
    if [[ ! -f "$phase_script" ]]; then
        log_error "Phase script not found: ${phase_script}"
        return 1
    fi
    
    # Source the phase script
    source "$phase_script"
    
    # Run the phase function
    if ! "$phase_func"; then
        log_error "Phase failed: ${phase_name}"
        return 1
    fi
    
    return 0
}

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

main() {
    parse_args "$@"
    
    banner
    
    # Display configuration
    local level="Quick"
    $VALIDATE_FULL && level="Full"
    $VALIDATE_E2E && level="E2E"
    
    echo "  Configuration:"
    echo "    Level:      $level"
    echo "    Dry Run:    $VALIDATE_DRY_RUN"
    echo "    Isolated:   $VALIDATE_ISOLATED"
    echo "    Log:        $VALIDATE_LOG_FILE"
    echo ""
    
    setup_validation
    
    local exit_code=0
    
    # Source common library
    source "${SCRIPT_DIR}/lib/validate-common.sh"
    
    # Phase 0: Prerequisites (always)
    if ! run_phase "${VALIDATE_DIR}/00-prerequisites.sh" "Prerequisites" "run_prerequisites"; then
        exit_code=1
    fi
    
    # Phase 1: Installation (only if isolated)
    if [[ "$VALIDATE_ISOLATED" == true ]]; then
        if ! run_phase "${VALIDATE_DIR}/10-install.sh" "Installation" "run_install"; then
            exit_code=1
        fi
    else
        log_info "Skipping isolated installation (using existing environment)"
    fi
    
    # Phase 2: Unit Tests (always)
    if ! run_phase "${VALIDATE_DIR}/20-unit-tests.sh" "Unit Tests" "run_unit_tests"; then
        exit_code=1
    fi
    
    # Phase 3: Integration Tests (full and e2e)
    if [[ "$VALIDATE_FULL" == true ]] || [[ "$VALIDATE_E2E" == true ]]; then
        if ! run_phase "${VALIDATE_DIR}/30-integration.sh" "Integration Tests" "run_integration_tests"; then
            exit_code=1
        fi
    else
        log_info "Skipping integration tests (use --full or --e2e)"
    fi
    
    # Phase 4: E2E Restore (e2e only)
    if [[ "$VALIDATE_E2E" == true ]]; then
        if ! run_phase "${VALIDATE_DIR}/40-e2e-restore.sh" "E2E Restore" "run_e2e_restore"; then
            exit_code=1
        fi
    else
        log_info "Skipping E2E restore test (use --e2e)"
    fi
    
    # Phase 5: Teardown (unless --no-teardown)
    if [[ "$VALIDATE_TEARDOWN" == true ]]; then
        run_phase "${VALIDATE_DIR}/99-teardown.sh" "Teardown" "run_teardown" || true
    else
        log_warn "Skipping teardown (--no-teardown specified)"
        log_info "Artifacts in: ${VALIDATE_PREFIX}"
    fi
    
    # Final status
    echo ""
    if [[ "$exit_code" -eq 0 ]]; then
        echo -e "${GREEN}${BOLD}✅ VALIDATION PASSED${NC}"
    else
        echo -e "${RED}${BOLD}❌ VALIDATION FAILED${NC}"
    fi
    echo ""
    
    exit "$exit_code"
}

# Run if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
