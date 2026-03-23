#!/usr/bin/env bash
# =============================================================================
# pullDB — Post-upgrade validation
# =============================================================================
# Called by upgrade.sh after spinning up the green container.
# Runs three tiers of checks and exits non-zero on any failure.
#
# Usage:
#   ./scripts/validate.sh <container-name> <api-port> <env-file>
#
# Example:
#   ./scripts/validate.sh pulldb-green 18080 compose/.env.green
# =============================================================================
set -euo pipefail

CONTAINER="${1:?Usage: validate.sh <container> <api-port> <env-file>}"
API_PORT="${2:?Usage: validate.sh <container> <api-port> <env-file>}"
ENV_FILE="${3:?Usage: validate.sh <container> <api-port> <env-file>}"

# Load compose env for S3 validate path
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source <(grep -v '^\s*#' "$ENV_FILE" | grep '=')
fi

VALIDATE_S3_PATH="${PULLDB_VALIDATE_S3_PATH:-}"
VALIDATE_AWS_PROFILE="${PULLDB_VALIDATE_AWS_PROFILE:-}"
TEST_DB="dockertestrestore"
TEST_USER="pulldb_test"
TEST_PASS=""
PASS=true

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; PASS=false; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
step() { echo -e "\n── $* ──"; }

# ---------------------------------------------------------------------------
# Tier 1: API health check
# ---------------------------------------------------------------------------
check_health() {
    step "Tier 1: API health check"

    local attempts=0
    local response
    until response=$(curl -fsk --max-time 5 "https://localhost:${API_PORT}/api/health" 2>/dev/null); do
        (( attempts++ )) || true
        if (( attempts >= 24 )); then
            fail "API did not respond after 120 seconds"
            return
        fi
        sleep 5
    done

    local status
    status=$(echo "$response" | grep -o '"status":"[^"]*"' | cut -d'"' -f4 || echo "")
    if [[ "$status" == "ok" ]]; then
        ok "API health: ok"
    else
        fail "API health endpoint returned unexpected response: ${response}"
    fi
}

# ---------------------------------------------------------------------------
# Tier 2: Schema integrity check
# ---------------------------------------------------------------------------
EXPECTED_TABLES=(
    auth_users auth_credentials sessions api_keys
    db_hosts user_hosts jobs job_events job_history_summary
    locks settings admin_tasks audit_logs procedure_deployments
    disallowed_users feature_requests schema_migrations
)

check_schema() {
    step "Tier 2: Schema integrity"

    local missing=0
    for table in "${EXPECTED_TABLES[@]}"; do
        local exists
        exists=$(docker exec "$CONTAINER" \
            mysql pulldb_service -N \
            -e "SELECT COUNT(*) FROM information_schema.tables \
                WHERE table_schema='pulldb_service' AND table_name='${table}'" \
            2>/dev/null || echo "0")
        if [[ "$exists" == "1" ]]; then
            ok "Table: ${table}"
        else
            fail "Missing table: ${table}"
            (( missing++ )) || true
        fi
    done

    local admin_exists
    admin_exists=$(docker exec "$CONTAINER" \
        mysql pulldb_service -N \
        -e "SELECT COUNT(*) FROM auth_users WHERE username='admin'" \
        2>/dev/null || echo "0")
    if [[ "$admin_exists" == "1" ]]; then
        ok "Admin user present"
    else
        fail "Admin user missing"
    fi
}

# ---------------------------------------------------------------------------
# Tier 3: QA template restore test
# ---------------------------------------------------------------------------
check_qa_restore() {
    step "Tier 3: QA restore test"

    if [[ -z "$VALIDATE_S3_PATH" ]]; then
        warn "PULLDB_VALIDATE_S3_PATH not set — skipping QA restore test"
        return
    fi

    # Find most recent backup under the configured S3 path
    local aws_cmd="aws s3 ls ${VALIDATE_S3_PATH} --recursive"
    if [[ -n "$VALIDATE_AWS_PROFILE" ]]; then
        aws_cmd="aws --profile ${VALIDATE_AWS_PROFILE} s3 ls ${VALIDATE_S3_PATH} --recursive"
    fi

    local most_recent_key
    most_recent_key=$(docker exec "$CONTAINER" bash -c "${aws_cmd} 2>/dev/null | sort -k1,2 | tail -1 | awk '{print \$4}'" || true)

    if [[ -z "$most_recent_key" ]]; then
        fail "Could not find any backup at ${VALIDATE_S3_PATH}"
        return
    fi

    # Extract bucket from path (s3://bucket/prefix/ -> bucket)
    local s3_bucket
    s3_bucket=$(echo "$VALIDATE_S3_PATH" | sed 's|s3://||' | cut -d'/' -f1)
    ok "Most recent backup: s3://${s3_bucket}/${most_recent_key}"

    # Generate test credentials
    TEST_PASS=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 20)

    # Set up test database and user inside container's MySQL
    docker exec "$CONTAINER" mysql -e "
        CREATE DATABASE IF NOT EXISTS ${TEST_DB};
        CREATE USER IF NOT EXISTS '${TEST_USER}'@'localhost' IDENTIFIED BY '${TEST_PASS}';
        GRANT ALL ON ${TEST_DB}.* TO '${TEST_USER}'@'localhost';
        FLUSH PRIVILEGES;
    " 2>/dev/null || { fail "Could not create test database/user"; return; }
    ok "Test database '${TEST_DB}' created"

    # Download and extract the backup inside the container
    local download_exit=0
    docker exec "$CONTAINER" bash -c "
        set -euo pipefail
        WORK_DIR=/tmp/pulldb-validate-\$\$
        mkdir -p \"\$WORK_DIR\"
        trap 'rm -rf \"\$WORK_DIR\"' EXIT

        echo '  Downloading backup...'
        aws_cmd='aws'
        [[ -n '${VALIDATE_AWS_PROFILE:-}' ]] && aws_cmd='aws --profile ${VALIDATE_AWS_PROFILE}'
        \$aws_cmd s3 cp 's3://${s3_bucket}/${most_recent_key}' \"\$WORK_DIR/backup.tar\" 2>/dev/null \
            || \$aws_cmd s3 cp 's3://${s3_bucket}/${most_recent_key}' \"\$WORK_DIR/backup.tar.zst\" 2>/dev/null

        # Decompress if needed
        if [[ -f \"\$WORK_DIR/backup.tar.zst\" ]]; then
            zstd -d \"\$WORK_DIR/backup.tar.zst\" -o \"\$WORK_DIR/backup.tar\"
        fi

        mkdir -p \"\$WORK_DIR/extracted\"
        tar -xf \"\$WORK_DIR/backup.tar\" -C \"\$WORK_DIR/extracted\" 2>/dev/null || true

        # Find the actual dump directory (may be nested)
        DUMP_DIR=\$(find \"\$WORK_DIR/extracted\" -name 'metadata' -type f -exec dirname {} \\; | head -1)
        DUMP_DIR=\${DUMP_DIR:-\"\$WORK_DIR/extracted\"}

        echo '  Running myloader restore...'
        /opt/pulldb.service/bin/myloader-0.21.1-1 \
            --directory \"\$DUMP_DIR\" \
            --database ${TEST_DB} \
            --user ${TEST_USER} \
            --password '${TEST_PASS}' \
            --host 127.0.0.1 \
            --port 3306 \
            --drop-table \
            --verbose 1 \
            2>&1 | tail -5
    " || download_exit=$?

    if [[ $download_exit -ne 0 ]]; then
        fail "Restore test failed (exit ${download_exit})"
        _cleanup_test_db
        return
    fi

    # Verify tables were restored
    local table_count
    table_count=$(docker exec "$CONTAINER" \
        mysql -N \
        -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${TEST_DB}'" \
        2>/dev/null || echo "0")

    if (( table_count > 0 )); then
        ok "QA restore: ${table_count} tables restored successfully"
    else
        fail "QA restore: zero tables found in ${TEST_DB} after restore"
    fi

    _cleanup_test_db
}

_cleanup_test_db() {
    docker exec "$CONTAINER" mysql -e "
        DROP DATABASE IF EXISTS ${TEST_DB};
        DROP USER IF EXISTS '${TEST_USER}'@'localhost';
        FLUSH PRIVILEGES;
    " 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo ""
    echo "═══════════════════════════════════════════════════"
    echo "  pullDB Validation — container: ${CONTAINER}"
    echo "═══════════════════════════════════════════════════"

    check_health
    check_schema
    check_qa_restore

    echo ""
    if [[ "$PASS" == true ]]; then
        echo -e "  ${GREEN}ALL CHECKS PASSED${NC}"
        echo ""
        exit 0
    else
        echo -e "  ${RED}VALIDATION FAILED — upgrade aborted${NC}"
        echo ""
        exit 1
    fi
}

main
