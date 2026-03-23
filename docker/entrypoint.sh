#!/usr/bin/env bash
# =============================================================================
# pullDB container entrypoint
# =============================================================================
# Handles three boot scenarios:
#
#   FRESH INSTALL  — MySQL data dir is empty. Applies schema from image,
#                    generates admin password and MySQL user credentials.
#
#   UPGRADE (GREEN) — PULLDB_IMPORT_DUMP is set to a dump file path.
#                     Imports blue's mysqldump, applies any new schema files,
#                     re-creates MySQL service users from .env passwords.
#
#   RESTART        — MySQL data dir already has pulldb_service. Skips init,
#                    starts supervisord directly.
#
# =============================================================================
set -euo pipefail

INSTALL_PREFIX="/opt/pulldb.service"
ENV_FILE="${INSTALL_PREFIX}/.env"
SYSTEM_USER="pulldb_service"
SCHEMA_DIR="${INSTALL_PREFIX}/schema/pulldb_service"
LOG_DIR="/mnt/data/logs/pulldb"
MARKER="${INSTALL_PREFIX}/.container-initialized"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
log()  { echo "[entrypoint] $*"; }
die()  { echo "[entrypoint] FATAL: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Load .env into environment
# ---------------------------------------------------------------------------
load_env() {
    if [[ -f "$ENV_FILE" ]]; then
        set -a
        # shellcheck disable=SC1090
        source "$ENV_FILE" 2>/dev/null || true
        set +a
    fi
}

# ---------------------------------------------------------------------------
# Ensure required directories exist
# ---------------------------------------------------------------------------
ensure_dirs() {
    mkdir -p \
        "$LOG_DIR" \
        /mnt/data/work/pulldb.service \
        /mnt/data/tmp \
        /var/run/mysqld

    chown -R mysql:mysql /var/run/mysqld 2>/dev/null || true
    chown -R "${SYSTEM_USER}:${SYSTEM_USER}" /mnt/data 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Start MySQL (background) and wait until ready
# ---------------------------------------------------------------------------
mysql_start_wait() {
    log "Starting MySQL..."
    mysqld_safe --skip-networking --user=mysql &
    MYSQL_TEMP_PID=$!

    local attempts=0
    until mysql -e "SELECT 1" >/dev/null 2>&1; do
        (( attempts++ )) || true
        if (( attempts > 30 )); then
            die "MySQL did not become ready within 60 seconds"
        fi
        sleep 2
    done
    log "MySQL ready"
}

# ---------------------------------------------------------------------------
# Stop the temporary MySQL started during init
# ---------------------------------------------------------------------------
mysql_stop() {
    if [[ -n "${MYSQL_TEMP_PID:-}" ]]; then
        mysqladmin shutdown 2>/dev/null || kill "$MYSQL_TEMP_PID" 2>/dev/null || true
        wait "$MYSQL_TEMP_PID" 2>/dev/null || true
        MYSQL_TEMP_PID=""
    fi
}

# ---------------------------------------------------------------------------
# Apply schema files in order (idempotent — all use IF NOT EXISTS / INSERT IGNORE)
# ---------------------------------------------------------------------------
apply_schema() {
    log "Applying schema..."
    mysql -e "CREATE DATABASE IF NOT EXISTS pulldb_service CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    for subdir in 00_tables 01_views 02_seed 03_users; do
        if [[ -d "${SCHEMA_DIR}/${subdir}" ]]; then
            for sql_file in "${SCHEMA_DIR}/${subdir}"/*.sql; do
                [[ -f "$sql_file" ]] || continue
                log "  Applying ${subdir}/$(basename "$sql_file")..."
                mysql pulldb_service < "$sql_file" 2>/dev/null || {
                    log "  Warning: $(basename "$sql_file") reported errors (may be safe to ignore)"
                }
            done
        fi
    done
    log "Schema applied"
}

# ---------------------------------------------------------------------------
# Create / update MySQL service users using passwords from .env
# ---------------------------------------------------------------------------
ensure_mysql_users() {
    local api_user="${PULLDB_API_MYSQL_USER:-pulldb_api}"
    local worker_user="${PULLDB_WORKER_MYSQL_USER:-pulldb_worker}"
    local api_pass="${PULLDB_API_MYSQL_PASSWORD:-}"
    local worker_pass="${PULLDB_WORKER_MYSQL_PASSWORD:-}"

    if [[ -z "$api_pass" || -z "$worker_pass" ]]; then
        log "Warning: PULLDB_API_MYSQL_PASSWORD or PULLDB_WORKER_MYSQL_PASSWORD not set in .env"
        log "  Service users will use placeholder passwords — update .env and restart"
        return
    fi

    log "Configuring MySQL service users..."
    mysql -e "
        CREATE USER IF NOT EXISTS '${api_user}'@'localhost' IDENTIFIED BY '${api_pass}';
        ALTER USER '${api_user}'@'localhost' IDENTIFIED BY '${api_pass}';
        CREATE USER IF NOT EXISTS '${worker_user}'@'localhost' IDENTIFIED BY '${worker_pass}';
        ALTER USER '${worker_user}'@'localhost' IDENTIFIED BY '${worker_pass}';
        FLUSH PRIVILEGES;
    " 2>/dev/null || log "Warning: Could not set MySQL user passwords"
}

# ---------------------------------------------------------------------------
# Generate admin password if not already set
# ---------------------------------------------------------------------------
generate_admin_password() {
    local admin_exists
    admin_exists=$(mysql -N -e "SELECT COUNT(*) FROM pulldb_service.auth_users WHERE username='admin'" 2>/dev/null || echo "0")
    [[ "$admin_exists" == "0" ]] && return

    local has_password
    has_password=$(mysql -N -e "
        SELECT COUNT(*) FROM pulldb_service.auth_credentials c
        JOIN pulldb_service.auth_users u ON c.user_id = u.user_id
        WHERE u.username='admin' AND c.password_hash IS NOT NULL
    " 2>/dev/null || echo "1")

    [[ "$has_password" != "0" ]] && return

    log "Generating admin password..."
    local admin_pass
    admin_pass=$(head -c 48 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 16)

    "${INSTALL_PREFIX}/venv/bin/python3" -c "
import sys, bcrypt, mysql.connector
password = sys.argv[1].encode('utf-8')
hash_value = bcrypt.hashpw(password, bcrypt.gensalt(rounds=12)).decode('utf-8')
conn = mysql.connector.connect(unix_socket='/var/run/mysqld/mysqld.sock', database='pulldb_service')
cur = conn.cursor()
cur.execute('SELECT user_id FROM auth_users WHERE username = %s', ('admin',))
row = cur.fetchone()
if row:
    cur.execute('UPDATE auth_credentials SET password_hash = %s WHERE user_id = %s', (hash_value, row[0]))
    conn.commit()
cur.close(); conn.close()
" "$admin_pass" 2>/dev/null || { log "Warning: Could not set admin password"; return; }

    local creds_file="${INSTALL_PREFIX}/ADMIN_CREDENTIALS.txt"
    printf 'pullDB Initial Admin Credentials\nUsername: admin\nPassword: %s\n\nChange after first login!\n' \
        "$admin_pass" > "$creds_file"
    chmod 600 "$creds_file"

    log "============================================================"
    log "  ADMIN CREDENTIALS (also saved to ${creds_file})"
    log "  Username: admin"
    log "  Password: ${admin_pass}"
    log "  Change after first login!"
    log "============================================================"
}

# ---------------------------------------------------------------------------
# Generate TLS certificate if not present or expiring within 30 days
# ---------------------------------------------------------------------------
ensure_tls() {
    local tls_dir="${INSTALL_PREFIX}/tls"
    local cert="${tls_dir}/cert.pem"
    local key="${tls_dir}/key.pem"

    if [[ -f "$cert" && -f "$key" ]]; then
        if openssl x509 -checkend 2592000 -noout -in "$cert" 2>/dev/null; then
            log "TLS certificate valid"
            return
        fi
        log "TLS certificate expiring soon — regenerating..."
    fi

    mkdir -p "$tls_dir"

    local server_ip san_entries
    server_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")
    san_entries="DNS:localhost,IP:127.0.0.1"
    [[ -n "$server_ip" && "$server_ip" != "127.0.0.1" ]] && san_entries="${san_entries},IP:${server_ip}"

    log "Generating self-signed TLS certificate..."
    openssl req -x509 \
        -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
        -nodes \
        -keyout "$key" -out "$cert" \
        -days 3650 \
        -subj "/CN=pulldb-service/O=pullDB" \
        -addext "subjectAltName=${san_entries}" \
        2>/dev/null || die "Failed to generate TLS certificate — ensure openssl is installed"

    chown "${SYSTEM_USER}:${SYSTEM_USER}" "$cert" "$key"
    chmod 644 "$cert"
    chmod 600 "$key"

    cp "$cert" /usr/local/share/ca-certificates/pulldb-service.crt
    update-ca-certificates 2>/dev/null || true

    # Ensure .env has TLS vars
    if ! grep -q "^PULLDB_TLS_CERT=" "$ENV_FILE" 2>/dev/null; then
        cat >> "$ENV_FILE" << EOF

# TLS (auto-generated)
PULLDB_TLS_CERT=${cert}
PULLDB_TLS_KEY=${key}
PULLDB_API_URL=https://localhost:8080
REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
EOF
    fi
    log "TLS certificate generated"
}

# ---------------------------------------------------------------------------
# BOOT SCENARIO 1: Fresh install
# ---------------------------------------------------------------------------
init_fresh() {
    log "Boot scenario: FRESH INSTALL"
    mysql_start_wait
    apply_schema
    ensure_mysql_users
    generate_admin_password
    mysql_stop
}

# ---------------------------------------------------------------------------
# BOOT SCENARIO 2: Volume-copy upgrade
# MySQL data directory was copied directly from the previous container.
# Data is already present — just apply any new schema migrations and
# re-create service users from .env (users are not in the data copy).
# ---------------------------------------------------------------------------
init_from_volume_copy() {
    log "Boot scenario: VOLUME COPY — data directory already present"
    mysql_start_wait

    log "Applying any new schema migrations..."
    apply_schema

    ensure_mysql_users
    mysql_stop
}

# ---------------------------------------------------------------------------
# BOOT SCENARIO 3: Upgrade via mysqldump (legacy / fallback)
# ---------------------------------------------------------------------------
init_from_dump() {
    local dump_file="$1"
    log "Boot scenario: DUMP IMPORT — importing from ${dump_file}"
    mysql_start_wait

    log "Creating database..."
    mysql -e "CREATE DATABASE IF NOT EXISTS pulldb_service CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"

    log "Importing dump (this may take a few minutes)..."
    mysql pulldb_service < "$dump_file" || die "Failed to import dump: ${dump_file}"
    log "Dump imported"

    log "Applying any new schema migrations..."
    apply_schema

    ensure_mysql_users
    mysql_stop
}

# ===========================================================================
# Main
# ===========================================================================
main() {
    log "pullDB container starting..."
    load_env
    ensure_dirs

    if [[ -f "$MARKER" ]]; then
        # Container has already been initialized (restart scenario)
        log "Boot scenario: RESTART — skipping init"

    elif [[ -n "${PULLDB_IMPORT_DUMP:-}" ]]; then
        # Upgrade via dump (legacy / fallback)
        [[ -f "$PULLDB_IMPORT_DUMP" ]] || die "PULLDB_IMPORT_DUMP set but file not found: ${PULLDB_IMPORT_DUMP}"
        init_from_dump "$PULLDB_IMPORT_DUMP"
        touch "$MARKER"

    elif [[ -d "/var/lib/mysql/pulldb_service" ]]; then
        # Volume-copy upgrade: MySQL data directory was copied from previous container.
        # Data is present; apply migrations and re-create service users, then proceed.
        init_from_volume_copy
        touch "$MARKER"

    else
        # Fresh install
        init_fresh
        touch "$MARKER"
    fi

    ensure_tls

    # Final ownership pass
    chown -R "${SYSTEM_USER}:${SYSTEM_USER}" "${INSTALL_PREFIX}" 2>/dev/null || true
    chown -R "${SYSTEM_USER}:${SYSTEM_USER}" /mnt/data 2>/dev/null || true

    log "Starting supervisord..."
    exec supervisord -n -c /etc/supervisor/conf.d/pulldb.conf
}

main
