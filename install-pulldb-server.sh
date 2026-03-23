#!/usr/bin/env bash
# =============================================================================
# pullDB Server — One-Step Installer
# =============================================================================
# Handles all prerequisites, package install, MySQL setup, and service start
# in a single run. Works on bare Ubuntu and Docker stations.
#
# Usage:
#   sudo ./install-pulldb-server.sh [OPTIONS] [path/to/pulldb_*.deb]
#
# Options:
#   --skip-mysql          Skip MySQL server install (use when MySQL is external)
#   --mysql-host HOST     MySQL host for schema application (default: localhost)
#   --mysql-root-pass PW  MySQL root password (default: try socket auth, then empty)
#   --no-start            Install only — do not start services at the end
#   --yes                 Non-interactive: accept all defaults, skip prompts
#
# If no .deb path is given, the script looks for pulldb_*.deb in the
# current directory and picks the most recently modified one.
#
# Examples:
#   # Standard bare-metal install
#   sudo ./install-pulldb-server.sh pulldb_1.3.0_amd64.deb
#
#   # Docker install (MySQL in same container, already running)
#   sudo ./install-pulldb-server.sh --skip-mysql pulldb_1.3.0_amd64.deb
#
#   # Docker install with external MySQL sidecar
#   sudo ./install-pulldb-server.sh --skip-mysql --mysql-host db \
#       --mysql-root-pass secret pulldb_1.3.0_amd64.deb
# =============================================================================
set -euo pipefail

# =============================================================================
# Constants
# =============================================================================
INSTALL_PREFIX="/opt/pulldb.service"
ENV_FILE="${INSTALL_PREFIX}/.env"
SYSTEM_USER="pulldb_service"
LOG_FILE="/tmp/pulldb-install-$(date +%Y%m%d-%H%M%S).log"

# =============================================================================
# Output helpers
# =============================================================================
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

log_info()    { echo -e "${GREEN}[INFO]${NC}  $*" | tee -a "$LOG_FILE"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*" | tee -a "$LOG_FILE"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2 | tee -a "$LOG_FILE" >&2; }
log_step()    { echo -e "\n${BLUE}══ $* ${NC}" | tee -a "$LOG_FILE"; }
log_detail()  { echo    "         $*" | tee -a "$LOG_FILE"; }

# =============================================================================
# Argument parsing
# =============================================================================
DEB_PATH=""
SKIP_MYSQL=false
MYSQL_HOST="localhost"
MYSQL_ROOT_PASS=""
NO_START=false
YES=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-mysql)      SKIP_MYSQL=true; shift ;;
        --mysql-host)      MYSQL_HOST="$2"; shift 2 ;;
        --mysql-root-pass) MYSQL_ROOT_PASS="$2"; shift 2 ;;
        --no-start)        NO_START=true; shift ;;
        --yes)             YES=true; shift ;;
        --*)               log_error "Unknown option: $1"; exit 1 ;;
        *)                 DEB_PATH="$1"; shift ;;
    esac
done

# =============================================================================
# Pre-flight checks
# =============================================================================
preflight() {
    log_step "Pre-flight checks"

    # Must run as root
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root."
        log_detail "On a bare server: sudo ./install-pulldb-server.sh"
        log_detail "In Docker (root by default): ./install-pulldb-server.sh"
        exit 1
    fi
    log_info "Running as root"

    # Find the .deb
    if [[ -z "$DEB_PATH" ]]; then
        DEB_PATH=$(ls -t pulldb_*.deb 2>/dev/null | head -n 1 || true)
    fi
    if [[ -z "$DEB_PATH" || ! -f "$DEB_PATH" ]]; then
        log_error "No pulldb server package found."
        log_detail "Usage: $0 [options] pulldb_1.3.0_amd64.deb"
        log_detail "Build the package first with: make server"
        exit 1
    fi
    log_info "Package: $DEB_PATH"

    # Confirm if interactive and not --yes
    if [[ "$YES" != true && -t 0 ]]; then
        echo ""
        echo "  This will install pullDB server from: $DEB_PATH"
        echo "  Installation log: $LOG_FILE"
        echo ""
        read -r -p "  Continue? [Y/n] " confirm
        case "$confirm" in
            [nN]*) echo "Aborted."; exit 0 ;;
        esac
    fi

    log_info "Pre-flight passed"
}

# =============================================================================
# Step 1 — Prerequisites
# =============================================================================
install_prerequisites() {
    log_step "Step 1: Installing prerequisites"

    # Detect if apt-get update is needed (skip if lists are fresh)
    local lists_dir="/var/lib/apt/lists"
    if [[ -z "$(find "$lists_dir" -maxdepth 1 -mmin -60 2>/dev/null)" ]]; then
        log_info "Updating package lists..."
        apt-get update -qq 2>&1 | tee -a "$LOG_FILE"
    else
        log_info "Package lists are recent, skipping apt-get update"
    fi

    # software-properties-common — required by Pre-Depends (blocks dpkg -i if absent)
    if ! dpkg -l software-properties-common 2>/dev/null | grep -q "^ii"; then
        log_info "Installing software-properties-common (required by Pre-Depends)..."
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq software-properties-common \
            2>&1 | tee -a "$LOG_FILE"
    else
        log_info "software-properties-common: already installed"
    fi

    # openssl — postinst generates TLS cert; exits fatally if missing
    if ! command -v openssl &>/dev/null; then
        log_info "Installing openssl (required for TLS certificate generation)..."
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssl \
            2>&1 | tee -a "$LOG_FILE"
    else
        log_info "openssl: $(openssl version)"
    fi

    # ca-certificates — needed for update-ca-certificates after cert install
    if ! dpkg -l ca-certificates 2>/dev/null | grep -q "^ii"; then
        log_info "Installing ca-certificates..."
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates \
            2>&1 | tee -a "$LOG_FILE"
    else
        log_info "ca-certificates: already installed"
    fi

    log_info "Prerequisites satisfied"
}

# =============================================================================
# Step 2 — MySQL server
# =============================================================================
install_and_start_mysql() {
    log_step "Step 2: MySQL server"

    if [[ "$SKIP_MYSQL" == true ]]; then
        log_info "--skip-mysql set: skipping MySQL server install"
        log_info "Verifying MySQL is reachable at ${MYSQL_HOST}..."
        if ! _mysql_cmd "SELECT 1" &>/dev/null; then
            log_error "Cannot reach MySQL at host '${MYSQL_HOST}'"
            log_detail "Ensure MySQL is running and accessible, or omit --skip-mysql to install it."
            exit 1
        fi
        log_info "MySQL is reachable"
        return
    fi

    # Install if not present
    if ! command -v mysqld &>/dev/null && ! dpkg -l mysql-server 2>/dev/null | grep -q "^ii"; then
        log_info "Installing mysql-server..."
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mysql-server \
            2>&1 | tee -a "$LOG_FILE"
    else
        log_info "mysql-server: already installed"
    fi

    # Start MySQL — try systemctl first, fall back to service command (Docker)
    if _mysql_cmd "SELECT 1" &>/dev/null; then
        log_info "MySQL is already running"
    else
        log_info "Starting MySQL..."
        if command -v systemctl &>/dev/null && systemctl is-system-running &>/dev/null 2>&1; then
            systemctl start mysql 2>&1 | tee -a "$LOG_FILE" || true
        else
            # Docker: systemd not running, use service wrapper
            service mysql start 2>&1 | tee -a "$LOG_FILE" || \
                mysqld_safe --daemonize 2>>"$LOG_FILE" || true
        fi

        # Wait up to 15s for MySQL to be ready
        local attempts=0
        until _mysql_cmd "SELECT 1" &>/dev/null || (( attempts++ >= 15 )); do
            sleep 1
        done

        if ! _mysql_cmd "SELECT 1" &>/dev/null; then
            log_error "MySQL failed to start within 15 seconds."
            log_detail "Check: journalctl -u mysql  or  cat /var/log/mysql/error.log"
            exit 1
        fi
        log_info "MySQL started"
    fi
}

# Internal: run a MySQL command as root using best available auth method
_mysql_cmd() {
    local cmd="$1"
    if [[ -n "$MYSQL_ROOT_PASS" ]]; then
        mysql -h "$MYSQL_HOST" -u root -p"${MYSQL_ROOT_PASS}" -N -e "$cmd" 2>/dev/null
    elif [[ "$MYSQL_HOST" == "localhost" || "$MYSQL_HOST" == "127.0.0.1" ]]; then
        # Try socket auth (works on fresh Ubuntu install as root)
        mysql -N -e "$cmd" 2>/dev/null
    else
        # Remote host, no password supplied — try without password
        mysql -h "$MYSQL_HOST" -u root -N -e "$cmd" 2>/dev/null
    fi
}

# =============================================================================
# Step 3 — Install the package
# =============================================================================
install_package() {
    log_step "Step 3: Installing pullDB package"

    # Upgrade path: warn if already installed
    if dpkg -l pulldb 2>/dev/null | grep -q "^ii"; then
        local installed_ver
        installed_ver=$(dpkg -l pulldb | awk '/^ii/{print $3}')
        log_warn "pulldb ${installed_ver} is already installed — upgrading"
    fi

    log_info "Running dpkg -i ${DEB_PATH}..."
    DEBIAN_FRONTEND=noninteractive dpkg -i "$DEB_PATH" 2>&1 | tee -a "$LOG_FILE" || {
        log_warn "dpkg reported errors — attempting apt-get -f to resolve dependencies..."
        DEBIAN_FRONTEND=noninteractive apt-get install -f -y 2>&1 | tee -a "$LOG_FILE"
    }

    # Verify the package is now in installed state
    if ! dpkg -l pulldb 2>/dev/null | grep -q "^ii"; then
        log_error "Package installation failed. Check the log: $LOG_FILE"
        exit 1
    fi

    local installed_ver
    installed_ver=$(dpkg -l pulldb | awk '/^ii/{print $3}')
    log_info "pulldb ${installed_ver} installed"
}

# =============================================================================
# Step 4 — Schema (for external / sidecar MySQL only)
# =============================================================================
# When MySQL is local, postinst applies the schema during dpkg -i.
# When --skip-mysql is set with a remote host, postinst cannot reach MySQL
# via Unix socket and skips schema. We apply it here in that case.
apply_schema_if_needed() {
    if [[ "$SKIP_MYSQL" != true || "$MYSQL_HOST" == "localhost" ]]; then
        # Postinst handled it (or will have tried)
        return
    fi

    log_step "Step 4: Applying schema (remote MySQL)"

    local schema_dir="${INSTALL_PREFIX}/schema/pulldb_service"
    if [[ ! -d "$schema_dir" ]]; then
        log_error "Schema directory not found: ${schema_dir}"
        exit 1
    fi

    # Create the database if needed
    if ! _mysql_cmd "SELECT 1 FROM information_schema.schemata WHERE schema_name='pulldb_service'" \
            2>/dev/null | grep -q 1; then
        log_info "Creating pulldb_service database..."
        _mysql_cmd "CREATE DATABASE pulldb_service CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    else
        log_info "pulldb_service database already exists"
    fi

    # Check if schema is already applied
    if _mysql_cmd "SELECT 1 FROM information_schema.tables \
            WHERE table_schema='pulldb_service' AND table_name='jobs'" \
            2>/dev/null | grep -q 1; then
        log_info "Schema already present — skipping"
        return
    fi

    log_info "Applying schema files..."
    for subdir in 00_tables 01_views 02_seed 03_users; do
        if [[ -d "${schema_dir}/${subdir}" ]]; then
            for sql_file in "${schema_dir}/${subdir}"/*.sql; do
                [[ -f "$sql_file" ]] || continue
                log_detail "Applying ${subdir}/$(basename "$sql_file")..."
                if [[ -n "$MYSQL_ROOT_PASS" ]]; then
                    mysql -h "$MYSQL_HOST" -u root -p"${MYSQL_ROOT_PASS}" pulldb_service \
                        < "$sql_file" 2>>"$LOG_FILE" || {
                        log_error "Failed to apply $(basename "$sql_file")"
                        exit 1
                    }
                else
                    mysql -h "$MYSQL_HOST" -u root pulldb_service \
                        < "$sql_file" 2>>"$LOG_FILE" || {
                        log_error "Failed to apply $(basename "$sql_file")"
                        exit 1
                    }
                fi
            done
        fi
    done
    log_info "Schema applied"
}

# =============================================================================
# Step 5 — Replace placeholder MySQL passwords
# =============================================================================
secure_mysql_users() {
    log_step "Step 5: Securing MySQL service user passwords"

    # Generate strong random passwords (32 alphanumeric chars)
    local api_pass worker_pass
    api_pass=$(head -c 64 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)
    worker_pass=$(head -c 64 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 32)

    # Validate we got full-length passwords
    if [[ ${#api_pass} -lt 32 || ${#worker_pass} -lt 32 ]]; then
        log_error "Failed to generate random passwords from /dev/urandom"
        exit 1
    fi

    # Check if users exist before trying to alter them
    local api_exists worker_exists
    api_exists=$(_mysql_cmd "SELECT COUNT(*) FROM mysql.user WHERE User='pulldb_api'" 2>/dev/null || echo "0")
    worker_exists=$(_mysql_cmd "SELECT COUNT(*) FROM mysql.user WHERE User='pulldb_worker'" 2>/dev/null || echo "0")

    if [[ "$api_exists" == "0" ]]; then
        log_warn "pulldb_api MySQL user not found — schema may not have been applied yet"
        log_detail "Run schema manually: sudo mysql pulldb_service < ${INSTALL_PREFIX}/schema/pulldb_service/03_users/001_mysql_users.sql"
    else
        _mysql_cmd "ALTER USER 'pulldb_api'@'localhost' IDENTIFIED BY '${api_pass}'; FLUSH PRIVILEGES;" 2>>"$LOG_FILE"
        log_info "pulldb_api password set"
    fi

    if [[ "$worker_exists" == "0" ]]; then
        log_warn "pulldb_worker MySQL user not found"
    else
        _mysql_cmd "ALTER USER 'pulldb_worker'@'localhost' IDENTIFIED BY '${worker_pass}'; FLUSH PRIVILEGES;" 2>>"$LOG_FILE"
        log_info "pulldb_worker password set"
    fi

    # Write passwords to .env
    if [[ -f "$ENV_FILE" ]]; then
        _set_env_var "PULLDB_API_MYSQL_PASSWORD"    "${api_pass}"
        _set_env_var "PULLDB_WORKER_MYSQL_PASSWORD" "${worker_pass}"
        # Ensure MySQL host is set correctly if non-local
        if [[ "$MYSQL_HOST" != "localhost" ]]; then
            _set_env_var "PULLDB_MYSQL_HOST" "${MYSQL_HOST}"
        fi
        log_info "Passwords written to ${ENV_FILE}"
    else
        log_warn ".env not found at ${ENV_FILE} — cannot write passwords"
        log_detail "Set manually: PULLDB_API_MYSQL_PASSWORD and PULLDB_WORKER_MYSQL_PASSWORD"
    fi

    # Export for use in print_completion
    GENERATED_API_PASS="$api_pass"
    GENERATED_WORKER_PASS="$worker_pass"
}

# =============================================================================
# Step 6 — Generate session secret
# =============================================================================
generate_session_secret() {
    log_step "Step 6: Generating session secret"

    if [[ ! -f "$ENV_FILE" ]]; then
        log_warn ".env not found, skipping session secret generation"
        return
    fi

    # Check if a real secret is already set (not the placeholder comment)
    if grep -qE "^PULLDB_SESSION_SECRET=[a-f0-9]{32}" "$ENV_FILE" 2>/dev/null; then
        log_info "Session secret already set"
        return
    fi

    local session_secret
    session_secret=$(head -c 64 /dev/urandom | base64 | tr -dc 'a-f0-9' | head -c 64)

    _set_env_var "PULLDB_SESSION_SECRET" "${session_secret}"
    log_info "Session secret generated and written to .env"
}

# =============================================================================
# Step 7 — Start services
# =============================================================================
start_services() {
    if [[ "$NO_START" == true ]]; then
        log_step "Step 7: Service start skipped (--no-start)"
        return
    fi

    log_step "Step 7: Starting services"

    # Detect systemd availability
    local has_systemd=false
    if command -v systemctl &>/dev/null && systemctl is-system-running &>/dev/null 2>&1; then
        has_systemd=true
    fi

    if [[ "$has_systemd" == true ]]; then
        log_info "systemd detected — using systemctl"
        _start_systemd_services
    else
        log_info "systemd not available (Docker) — starting services directly"
        _start_direct_services
    fi
}

_start_systemd_services() {
    systemctl daemon-reload 2>/dev/null || true

    for svc in pulldb-api pulldb-worker; do
        if systemctl is-enabled "$svc" &>/dev/null 2>&1; then
            systemctl restart "$svc" 2>&1 | tee -a "$LOG_FILE" || true
            sleep 2
            if systemctl is-active --quiet "$svc" 2>/dev/null; then
                log_info "${svc}: running"
            else
                log_warn "${svc}: failed to start — check: journalctl -u ${svc} -n 20"
            fi
        else
            log_warn "${svc}: not enabled"
        fi
    done

    # Web UI: not auto-enabled, print the enable command
    log_info "Web UI (pulldb-web) not started by default"
    log_detail "Enable with: systemctl enable --now pulldb-web"
}

_start_direct_services() {
    local venv="${INSTALL_PREFIX}/venv"
    local log_dir
    log_dir=$(grep -E "^PULLDB_LOG_DIR=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "/mnt/data/logs/pulldb.service")

    mkdir -p "$log_dir" 2>/dev/null || true

    # Source .env for the services
    local env_args=()
    if [[ -f "$ENV_FILE" ]]; then
        while IFS= read -r line; do
            [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] && env_args+=("$line")
        done < <(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$')
    fi

    # Start API
    if [[ -x "${venv}/bin/pulldb-api" ]]; then
        env "${env_args[@]}" \
            "${venv}/bin/pulldb-api" \
            >> "${log_dir}/pulldb-api.log" 2>&1 &
        echo $! > /tmp/pulldb-api.pid
        sleep 2
        if kill -0 "$(cat /tmp/pulldb-api.pid 2>/dev/null)" 2>/dev/null; then
            log_info "pulldb-api: started (PID $(cat /tmp/pulldb-api.pid))"
        else
            log_warn "pulldb-api: may not have started — check ${log_dir}/pulldb-api.log"
        fi
    else
        log_warn "pulldb-api binary not found at ${venv}/bin/pulldb-api"
    fi

    # Start worker
    if [[ -x "${venv}/bin/pulldb-worker" ]]; then
        env "${env_args[@]}" \
            "${venv}/bin/pulldb-worker" \
            >> "${log_dir}/pulldb-worker.log" 2>&1 &
        echo $! > /tmp/pulldb-worker.pid
        sleep 1
        if kill -0 "$(cat /tmp/pulldb-worker.pid 2>/dev/null)" 2>/dev/null; then
            log_info "pulldb-worker: started (PID $(cat /tmp/pulldb-worker.pid))"
        else
            log_warn "pulldb-worker: may not have started — check ${log_dir}/pulldb-worker.log"
        fi
    else
        log_warn "pulldb-worker binary not found"
    fi

    log_info "Web UI not started by default in Docker mode"
    log_detail "Start manually: env \$(grep -v '^#' ${ENV_FILE} | xargs) ${venv}/bin/pulldb-web &"
}

# =============================================================================
# Helpers
# =============================================================================

# Set or replace a variable in .env (handles commented, missing, or existing)
_set_env_var() {
    local key="$1" value="$2"

    if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    elif grep -qE "^#\s*${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^#\s*${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        printf '\n%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}

# =============================================================================
# Completion summary
# =============================================================================
print_completion() {
    local version
    version=$(dpkg -l pulldb 2>/dev/null | awk '/^ii/{print $3}' || echo "unknown")

    local admin_pass=""
    if [[ -f "${INSTALL_PREFIX}/ADMIN_CREDENTIALS.txt" ]]; then
        admin_pass=$(grep "^Password:" "${INSTALL_PREFIX}/ADMIN_CREDENTIALS.txt" 2>/dev/null | awk '{print $2}' || true)
    fi

    local server_ip
    server_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "<server-ip>")

    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  pullDB ${version} — Installation Complete${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    echo ""

    if [[ -n "$admin_pass" ]]; then
        echo "  ┌──────────────────────────────────────────────────────────────┐"
        echo "  │  ADMIN CREDENTIALS (save these — shown once)                 │"
        echo "  │                                                              │"
        printf "  │    Username: %-47s│\n" "admin"
        printf "  │    Password: %-47s│\n" "$admin_pass"
        echo "  │                                                              │"
        echo "  │  Change after first login!                                   │"
        echo "  └──────────────────────────────────────────────────────────────┘"
        echo ""
    fi

    echo "  MySQL service users:"
    echo "    pulldb_api    password → written to ${ENV_FILE}"
    echo "    pulldb_worker password → written to ${ENV_FILE}"
    echo ""
    echo "  Web UI:    https://${server_ip}:8000  (enable: systemctl enable --now pulldb-web)"
    echo "  REST API:  https://${server_ip}:8080"
    echo ""
    echo "  TLS cert (self-signed, add to browser trust store if needed):"
    echo "    ${INSTALL_PREFIX}/tls/cert.pem"
    echo ""
    echo "  Configuration: ${ENV_FILE}"
    echo "  Install log:   ${LOG_FILE}"
    echo ""
    echo "  Next steps:"
    echo "    1. Edit ${ENV_FILE} — set PULLDB_AWS_PROFILE, PULLDB_COORDINATION_SECRET, S3 locations"
    echo "    2. Run the wizard any time: sudo ${INSTALL_PREFIX}/scripts/configure-pulldb.sh"
    echo "    3. Restart services after config changes:"
    echo "       systemctl restart pulldb-api pulldb-worker   (systemd)"
    echo "       OR kill/relaunch from PIDs in /tmp/pulldb-*.pid  (Docker)"
    echo ""
}

# =============================================================================
# Main
# =============================================================================
main() {
    echo ""
    echo -e "${BLUE}pullDB Server Installer${NC}"
    echo "Log: $LOG_FILE"
    echo ""

    preflight
    install_prerequisites
    install_and_start_mysql
    install_package
    apply_schema_if_needed
    secure_mysql_users
    generate_session_secret
    start_services
    print_completion
}

main
