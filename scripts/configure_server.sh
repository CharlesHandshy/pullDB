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
chown "${SYSTEM_USER}:${SYSTEM_USER}" "${AWS_DIR}"
chmod 700 "${AWS_DIR}"

# Create example AWS config (never overwrite existing)
AWS_CONFIG_EXAMPLE="${AWS_DIR}/config.example"
cat > "${AWS_CONFIG_EXAMPLE}" <<'EOF'
# AWS CLI Configuration (example)
# Copy to 'config' and customize for your environment
# For EC2 instances with Instance Profile, this may not be needed.

[profile pr-prod]
role_arn = arn:aws:iam::448509429610:role/pulldb-cross-account-readonly
credential_source = Ec2InstanceMetadata
region = us-east-1

[profile dev]
# For local development with SSO or static credentials
# region = us-east-1
EOF
chown "${SYSTEM_USER}:${SYSTEM_USER}" "${AWS_CONFIG_EXAMPLE}"

if [ -f "${AWS_DIR}/config" ]; then
    echo "Existing ${AWS_DIR}/config preserved. See ${AWS_CONFIG_EXAMPLE} for defaults."
else
    cp "${AWS_CONFIG_EXAMPLE}" "${AWS_DIR}/config"
    chown "${SYSTEM_USER}:${SYSTEM_USER}" "${AWS_DIR}/config"
    chmod 600 "${AWS_DIR}/config"
    echo "Created ${AWS_DIR}/config from example."
fi

# Copy AWS-SETUP.md to user home (informational, safe to overwrite)
if [ -f "${INSTALL_PREFIX}/AWS-SETUP.md" ]; then
    cp "${INSTALL_PREFIX}/AWS-SETUP.md" "${USER_HOME}/AWS-SETUP.md"
    chown "${SYSTEM_USER}:${SYSTEM_USER}" "${USER_HOME}/AWS-SETUP.md"
fi

echo "AWS configuration files are in ${AWS_DIR}/"
echo "Refer to ${USER_HOME}/AWS-SETUP.md for detailed instructions."

# 2. Test Run
echo "Running basic validation..."
if sudo -u "${SYSTEM_USER}" "${INSTALL_PREFIX}/venv/bin/python" -c "import pulldb; print('pullDB module loaded successfully')" 2>/dev/null; then
    echo "Validation successful: pullDB python environment is operational."
else
    echo "Validation failed: Could not import pulldb module."
    exit 1
fi

echo "Configuration complete."
echo "To start the service: systemctl start pulldb-worker"
