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
# Builds DATABASE_URL from environment, socket auth, or AWS Secrets Manager
#
# LESSONS LEARNED:
# 1. For localhost, ALWAYS prefer socket auth - works with sudo, no passwords needed
# 2. Socket auth is more secure (no password in URL/environment)
# 3. AWS credentials may not be accessible when run as root (user-specific profiles)
#
# Priority for localhost:
#   1. DATABASE_URL environment variable (explicit override)
#   2. Unix socket auth (preferred - works with sudo, no passwords)
#   3. TCP with AWS Secrets Manager credentials (fallback)
#
# Priority for remote hosts:
#   1. DATABASE_URL environment variable
#   2. TCP with AWS Secrets Manager credentials
#
build_database_url() {
    # Default database for all paths
    local database="${PULLDB_MYSQL_DATABASE:-pulldb_service}"
    export MYSQL_DATABASE="$database"
    
    # Check if DATABASE_URL is already set (for testing/override)
    if [[ -n "${DATABASE_URL:-}" ]]; then
        debug "Using existing DATABASE_URL"
        return 0
    fi
    
    local host="${PULLDB_MYSQL_HOST:-localhost}"
    local port="${PULLDB_MYSQL_PORT:-3306}"
    local socket="${PULLDB_MYSQL_SOCKET:-}"
    
    # For localhost connections, ALWAYS prefer socket auth
    # This works with sudo, doesn't require passwords, and is more secure
    if [[ "$host" == "localhost" || "$host" == "127.0.0.1" ]]; then
        # Try common socket locations if not specified
        if [[ -z "$socket" ]]; then
            for sock_path in /var/run/mysqld/mysqld.sock /tmp/mysql.sock /var/lib/mysql/mysql.sock; do
                if [[ -S "$sock_path" ]]; then
                    socket="$sock_path"
                    debug "Found MySQL socket at: $socket"
                    break
                fi
            done
        fi
        
        # If socket exists, use socket auth
        # With MySQL auth_socket plugin, root user doesn't need a password
        # dbmate URL format for socket: mysql://user:pass@/database?socket=/path/to/socket
        if [[ -S "${socket:-}" ]]; then
            local mysql_user="${PULLDB_MIGRATION_MYSQL_USER:-root}"
            debug "Using Unix socket authentication at: $socket (user: $mysql_user)"
            # Note: empty password but still need : after user, @ before /
            export DATABASE_URL="mysql://${mysql_user}:@/${database}?socket=${socket}"
            # Track that we're using socket auth (for verify/baseline commands)
            export USE_SOCKET_AUTH="true"
            export SOCKET_PATH="$socket"
            export MYSQL_USER="$mysql_user"
            export MYSQL_DATABASE="$database"
            return 0
        fi
        
        debug "No socket found, will try TCP connection"
    fi
    
    # For remote connections or when socket is not available, use TCP with credentials
    local user="${PULLDB_MIGRATION_MYSQL_USER:-${PULLDB_MYSQL_USER:-pulldb_migrate}}"
    local password=""
    
    # Get password from AWS Secrets Manager
    local secret_ref="${PULLDB_COORDINATION_SECRET:-}"
    local aws_profile="${PULLDB_AWS_PROFILE:-}"
    
    if [[ -z "$secret_ref" ]]; then
        fail "No MySQL connection method available. Socket not found and PULLDB_COORDINATION_SECRET not set."
    fi
    
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
    
    # Get host/port from secret if present (may override PULLDB_MYSQL_HOST for remote)
    local secret_host secret_port
    secret_host=$(echo "$secret_json" | jq -r '.host // empty')
    secret_port=$(echo "$secret_json" | jq -r '.port // empty')
    
    if [[ -n "$secret_host" ]]; then
        host="$secret_host"
    fi
    if [[ -n "$secret_port" ]]; then
        port="$secret_port"
    fi
    
    password=$(echo "$secret_json" | jq -r '.password // empty')
    
    if [[ -z "$password" ]]; then
        fail "No password found in secret: $secret_name"
    fi
    
    # URL-encode password (handles special characters)
    local encoded_password
    encoded_password=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$password', safe=''))")
    
    # Build MySQL URL for dbmate (TCP connection)
    export DATABASE_URL="mysql://${user}:${encoded_password}@${host}:${port}/${database}"
    export USE_SOCKET_AUTH="false"
    export MYSQL_USER="$user"
    export MYSQL_DATABASE="$database"
    debug "DATABASE_URL constructed for host: $host (TCP)"
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

# === Build mysql client command ===
# Constructs mysql CLI command based on auth method
# Uses socket auth for localhost, TCP with password for remote
build_mysql_cmd() {
    local database="${1:-$MYSQL_DATABASE}"
    
    if [[ -n "$USE_SOCKET_AUTH" && "$USE_SOCKET_AUTH" == "true" ]]; then
        # Socket auth - no password needed
        echo "mysql --socket='$SOCKET_PATH' -u'$MYSQL_USER' '$database' -N -e"
    else
        # TCP auth - parse from DATABASE_URL
        local db_url="$DATABASE_URL"
        local user host port password
        
        user=$(echo "$db_url" | sed -E 's|mysql://([^:]+):.*|\1|')
        password=$(echo "$db_url" | sed -E 's|mysql://[^:]+:([^@]+)@.*|\1|' | python3 -c "import urllib.parse,sys; print(urllib.parse.unquote(sys.stdin.read().strip()))")
        host=$(echo "$db_url" | sed -E 's|mysql://[^@]+@([^:]+):.*|\1|')
        port=$(echo "$db_url" | sed -E 's|mysql://[^@]+@[^:]+:([0-9]+)/.*|\1|')
        
        echo "mysql -u'${user}' -p'${password}' -h'${host}' -P'${port}' '${database}' -N -e"
    fi
}

cmd_verify() {
    info "Verifying schema..."
    
    build_database_url
    
    local mysql_cmd
    mysql_cmd=$(build_mysql_cmd)
    
    # Verify essential tables exist
    local tables=("auth_users" "jobs" "job_events" "db_hosts" "settings" "locks" "schema_migrations")
    local missing=()
    
    for table in "${tables[@]}"; do
        if ! eval "$mysql_cmd \"SELECT 1 FROM information_schema.tables WHERE table_schema='${MYSQL_DATABASE}' AND table_name='${table}'\"" 2>/dev/null | grep -q 1; then
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
        if ! eval "$mysql_cmd \"SELECT 1 FROM settings WHERE setting_key='${setting}'\"" 2>/dev/null | grep -q 1; then
            missing_settings+=("$setting")
        fi
    done
    
    if [[ ${#missing_settings[@]} -gt 0 ]]; then
        warn "Missing settings (may need migration): ${missing_settings[*]}"
    fi
    
    # Count migrations
    local applied_count
    applied_count=$(eval "$mysql_cmd \"SELECT COUNT(*) FROM schema_migrations\"" 2>/dev/null || echo "0")
    
    info "Schema verification passed"
    info "  - All required tables present"
    info "  - Applied migrations: $applied_count"
    
    if [[ ${#missing_settings[@]} -eq 0 ]]; then
        info "  - Phase 2 settings: OK"
    fi
}

# === Baseline existing database ===
# Marks migrations as applied without running them
# Used when database already has schema from manual setup
cmd_baseline() {
    info "Baseline: marking existing migrations as applied..."
    
    build_database_url
    
    local mysql_cmd
    mysql_cmd=$(build_mysql_cmd)
    
    # Ensure schema_migrations table exists
    eval "$mysql_cmd \"CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(255) PRIMARY KEY)\"" 2>/dev/null
    
    # Get list of all migration files
    local migrations=()
    while IFS= read -r -d '' file; do
        migrations+=("$(basename "$file")")
    done < <(find "$MIGRATIONS_DIR" -maxdepth 1 -name "*.sql" -print0 | sort -z)
    
    if [[ ${#migrations[@]} -eq 0 ]]; then
        warn "No migration files found in $MIGRATIONS_DIR"
        return 0
    fi
    
    local baselined=0
    for migration in "${migrations[@]}"; do
        # Extract version (first 14 digits before underscore)
        local version
        version=$(echo "$migration" | grep -oE '^[0-9]+')
        
        if [[ -z "$version" ]]; then
            warn "Skipping invalid migration filename: $migration"
            continue
        fi
        
        # Check if already recorded
        if eval "$mysql_cmd \"SELECT 1 FROM schema_migrations WHERE version='$version'\"" 2>/dev/null | grep -q 1; then
            debug "Already recorded: $migration"
        else
            eval "$mysql_cmd \"INSERT INTO schema_migrations (version) VALUES ('$version')\"" 2>/dev/null
            info "  Baselined: $migration"
            ((baselined++))
        fi
    done
    
    info "Baseline complete: $baselined migrations recorded"
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
  baseline            Mark all migrations as applied (for existing databases)
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

Authentication:
  - For localhost: Uses socket auth (root or PULLDB_MIGRATION_MYSQL_USER)
  - For remote: Uses AWS Secrets Manager credentials
  - Override with DATABASE_URL for full control

Examples:
  # Check migration status
  pulldb-migrate status

  # Apply migrations interactively
  pulldb-migrate up

  # Apply migrations non-interactively (CI/upgrade scripts)
  pulldb-migrate up --yes

  # Baseline existing database (skip running migrations, just record them)
  pulldb-migrate baseline

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
        baseline)
            cmd_baseline
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
