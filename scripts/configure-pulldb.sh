#!/bin/bash
# configure-pulldb.sh - Interactive configuration for pullDB
#
# This script provides a menu-driven interface to configure pullDB settings.
# It can be run during install (called from postinst) or manually afterward.
#
# Usage: configure-pulldb.sh [--non-interactive]
#   --non-interactive: Skip the menu, just validate and apply current config

set -e

INSTALL_PREFIX="${PULLDB_INSTALL_PREFIX:-/opt/pulldb.service}"
ENV_FILE="${INSTALL_PREFIX}/.env"
SYSTEM_USER="${PULLDB_SYSTEM_USER:-pulldb_service}"
SYSTEM_GROUP="${PULLDB_SYSTEM_GROUP:-pulldb_service}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

#------------------------------------------------------------------------------
# Utility Functions
#------------------------------------------------------------------------------

print_header() {
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
}

print_ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

print_warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "  ${RED}✗${NC} $1"
}

print_info() {
    echo -e "  ${BLUE}ℹ${NC} $1"
}

# Load current .env values into shell variables
load_env() {
    if [ -f "$ENV_FILE" ]; then
        # Export all PULLDB_* variables
        set -a
        # shellcheck disable=SC1090
        source "$ENV_FILE" 2>/dev/null || true
        set +a
        return 0
    fi
    return 1
}

# Get a variable value with default
get_var() {
    local var_name="$1"
    local default="$2"
    eval "echo \${${var_name}:-$default}"
}

# Update a variable in .env file
set_var() {
    local var_name="$1"
    local new_value="$2"
    
    if grep -q "^${var_name}=" "$ENV_FILE" 2>/dev/null; then
        # Variable exists (uncommented) - update it
        sed -i "s|^${var_name}=.*|${var_name}=${new_value}|" "$ENV_FILE"
    elif grep -q "^#\s*${var_name}=" "$ENV_FILE" 2>/dev/null; then
        # Variable exists but commented - uncomment and update
        sed -i "s|^#\s*${var_name}=.*|${var_name}=${new_value}|" "$ENV_FILE"
    else
        # Variable doesn't exist - append it
        echo "${var_name}=${new_value}" >> "$ENV_FILE"
    fi
}

#------------------------------------------------------------------------------
# Configuration Menu Functions
#------------------------------------------------------------------------------

show_current_config() {
    print_header "Current Configuration"
    
    echo ""
    echo "  Database:"
    echo "    Host:     $(get_var PULLDB_MYSQL_HOST 'not set')"
    echo "    Port:     $(get_var PULLDB_MYSQL_PORT '3306')"
    echo "    User:     $(get_var PULLDB_MYSQL_USER 'not set')"
    echo "    Database: $(get_var PULLDB_MYSQL_DATABASE 'pulldb')"
    
    echo ""
    echo "  AWS:"
    echo "    Profile:    $(get_var PULLDB_AWS_PROFILE 'not set')"
    echo "    S3 Profile: $(get_var PULLDB_S3_AWS_PROFILE 'not set')"
    
    echo ""
    echo "  Paths:"
    echo "    Work Dir:  $(get_var PULLDB_WORK_DIR '/mnt/data/work/pulldb.service')"
    echo "    Log Dir:   $(get_var PULLDB_LOG_DIR '/mnt/data/logs/pulldb.service')"
    echo "    Temp Dir:  $(get_var PULLDB_TMP_DIR '/mnt/data/tmp')"
    
    echo ""
    echo "  After-SQL:"
    echo "    Customer:  $(get_var PULLDB_CUSTOMERS_AFTER_SQL_DIR "${INSTALL_PREFIX}/after_sql/customer")"
    echo "    QA:        $(get_var PULLDB_QA_TEMPLATE_AFTER_SQL_DIR "${INSTALL_PREFIX}/after_sql/quality")"
    
    echo ""
    echo "  Logging:"
    echo "    Level:     $(get_var PULLDB_LOG_LEVEL 'INFO')"
    echo ""
}

configure_database() {
    print_header "Database Configuration"
    
    local current_host=$(get_var PULLDB_MYSQL_HOST 'localhost')
    local current_port=$(get_var PULLDB_MYSQL_PORT '3306')
    local current_user=$(get_var PULLDB_MYSQL_USER 'pulldb')
    local current_db=$(get_var PULLDB_MYSQL_DATABASE 'pulldb')
    
    echo ""
    read -p "  MySQL Host [$current_host]: " new_host
    [ -n "$new_host" ] && set_var PULLDB_MYSQL_HOST "$new_host"
    
    read -p "  MySQL Port [$current_port]: " new_port
    [ -n "$new_port" ] && set_var PULLDB_MYSQL_PORT "$new_port"
    
    read -p "  MySQL User [$current_user]: " new_user
    [ -n "$new_user" ] && set_var PULLDB_MYSQL_USER "$new_user"
    
    read -p "  MySQL Database [$current_db]: " new_db
    [ -n "$new_db" ] && set_var PULLDB_MYSQL_DATABASE "$new_db"
    
    echo ""
    echo "  Note: For password, use AWS Secrets Manager reference:"
    echo "        PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/..."
    echo ""
    
    print_ok "Database settings updated"
}

configure_aws() {
    print_header "AWS Configuration"
    
    local current_profile=$(get_var PULLDB_AWS_PROFILE 'default')
    local current_s3_profile=$(get_var PULLDB_S3_AWS_PROFILE "$current_profile")
    
    echo ""
    echo "  AWS profiles are configured in ~/.aws/config"
    echo "  See ${INSTALL_PREFIX}/AWS-SETUP.md for setup instructions"
    echo ""
    
    read -p "  AWS Profile (for Secrets Manager) [$current_profile]: " new_profile
    [ -n "$new_profile" ] && set_var PULLDB_AWS_PROFILE "$new_profile"
    
    read -p "  S3 AWS Profile (for backups) [$current_s3_profile]: " new_s3_profile
    [ -n "$new_s3_profile" ] && set_var PULLDB_S3_AWS_PROFILE "$new_s3_profile"
    
    print_ok "AWS settings updated"
}

configure_paths() {
    print_header "Path Configuration"
    
    local current_work=$(get_var PULLDB_WORK_DIR '/mnt/data/work/pulldb.service')
    local current_log=$(get_var PULLDB_LOG_DIR '/mnt/data/logs/pulldb.service')
    local current_tmp=$(get_var PULLDB_TMP_DIR '/mnt/data/tmp')
    
    echo ""
    echo "  These directories should be on a volume with sufficient space"
    echo "  for downloading and extracting database backups."
    echo ""
    
    read -p "  Work Directory [$current_work]: " new_work
    [ -n "$new_work" ] && set_var PULLDB_WORK_DIR "$new_work"
    
    read -p "  Log Directory [$current_log]: " new_log
    [ -n "$new_log" ] && set_var PULLDB_LOG_DIR "$new_log"
    
    read -p "  Temp Directory [$current_tmp]: " new_tmp
    [ -n "$new_tmp" ] && set_var PULLDB_TMP_DIR "$new_tmp"
    
    print_ok "Path settings updated"
}

configure_logging() {
    print_header "Logging Configuration"
    
    local current_level=$(get_var PULLDB_LOG_LEVEL 'INFO')
    
    echo ""
    echo "  Log Levels: DEBUG, INFO, WARNING, ERROR, CRITICAL"
    echo ""
    
    read -p "  Log Level [$current_level]: " new_level
    if [ -n "$new_level" ]; then
        # Validate
        case "$new_level" in
            DEBUG|INFO|WARNING|ERROR|CRITICAL)
                set_var PULLDB_LOG_LEVEL "$new_level"
                print_ok "Log level set to $new_level"
                ;;
            *)
                print_error "Invalid log level. Keeping $current_level"
                ;;
        esac
    fi
}

#------------------------------------------------------------------------------
# Path/Permission Validation
#------------------------------------------------------------------------------

ensure_directory() {
    local dir="$1"
    local owner="$2"
    local group="$3"
    local mode="$4"
    
    if [ ! -d "$dir" ]; then
        if mkdir -p "$dir" 2>/dev/null; then
            print_ok "Created $dir"
        else
            print_error "Failed to create $dir"
            return 1
        fi
    fi
    
    if chown "$owner:$group" "$dir" 2>/dev/null; then
        chmod "$mode" "$dir" 2>/dev/null
        print_ok "Set permissions on $dir"
    else
        print_warn "Could not set ownership on $dir (run as root)"
    fi
}

validate_and_create_paths() {
    print_header "Validating Paths and Permissions"
    
    # Reload env to get latest values
    load_env
    
    local work_dir=$(get_var PULLDB_WORK_DIR '/mnt/data/work/pulldb.service')
    local log_dir=$(get_var PULLDB_LOG_DIR '/mnt/data/logs/pulldb.service')
    local tmp_dir=$(get_var PULLDB_TMP_DIR '/mnt/data/tmp')
    local customer_sql=$(get_var PULLDB_CUSTOMERS_AFTER_SQL_DIR "${INSTALL_PREFIX}/after_sql/customer")
    local qa_sql=$(get_var PULLDB_QA_TEMPLATE_AFTER_SQL_DIR "${INSTALL_PREFIX}/after_sql/quality")
    
    echo ""
    
    # Work directory (needs to be writable by service)
    ensure_directory "$work_dir" "$SYSTEM_USER" "$SYSTEM_GROUP" "0750"
    
    # Log directory
    ensure_directory "$log_dir" "$SYSTEM_USER" "$SYSTEM_GROUP" "0750"
    
    # Temp directory (world-writable with sticky bit)
    if [ ! -d "$tmp_dir" ]; then
        mkdir -p "$tmp_dir" 2>/dev/null && chmod 1777 "$tmp_dir" && print_ok "Created $tmp_dir"
    else
        print_ok "Exists: $tmp_dir"
    fi
    
    # After-SQL directories
    ensure_directory "$customer_sql" "$SYSTEM_USER" "$SYSTEM_GROUP" "0750"
    ensure_directory "$qa_sql" "$SYSTEM_USER" "$SYSTEM_GROUP" "0750"
    
    # Copy template SQL files if directory is empty
    local template_customer="${INSTALL_PREFIX}/template_after_sql/customer"
    local template_qa="${INSTALL_PREFIX}/template_after_sql/quality"
    
    if [ -d "$template_customer" ] && [ -z "$(ls -A "$customer_sql" 2>/dev/null)" ]; then
        cp -r "$template_customer"/* "$customer_sql"/ 2>/dev/null || true
        chown -R "$SYSTEM_USER:$SYSTEM_GROUP" "$customer_sql" 2>/dev/null || true
        print_ok "Installed customer after-SQL scripts"
    fi
    
    if [ -d "$template_qa" ] && [ -z "$(ls -A "$qa_sql" 2>/dev/null)" ]; then
        cp -r "$template_qa"/* "$qa_sql"/ 2>/dev/null || true
        chown -R "$SYSTEM_USER:$SYSTEM_GROUP" "$qa_sql" 2>/dev/null || true
        print_ok "Installed QA after-SQL scripts"
    fi
    
    # Validate .env permissions
    if [ -f "$ENV_FILE" ]; then
        chown "$SYSTEM_USER:$SYSTEM_GROUP" "$ENV_FILE" 2>/dev/null || true
        chmod 600 "$ENV_FILE" 2>/dev/null || true
        print_ok "Set secure permissions on .env"
    fi
    
    echo ""
}

#------------------------------------------------------------------------------
# Main Menu
#------------------------------------------------------------------------------

show_menu() {
    print_header "pullDB Configuration"
    
    echo ""
    echo "  1) View current configuration"
    echo "  2) Configure database settings"
    echo "  3) Configure AWS settings"
    echo "  4) Configure paths"
    echo "  5) Configure logging"
    echo ""
    echo "  v) Validate and create paths"
    echo "  s) Save and exit"
    echo "  q) Quit without additional changes"
    echo ""
}

run_interactive() {
    # Load current config
    if ! load_env; then
        print_error "No .env file found at $ENV_FILE"
        print_info "Run the package installer first: sudo dpkg -i pulldb_*.deb"
        exit 1
    fi
    
    while true; do
        show_menu
        read -p "  Select option: " choice
        
        case "$choice" in
            1) show_current_config ;;
            2) configure_database ;;
            3) configure_aws ;;
            4) configure_paths ;;
            5) configure_logging ;;
            v|V) validate_and_create_paths ;;
            s|S)
                validate_and_create_paths
                print_header "Configuration Saved"
                echo ""
                print_ok "Configuration saved to $ENV_FILE"
                print_info "Restart services to apply: sudo systemctl restart pulldb-api pulldb-worker"
                echo ""
                exit 0
                ;;
            q|Q)
                echo ""
                print_info "Exiting without additional changes"
                echo ""
                exit 0
                ;;
            *)
                print_error "Invalid option"
                ;;
        esac
    done
}

run_non_interactive() {
    echo "Running non-interactive configuration..."
    
    if load_env; then
        print_ok "Loaded configuration from $ENV_FILE"
    else
        print_warn "No .env file found, using defaults"
    fi
    
    validate_and_create_paths
    
    print_ok "Configuration validated"
}

#------------------------------------------------------------------------------
# Entry Point
#------------------------------------------------------------------------------

# Check if we're being called with --non-interactive
if [ "$1" = "--non-interactive" ]; then
    run_non_interactive
else
    # Check if stdin is a terminal
    if [ -t 0 ]; then
        run_interactive
    else
        echo "Non-interactive environment detected, skipping configuration menu"
        run_non_interactive
    fi
fi
