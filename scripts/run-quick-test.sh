#!/usr/bin/env bash
# Quick smoke test for pullDB installation
#
# Usage: bash run-quick-test.sh
#
# This script expects to be run within the test-env directory structure
# or with the test-env environment variables already loaded.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Try to source activate script if we are in test-env
if [[ -f "${SCRIPT_DIR}/activate-test-env.sh" ]]; then
    source "${SCRIPT_DIR}/activate-test-env.sh"
elif [[ -f "${SCRIPT_DIR}/../activate-test-env.sh" ]]; then
    source "${SCRIPT_DIR}/../activate-test-env.sh"
fi

echo "Running quick smoke tests..."
echo ""

# Test 1: CLI help
echo "✓ Testing CLI help..."
pulldb --help >/dev/null || { echo "✗ CLI help failed"; exit 1; }

# Test 2: Database connectivity
echo "✓ Testing database connectivity..."
python3 -c "
import mysql.connector
import os
try:
    conn = mysql.connector.connect(
        host=os.environ['PULLDB_MYSQL_HOST'],
        user=os.environ['PULLDB_MYSQL_USER'],
        password=os.environ['PULLDB_MYSQL_PASSWORD'],
        database=os.environ['PULLDB_MYSQL_DATABASE']
    )
    cursor = conn.cursor()
    cursor.execute('SELECT VERSION()')
    print(f'  MySQL version: {cursor.fetchone()[0]}')
    conn.close()
except Exception as e:
    print(f'Error: {e}')
    exit(1)
" || { echo "✗ Database connectivity failed"; exit 1; }

# Test 3: AWS credentials
echo "✓ Testing AWS credentials..."
aws sts get-caller-identity --profile "${PULLDB_AWS_PROFILE:-pr-dev}" >/dev/null || {
    echo "✗ AWS credentials not configured"
    echo "  Run: aws configure --profile ${PULLDB_AWS_PROFILE:-pr-dev}"
}

# Test 4: Import test
echo "✓ Testing Python imports..."
python3 -c "
from pulldb.cli import main
from pulldb.infra import mysql, s3, secrets
from pulldb.domain import config, models
print('  All imports successful')
" || { echo "✗ Import test failed"; exit 1; }

echo ""
echo "All smoke tests passed! ✓"
