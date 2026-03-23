#!/usr/bin/env bash
# Waits for MySQL to accept connections, then execs the given command.
# Used by supervisord to delay pulldb services until MySQL is ready.
set -euo pipefail

until mysql -e "SELECT 1" >/dev/null 2>&1; do
    sleep 2
done

exec "$@"
