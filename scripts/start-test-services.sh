#!/usr/bin/env bash
# Start pullDB services in the test environment
#
# Usage: bash start-test-services.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_ENV_DIR="${SCRIPT_DIR}/../test-env"

# Handle case where script is run from test-env dir (copied there)
if [[ -f "${SCRIPT_DIR}/activate-test-env.sh" ]]; then
    TEST_ENV_DIR="${SCRIPT_DIR}"
fi

if [[ ! -f "${TEST_ENV_DIR}/activate-test-env.sh" ]]; then
    echo "Error: activate-test-env.sh not found in ${TEST_ENV_DIR}"
    exit 1
fi

source "${TEST_ENV_DIR}/activate-test-env.sh"

echo "DEBUG: PULLDB_S3_BACKUP_LOCATIONS is configured"

LOG_DIR="${TEST_ENV_DIR}/logs"
mkdir -p "$LOG_DIR"

echo "Starting pullDB services..."

# Check if already running
if pgrep -f "pulldb-api" >/dev/null; then
    echo "Warning: pulldb-api seems to be running already."
else
    echo "Starting pulldb-api..."
    nohup pulldb-api --host 127.0.0.1 --port 8080 > "${LOG_DIR}/pulldb-api.log" 2>&1 &
    echo $! > "${LOG_DIR}/pulldb-api.pid"
    echo "  PID: $(cat "${LOG_DIR}/pulldb-api.pid")"
fi

if pgrep -f "pulldb-worker" >/dev/null; then
    echo "Warning: pulldb-worker seems to be running already."
else
    echo "Starting pulldb-worker..."
    nohup pulldb-worker --poll-interval 1 > "${LOG_DIR}/pulldb-worker.log" 2>&1 &
    echo $! > "${LOG_DIR}/pulldb-worker.pid"
    echo "  PID: $(cat "${LOG_DIR}/pulldb-worker.pid")"
fi

echo "Services started. Logs in ${LOG_DIR}"
