#!/bin/bash
# Start dev server (kills any existing instance first)

set -e

echo "Killing any existing dev_server.py processes..."
pkill -f "dev_server.py" 2>/dev/null || true

echo "Waiting 5 seconds..."
sleep 5

echo "Starting dev server..."
cd /home/charleshandshy/Projects/pullDB && python3 scripts/dev_server.py &

echo "Dev server started (PID: $!)"
