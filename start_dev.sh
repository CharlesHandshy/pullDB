#!/bin/bash
# Start dev server (kills any existing instance first)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Killing any existing dev_server.py processes..."
pkill -f "dev_server.py" 2>/dev/null || true

echo "Waiting 5 seconds..."
sleep 5

echo "Starting dev server..."
cd "$SCRIPT_DIR" && python3 scripts/dev_server.py &

echo "Dev server started (PID: $!)"
