#!/bin/bash
#
# pullDB Test Data Setup Script
# Populates test data in pulldb database for integration testing
#
# PREREQUISITES:
#   1. MySQL 8.0+ installed and running
#   2. pulldb database created (apply schema/pulldb.sql first)
#   3. AWS Secrets Manager secret created: /pulldb/mysql/coordination-db
#
# WHAT THIS SCRIPT DOES:
#   - Inserts test user for application logic testing (NOT for DB authentication)
#   - Test DB authentication uses AWS Secrets Manager (see .github/copilot-instructions.md)
#
# Usage: sudo ./setup-tests-dbdata.sh
#

set -euo pipefail  # Exit on error, undefined variables, pipe failures

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    print_error "Please run as root (use sudo)"
    exit 1
fi

print_info "Setting up pullDB test data"

# Check if MySQL is running
if ! systemctl is-active --quiet mysql; then
    print_error "MySQL service is not running. Please start MySQL first."
    exit 1
fi

# Check if pulldb database exists
DB_EXISTS=$(mysql -sN -e "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = 'pulldb';")

if [ -z "$DB_EXISTS" ]; then
    print_error "pulldb database does not exist. Apply schema/pulldb.sql first."
    exit 1
fi

print_info "Inserting test application user (testuser) for business logic testing..."

# Insert test user for application logic testing
# NOTE: This is NOT for database authentication - tests use AWS Secrets Manager for DB login
mysql pulldb <<'EOF'
-- Test user for application logic (NOT for DB authentication)
INSERT INTO auth_users (user_id, username, user_code, is_admin, created_at)
VALUES (
    '550e8400-e29b-41d4-a716-446655440099',
    'testuser',
    'testcd',
    FALSE,
    UTC_TIMESTAMP(6)
)
ON DUPLICATE KEY UPDATE
    username = VALUES(username),
    user_code = VALUES(user_code);
EOF

print_info "✓ Test user inserted (testuser / testcd)"

echo ""
print_info "=========================================="
print_info "✓ pullDB Test Data Setup Complete!"
print_info "=========================================="
echo ""
print_info "Test user: testuser (user_code: testcd)"
print_warn "IMPORTANT: Tests use AWS Secrets Manager for DB authentication"
print_warn "  Secret: /pulldb/mysql/coordination-db"
print_warn "  See: .github/copilot-instructions.md for mandate details"
echo ""
