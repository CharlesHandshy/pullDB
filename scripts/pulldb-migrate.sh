#!/usr/bin/env bash
# pulldb-migrate.sh - Database migration wrapper for pullDB
#
# Wraps dbmate with pullDB-specific configuration:
# - Loads connection string from AWS Secrets Manager
# - Provides validation and confirmation prompts
# - Supports non-interactive mode for automation
#
# Usage:
#   pulldb-migrate status              # Show pending migrations
#   pulldb-migrate up                  # Apply all pending migrations
#   pulldb-migrate up --yes            # Non-interactive mode
#   pulldb-migrate rollback            # Rollback last migration
#   pulldb-migrate verify              # Verify schema is correct
#   pulldb-migrate new <name>          # Create new migration file

set -euo pipefail

# === Configuration ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PREFIX="${PULLDB_INSTALL_PREFIX:-/opt/pulldb.service}"
MIGRATIONS_DIR="${PULLDB_MIGRATIONS_DIR:-${INSTALL_PREFIX}/migrations}"
DBMATE_BIN="${PULLDB_DBMATE_BIN:-${INSTALL_PREFIX}/bin/dbmate}"

# For development, check local paths
if [[ ! -f "$DBMATE_BIN" ]] && [[ -f "${SCRIPT_DIR}/../bin/dbmate" ]]; then
    DBMATE_BIN="${SCRIPT_DIR}/../bin/dbmate"
fi
if [[ ! -d "$MIGRATIONS_DIR" ]] && [[ -d "${SCRIPT_DIR}/../migrations" ]]; then
    MIGRATIONS_DIR="${SCRIPT_DIR}/../migrations"
fi

ASSUME_YES=0
VERBOSE=0

# === Helpers ===
info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*" >&2; }
error() { echo "[ERROR] $*" >&2; }
fail() { error "$*"; exit 1; }

debug() {
    if [[ $VERBOSE -eq 1 ]]; then
        echo "[DEBUG] $*" >&2
    fi
}

confirm() {
    local question="$1"
    if [[ $ASSUME_YES -eq 1 ]]; then
        info "Auto-confirm: $question"
        return 0
    fi
    read -r -p "${question} [y/N]: " reply || true
    if [[ "$reply" =~ ^[Yy]$ ]]; then
        return 0
    fi
    return 1
}

# === Database URL Construction ===
# Builds DATABASE_URL from AWS Secrets Manager or environment
build_database_url() {
    # Check if DATABASE_URL is already set (for testing/override)
    if [[ -n "${DATABASE_URL:-}" ]]; then
        debug "Using existing DATABASE_URL"
        return 0
    fi
    
    # Load from AWS Secrets Manager
    local secret_ref="${PULLDB_COORDINATION_SECRET:-aws-secretsmanager:/pulldb/mysql/coordination-db}"
    local aws_profile="${PULLDB_AWS_PROFILE:-}"
    
    debug "Loading credentials from: $secret_ref"
    
    # Extract secret name from reference
    local secret_name
    if [[ "$secret_ref" == aws-secretsmanager:* ]]; then
        secret_name="${secret_ref#aws-secretsmanager:}"
    else
        fail "Unsupported secret reference format: $secret_ref (expected aws-secretsmanager:/path)"
    fi
    
    # Build AWS CLI command
    local aws_cmd="aws secretsmanager get-secret-value --secret-id ${secret_name} --query SecretString --output text"
    if [[ -n "$aws_profile" ]]; then
        aws_cmd="aws --profile ${aws_profile} secretsmanager get-secret-value --secret-id ${secret_name} --query SecretString --output text"
    fi
    
    # Fetch secret
    local secret_json
    if ! secret_json=$(eval "$aws_cmd" 2>/dev/null); then
        fail "Failed to fetch secret from AWS Secrets Manager: $secret_name"
    fi
    
    # Parse JSON (requires jq)
    if ! command -v jq &>/dev/null; then
        fail "jq is required for parsing secrets. Install with: apt-get install jq"
    fi
    
    local host port password database
    host=$(echo "$secret_json" | jq -r '.host // "localhost"')
    port=$(echo "$secret_json" | jq -r '.port // 3306')
    password=$(echo "$secret_json" | jq -r '.password // empty')
    database="${PULLDB_MYSQL_DATABASE:-pulldb_service}"
    
    # Use environment variable for user (supports API/Worker separation)
    local user="${PULLDB_MIGRATION_MYSQL_USER:-${PULLDB_MYSQL_USER:-root}}"
    
    if [[ -z "$password" ]]; then
        fail "No password found in secret: $secret_name"
    fi
    
    # URL-encode password (handles special characters)
    local encoded_password
    encoded_password=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$password', safe=''))")
    
    # Build MySQL URL for dbmate
    export DATABASE_URL="mysql://${user}:${encoded_password}@${host}:${port}/${database}"
    debug "DATABASE_URL constructed for host: $host"
}

# === Check Prerequisites ===
check_prerequisites() {
    if [[ ! -f "$DBMATE_BIN" ]]; then
        fail "dbmate binary not found at: $DBMATE_BIN\nRun: sudo scripts/install-dbmate.sh"
    fi
    
    if [[ ! -d "$MIGRATIONS_DIR" ]]; then
        fail "Migrations directory not found: $MIGRATIONS_DIR"
    fi
    
    if ! command -v jq &>/dev/null; then
        fail "jq is required. Install with: apt-get install jq"
    fi
}

# === Run dbmate with configuration ===
run_dbmate() {
    local cmd="$1"
    shift
    
    build_database_url
    
    "$DBMATE_BIN" \
        --migrations-dir "$MIGRATIONS_DIR" \
        --migrations-table "schema_migrations" \
        --no-dump-schema \
        "$cmd" "$@"
}

# === Commands ===
cmd_status() {
    info "Checking migration status..."
    run_dbmate status
}

cmd_up() {
    info "Checking for pending migrations..."
    
    # Get pending count
    local pending_output
    pending_output=$(run_dbmate status 2>&1) || true
    
    if echo "$pending_output" | grep -q "Applied"; then
        echo "$pending_output"
    fi
    
    local pending_count
    pending_count=$(echo "$pending_output" | grep -c "Pending" || echo "0")
    
    if [[ "$pending_count" == "0" ]]; then
        info "No pending migrations. Database is up to date."
        return 0
    fi
    
    info "Found $pending_count pending migration(s)"
    echo "$pending_output" | grep "Pending" || true
    echo
    
    if ! confirm "Apply $pending_count migration(s)?"; then
        info "Migration cancelled by user"
        return 1
    fi
    
    info "Applying migrations..."
    run_dbmate up
    
    info "Migrations applied successfully"
    cmd_verify
}

cmd_rollback() {
    warn "Rolling back the last migration..."
    
    if ! confirm "This will undo the last migration. Continue?"; then
        info "Rollback cancelled"
        return 1
    fi
    
    run_dbmate rollback
    info "Rollback complete"
}

cmd_new() {
    local name="${1:-}"
    if [[ -z "$name" ]]; then
        fail "Usage: pulldb-migrate new <migration_name>"
    fi
    
    # Sanitize name (lowercase, underscores)
    name=$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr ' -' '_' | tr -cd 'a-z0-9_')
    
    info "Creating new migration: $name"
    run_dbmate new "$name"
}

cmd_verify() {
    info "Verifying schema..."
    
    build_database_url
    
    # Extract connection params from DATABASE_URL for mysql client
    local db_url="$DATABASE_URL"
    local user host port database password
    
    # Parse URL (mysql://user:pass@host:port/database)
    user=$(echo "$db_url" | sed -E 's|mysql://([^:]+):.*|\1|')
    password=$(echo "$db_url" | sed -E 's|mysql://[^:]+:([^@]+)@.*|\1|' | python3 -c "import urllib.parse,sys; print(urllib.parse.unquote(sys.stdin.read().strip()))")
    host=$(echo "$db_url" | sed -E 's|mysql://[^@]+@([^:]+):.*|\1|')
    port=$(echo "$db_url" | sed -E 's|mysql://[^@]+@[^:]+:([0-9]+)/.*|\1|')
    database=$(echo "$db_url" | sed -E 's|mysql://[^/]+/([^?]+).*|\1|')
    
    local mysql_cmd="mysql -u${user} -p${password} -h${host} -P${port} ${database} -N -e"
    
    # Verify essential tables exist
    local tables=("auth_users" "jobs" "job_events" "db_hosts" "settings" "locks" "schema_migrations")
    local missing=()
    
    for table in "${tables[@]}"; do
        if ! $mysql_cmd "SELECT 1 FROM information_schema.tables WHERE table_schema='${database}' AND table_name='${table}'" 2>/dev/null | grep -q 1; then
            missing+=("$table")
        fi
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        error "Missing tables: ${missing[*]}"
        return 1
    fi
    
    # Verify Phase 2 settings exist
    local phase2_settings=("max_active_jobs_per_user" "max_active_jobs_global")
    local missing_settings=()
    
    for setting in "${phase2_settings[@]}"; do
        if ! $mysql_cmd "SELECT 1 FROM settings WHERE setting_key='${setting}'" 2>/dev/null | grep -q 1; then
            missing_settings+=("$setting")
        fi
    done
    
    if [[ ${#missing_settings[@]} -gt 0 ]]; then
        warn "Missing settings (may need migration): ${missing_settings[*]}"
    fi
    
    # Count migrations
    local applied_count
    applied_count=$($mysql_cmd "SELECT COUNT(*) FROM schema_migrations" 2>/dev/null || echo "0")
    
    info "Schema verification passed"
    info "  - All required tables present"
    info "  - Applied migrations: $applied_count"
    
    if [[ ${#missing_settings[@]} -eq 0 ]]; then
        info "  - Phase 2 settings: OK"
    fi
}

cmd_wait() {
    info "Waiting for database to become available..."
    run_dbmate wait
    info "Database is ready"
}

# === Usage ===
usage() {
    cat <<EOF
pulldb-migrate - Database migration tool for pullDB

Usage: pulldb-migrate [options] <command>

Commands:
  status              Show migration status (applied/pending)
  up                  Apply all pending migrations
  rollback            Rollback the last migration
  new <name>          Create a new migration file
  verify              Verify schema is correct
  wait                Wait for database to become available

Options:
  --yes, -y           Non-interactive mode (skip confirmations)
  --verbose, -v       Show debug output
  --help, -h          Show this help message

Environment Variables:
  PULLDB_INSTALL_PREFIX       Installation directory (default: /opt/pulldb.service)
  PULLDB_MIGRATIONS_DIR       Migrations directory (default: \$INSTALL_PREFIX/migrations)
  PULLDB_COORDINATION_SECRET  AWS secret reference for DB credentials
  PULLDB_AWS_PROFILE          AWS CLI profile to use
  PULLDB_MYSQL_DATABASE       Database name (default: pulldb_service)
  PULLDB_MIGRATION_MYSQL_USER MySQL user for migrations (default: root)
  DATABASE_URL                Override: mysql://user:pass@host:port/database

Examples:
  # Check migration status
  pulldb-migrate status

  # Apply migrations interactively
  pulldb-migrate up

  # Apply migrations non-interactively (CI/upgrade scripts)
  pulldb-migrate up --yes

  # Create new migration
  pulldb-migrate new add_feature_table
EOF
}

# === Main ===
main() {
    local cmd=""
    local args=()
    
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --yes|-y)
                ASSUME_YES=1
                shift
                ;;
            --verbose|-v)
                VERBOSE=1
                shift
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            -*)
                fail "Unknown option: $1"
                ;;
            *)
                if [[ -z "$cmd" ]]; then
                    cmd="$1"
                else
                    args+=("$1")
                fi
                shift
                ;;
        esac
    done
    
    if [[ -z "$cmd" ]]; then
        usage
        exit 1
    fi
    
    check_prerequisites
    
    case "$cmd" in
        status)
            cmd_status
            ;;
        up)
            cmd_up
            ;;
        rollback)
            cmd_rollback
            ;;
        new)
            cmd_new "${args[0]:-}"
            ;;
        verify)
            cmd_verify
            ;;
        wait)
            cmd_wait
            ;;
        *)
            fail "Unknown command: $cmd"
            ;;
    esac
}

main "$@"
