#!/usr/bin/env bash
# Waits for MySQL to accept connections, then execs the given command.
# Used by supervisord to delay pulldb services until MySQL is ready.
set -euo pipefail

until bash -c "echo > /dev/tcp/127.0.0.1/3306" 2>/dev/null; do
    sleep 2
done

exec "$@"
