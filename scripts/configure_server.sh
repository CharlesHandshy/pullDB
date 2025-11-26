#!/bin/bash
set -e

INSTALL_PREFIX="/opt/pulldb.service"
SYSTEM_USER="pulldb_service"

echo "=== pullDB Server Configuration ==="

# 1. AWS Setup
echo "Checking AWS credentials for ${SYSTEM_USER}..."
USER_HOME=$(getent passwd "${SYSTEM_USER}" | cut -d: -f6)

if [ -z "$USER_HOME" ]; then
    echo "Error: Could not find home directory for ${SYSTEM_USER}"
    exit 1
fi

AWS_DIR="${USER_HOME}/.aws"
mkdir -p "${AWS_DIR}"

# Copy AWS-SETUP.md to user home and install dir
cp "${INSTALL_PREFIX}/AWS-SETUP.md" "${USER_HOME}/AWS-SETUP.md"
chown "${SYSTEM_USER}:${SYSTEM_USER}" "${USER_HOME}/AWS-SETUP.md"

echo "Please ensure AWS credentials are configured in ${AWS_DIR}/credentials"
echo "Refer to ${USER_HOME}/AWS-SETUP.md for instructions."

# 2. Test Run
echo "Running basic validation..."
# We can run a simple command to check if the venv works and imports succeed
if sudo -u "${SYSTEM_USER}" "${INSTALL_PREFIX}/venv/bin/python" -c "import pulldb; print('pullDB module loaded successfully')" 2>/dev/null; then
    echo "Validation successful: pullDB python environment is operational."
else
    echo "Validation failed: Could not import pulldb module."
    exit 1
fi

echo "Configuration complete."
echo "To start the service: systemctl start pulldb-worker"
