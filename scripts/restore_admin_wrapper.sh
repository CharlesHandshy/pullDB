#!/bin/bash
# Restore pulldb-admin wrapper script after dev install
#
# pip install -e . overwrites /usr/local/bin/pulldb-admin with a Python entry point.
# This script restores the bash wrapper that auto-escalates to pulldb_service user.
#
# Usage:
#   ./scripts/restore_admin_wrapper.sh
#   make dev-install  # Runs pip install -e . followed by this script

set -euo pipefail

WRAPPER_PATH="/usr/local/bin/pulldb-admin"
VENV_ADMIN="/opt/pulldb.service/venv/bin/pulldb-admin"

# Check if running with sufficient privileges
if [[ $EUID -ne 0 ]]; then
    echo "Restoring pulldb-admin wrapper (requires sudo)..."
    exec sudo "$0" "$@"
fi

# Check if the production venv binary exists
if [[ ! -x "$VENV_ADMIN" ]]; then
    echo "Warning: $VENV_ADMIN not found. Skipping wrapper restore."
    echo "         (This is expected if pulldb.service package is not installed)"
    exit 0
fi

# Check if wrapper already correct (avoid unnecessary writes)
if [[ -f "$WRAPPER_PATH" ]] && head -1 "$WRAPPER_PATH" 2>/dev/null | grep -q '^#!/bin/bash'; then
    echo "pulldb-admin wrapper already in place."
    exit 0
fi

# Create the wrapper script
cat > "$WRAPPER_PATH" << 'WRAPPER_EOF'
#!/bin/bash
# pulldb-admin wrapper - auto-escalates to pulldb_service user
# Admin authorization is enforced by the CLI itself (checks SUDO_USER)
set -euo pipefail
exec sudo -u pulldb_service /opt/pulldb.service/venv/bin/pulldb-admin "$@"
WRAPPER_EOF

chmod 755 "$WRAPPER_PATH"
echo "Restored pulldb-admin wrapper: $WRAPPER_PATH"
