#!/bin/bash
#
# MySQL 8.x Installation and Configuration Script for pullDB
# This script installs MySQL server, configures data directories on /mnt/data,
# and sets up the pulldb coordination database.
#
# Usage: sudo ./setup-mysql.sh
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Function to print colored output
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

print_info "Starting MySQL 8.x installation and configuration for pullDB"

# Step 1: Update package lists
print_info "Updating package lists..."
apt update

# Step 2: Install MySQL server and client
print_info "Installing MySQL server and client..."
DEBIAN_FRONTEND=noninteractive apt install -y mysql-server mysql-client

# Step 3: Install MySQL development libraries
print_info "Installing MySQL development libraries..."
apt install -y libmysqlclient-dev pkg-config

# Step 4: Check MySQL version
MYSQL_VERSION=$(mysql --version)
print_info "Installed: $MYSQL_VERSION"

# Step 5: Stop MySQL to configure data directories
print_info "Stopping MySQL service..."
systemctl stop mysql

# Step 6: Create data directories on /mnt/data
print_info "Creating MySQL data directories at /mnt/data/mysql..."
mkdir -p /mnt/data/mysql/data
mkdir -p /mnt/data/mysql/tmpdir

# Step 7: Copy existing MySQL data to new location
if [ -d "/var/lib/mysql" ] && [ "$(ls -A /var/lib/mysql)" ]; then
    print_info "Copying existing MySQL data to /mnt/data/mysql/data..."
    rsync -av /var/lib/mysql/ /mnt/data/mysql/data/
else
    print_warn "No existing MySQL data found at /var/lib/mysql"
fi

# Step 8: Set ownership and permissions
print_info "Setting ownership and permissions..."
chown -R mysql:mysql /mnt/data/mysql
chmod 750 /mnt/data/mysql/data
chmod 750 /mnt/data/mysql/tmpdir

# Step 9: Backup original MySQL configuration
MYSQL_CONFIG="/etc/mysql/mysql.conf.d/mysqld.cnf"
if [ -f "$MYSQL_CONFIG" ]; then
    print_info "Backing up original MySQL configuration..."
    cp "$MYSQL_CONFIG" "${MYSQL_CONFIG}.backup"
fi

# Step 10: Update MySQL configuration
print_info "Updating MySQL configuration..."
cat >> "$MYSQL_CONFIG" << 'EOF'

#
# * pullDB Custom Configuration
#
# Data and temporary directories on /mnt/data
datadir         = /mnt/data/mysql/data
tmpdir          = /mnt/data/mysql/tmpdir

# InnoDB settings
innodb_data_home_dir = /mnt/data/mysql/data
innodb_log_group_home_dir = /mnt/data/mysql/data

# Binary log location
log_bin         = /mnt/data/mysql/data/binlog
EOF

# Step 11: Update AppArmor permissions
print_info "Updating AppArmor permissions for new data directory..."
cat >> /etc/apparmor.d/local/usr.sbin.mysqld << 'EOF'
# pullDB custom data directory
/mnt/data/mysql/ r,
/mnt/data/mysql/** rwk,
EOF

systemctl reload apparmor

# Step 12: Start MySQL with new configuration
print_info "Starting MySQL with new configuration..."
systemctl start mysql

# Step 13: Verify MySQL is running
if systemctl is-active --quiet mysql; then
    print_info "MySQL service is running"
else
    print_error "MySQL service failed to start"
    systemctl status mysql
    exit 1
fi

# Step 14: Verify data directory configuration
print_info "Verifying MySQL configuration..."
DATADIR=$(mysql -sN -e "SHOW VARIABLES LIKE 'datadir';" | awk '{print $2}')
TMPDIR=$(mysql -sN -e "SHOW VARIABLES LIKE 'tmpdir';" | awk '{print $2}')

if [ "$DATADIR" = "/mnt/data/mysql/data/" ]; then
    print_info "✓ datadir: $DATADIR"
else
    print_error "✗ datadir: $DATADIR (expected /mnt/data/mysql/data/)"
fi

if [ "$TMPDIR" = "/mnt/data/mysql/tmpdir" ]; then
    print_info "✓ tmpdir: $TMPDIR"
else
    print_error "✗ tmpdir: $TMPDIR (expected /mnt/data/mysql/tmpdir)"
fi

# Step 15: Display disk usage
print_info "MySQL disk usage:"
du -sh /mnt/data/mysql/*

# Step 16: Installation complete
print_info ""
print_info "=========================================="
print_info "MySQL 8.x installation complete!"
print_info "=========================================="
print_info ""
print_info "Data directory: /mnt/data/mysql/data"
print_info "Temp directory: /mnt/data/mysql/tmpdir"
print_info ""
print_info "Next steps:"
print_info "1. Load schema: mysql -u root -p < $PROJECT_ROOT/schema/pulldb.sql"
print_info "2. Install Python MySQL libraries in your venv:"
print_info "   source venv/bin/activate"
print_info "   pip install mysql-connector-python pymysql"
print_info ""
