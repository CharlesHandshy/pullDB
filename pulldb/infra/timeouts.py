"""Centralized timeout constants for pullDB.

HCA Layer: shared (pulldb/infra/)

This module consolidates all timeout-related constants to ensure consistency
across the codebase. All timeouts should be imported from here rather than
defined locally in each module.

Timeout Categories:
1. MySQL connect_timeout: Time to establish TCP connection to MySQL server
2. Operation timeouts: Time for long-running operations (restore, post-SQL)
3. Stale timeouts: Time before a job is considered orphaned/stuck
4. API timeouts: Time for HTTP client requests

Environment Variables:
- PULLDB_MYSQL_CONNECT_TIMEOUT_WORKER: Worker operations (default: 30s)
- PULLDB_MYSQL_CONNECT_TIMEOUT_API: API operations (default: 10s)
- PULLDB_MYSQL_CONNECT_TIMEOUT_MONITOR: Monitoring operations (default: 5s)
"""
from __future__ import annotations

import os

# =============================================================================
# MySQL Connection Timeouts (connect_timeout parameter)
# =============================================================================

# Worker operations: staging, restore, atomic rename, cleanup
# Longer timeout because these are critical operations and network latency matters
DEFAULT_MYSQL_CONNECT_TIMEOUT_WORKER = 30

# API operations: user-facing, provisioning, secret rotation
# Shorter timeout to fail fast for user experience
DEFAULT_MYSQL_CONNECT_TIMEOUT_API = 10

# Monitoring/polling operations: processlist, health checks
# Shortest timeout - background operations that shouldn't block
DEFAULT_MYSQL_CONNECT_TIMEOUT_MONITOR = 5


def get_mysql_connect_timeout_worker() -> int:
    """Get worker connect timeout from environment or default."""
    env_val = os.environ.get("PULLDB_MYSQL_CONNECT_TIMEOUT_WORKER")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    return DEFAULT_MYSQL_CONNECT_TIMEOUT_WORKER


def get_mysql_connect_timeout_api() -> int:
    """Get API connect timeout from environment or default."""
    env_val = os.environ.get("PULLDB_MYSQL_CONNECT_TIMEOUT_API")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    return DEFAULT_MYSQL_CONNECT_TIMEOUT_API


def get_mysql_connect_timeout_monitor() -> int:
    """Get monitor connect timeout from environment or default."""
    env_val = os.environ.get("PULLDB_MYSQL_CONNECT_TIMEOUT_MONITOR")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    return DEFAULT_MYSQL_CONNECT_TIMEOUT_MONITOR


# =============================================================================
# Operation Timeouts (for long-running MySQL operations)
# =============================================================================

# Default timeout for myloader/staging operations (24 hours)
DEFAULT_MYSQL_OPERATION_TIMEOUT = 86400

# Default timeout for post-SQL script execution (30 minutes)
DEFAULT_POST_SQL_TIMEOUT = 1800


# =============================================================================
# Stale Job Timeouts (for orphan recovery)
# =============================================================================

# Running jobs without heartbeat updates are considered stale after this many minutes
STALE_RUNNING_TIMEOUT_MINUTES = 30

# Orphaned task queue entries are reclaimed after this many minutes
STALE_TASK_TIMEOUT_MINUTES = 30

# Jobs stuck in "deleting" state are considered stale after this many minutes
STALE_DELETE_TIMEOUT_MINUTES = 30


# =============================================================================
# AWS SDK Timeouts
# =============================================================================

# AWS Secrets Manager / boto3 connection timeout
DEFAULT_AWS_CONNECT_TIMEOUT = 5.0

# AWS Secrets Manager / boto3 read timeout
DEFAULT_AWS_READ_TIMEOUT = 10.0


# =============================================================================
# API Client Timeouts
# =============================================================================

# Default timeout for CLI HTTP requests to API
DEFAULT_API_CLIENT_TIMEOUT = 30.0
