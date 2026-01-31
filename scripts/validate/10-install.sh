#!/usr/bin/env bash
# ==============================================================================
# Phase 1: Installation Simulation
# ==============================================================================
# Creates an isolated installation to validate the deployment process
#
# Actions:
#   - Create isolated prefix in /tmp
#   - Set up virtual environment
#   - Install pulldb package
#   - Verify binaries and configuration

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source common library
source "${SCRIPT_DIR}/../lib/validate-common.sh"

# ------------------------------------------------------------------------------
# Installation Functions
# ------------------------------------------------------------------------------

setup_venv() {
    local venv_path="${VALIDATE_PREFIX}/venv"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would create venv at ${venv_path}"
        return 0
    fi
    
    # Create virtual environment
    python3 -m venv "$venv_path" >> "$VALIDATE_LOG_FILE" 2>&1
    
    # Upgrade pip
    "$venv_path/bin/pip" install --upgrade pip wheel >> "$VALIDATE_LOG_FILE" 2>&1
    
    check_pass "Virtual environment created"
    return 0
}

install_pulldb() {
    local venv_path="${VALIDATE_PREFIX}/venv"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would install pulldb from ${PROJECT_ROOT}"
        return 0
    fi
    
    # Install pulldb in editable mode
    if "$venv_path/bin/pip" install -e "$PROJECT_ROOT" >> "$VALIDATE_LOG_FILE" 2>&1; then
        local version
        version=$("$venv_path/bin/python" -c "import pulldb; print(pulldb.__version__)" 2>/dev/null || echo "unknown")
        check_pass "pulldb package installed (version: ${version})"
        return 0
    else
        check_fail "Failed to install pulldb package"
        return 1
    fi
}

install_test_deps() {
    local venv_path="${VALIDATE_PREFIX}/venv"
    local requirements_test="${PROJECT_ROOT}/requirements-test.txt"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would install test dependencies"
        return 0
    fi
    
    if [[ -f "$requirements_test" ]]; then
        if "$venv_path/bin/pip" install -r "$requirements_test" >> "$VALIDATE_LOG_FILE" 2>&1; then
            check_pass "Test dependencies installed"
            return 0
        else
            check_warn "Some test dependencies failed to install"
            return 0
        fi
    else
        # Install minimal test deps
        "$venv_path/bin/pip" install pytest pytest-timeout pytest-mock >> "$VALIDATE_LOG_FILE" 2>&1
        check_pass "Minimal test dependencies installed"
    fi
    
    return 0
}

create_env_file() {
    local env_file="${VALIDATE_PREFIX}/.env"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would create .env at ${env_file}"
        return 0
    fi
    
    # Copy project .env if exists, otherwise create minimal
    if [[ -f "${PROJECT_ROOT}/.env" ]]; then
        cp "${PROJECT_ROOT}/.env" "$env_file"
        check_pass ".env copied from project"
    else
        cat > "$env_file" << 'EOF'
# Minimal validation environment
PULLDB_AWS_PROFILE=pr-dev
PULLDB_S3_AWS_PROFILE=pr-staging
EOF
        check_pass ".env created with defaults"
    fi
    
    return 0
}

verify_binaries() {
    local venv_path="${VALIDATE_PREFIX}/venv"
    local bin_dir="${PROJECT_ROOT}/pulldb/binaries"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would verify binaries"
        return 0
    fi
    
    # Check pulldb CLI
    if "$venv_path/bin/pulldb" --help >> "$VALIDATE_LOG_FILE" 2>&1; then
        check_pass "pulldb CLI accessible"
    else
        check_fail "pulldb CLI not working"
        return 1
    fi
    
    # Check myloader binary exists
    local myloader_bin="${bin_dir}/myloader-0.21.1-1"
    if [[ -x "$myloader_bin" ]]; then
        check_pass "myloader binary found: myloader-0.21.1-1"
    elif [[ -f "$myloader_bin" ]]; then
        check_warn "myloader binary exists but not executable"
    else
        check_warn "myloader binary not found in package (will use system myloader)"
    fi
    
    return 0
}

verify_imports() {
    local venv_path="${VALIDATE_PREFIX}/venv"
    
    if [[ "$VALIDATE_DRY_RUN" == true ]]; then
        check_info "[DRY-RUN] Would verify Python imports"
        return 0
    fi
    
    local imports_ok
    imports_ok=$("$venv_path/bin/python" -c "
from pulldb.cli import main
from pulldb.infra import mysql, s3, secrets
from pulldb.domain import config, models
from pulldb.worker import service, restore
print('OK')
" 2>&1)
    
    if [[ "$imports_ok" == "OK" ]]; then
        check_pass "All Python imports successful"
        return 0
    else
        check_fail "Python import errors: ${imports_ok}"
        return 1
    fi
}

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

run_installation() {
    phase_header "1" "Installation"
    
    local failed=0
    
    # Create validation prefix if not already created
    if [[ -z "$VALIDATE_PREFIX" ]]; then
        create_validate_prefix
    fi
    
    setup_venv || ((failed++))
    install_pulldb || ((failed++))
    install_test_deps
    create_env_file
    verify_binaries || ((failed++))
    verify_imports || ((failed++))
    
    return "$failed"
}

# Allow sourcing or direct execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # Create prefix for standalone execution
    create_validate_prefix
    run_installation
fi
