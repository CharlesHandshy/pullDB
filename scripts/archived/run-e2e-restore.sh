#!/bin/bash
set -e

# Source the test environment configuration
source test-env/venv/bin/activate

# Set up environment variables
export PULLDB_MYLOADER_BINARY="$(pwd)/pulldb/binaries/myloader-0.19.3-3"
export PULLDB_AWS_PROFILE=pr-dev
export PULLDB_S3_AWS_PROFILE=pr-staging
export PULLDB_MYSQL_HOST=localhost
export PULLDB_MYSQL_USER=pulldb
export PULLDB_MYSQL_PASSWORD=password
export PULLDB_MYSQL_DATABASE=pulldb_test_coordination

# Ensure the binary is executable
chmod +x "$PULLDB_MYLOADER_BINARY"

echo "Starting E2E restore test..."
echo "Using myloader binary: $PULLDB_MYLOADER_BINARY"
echo "AWS Profile: $PULLDB_AWS_PROFILE"
echo "S3 AWS Profile: $PULLDB_S3_AWS_PROFILE"

# Run the restore command
# Using 'overwrite' to avoid interactive prompts if the target exists
pulldb restore user=testuser customer=pestdemo overwrite

echo "E2E restore test initiated. Check logs for progress."
