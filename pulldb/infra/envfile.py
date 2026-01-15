"""Environment file utilities for pullDB configuration.

Provides thread-safe read/write operations for .env files with file locking
to prevent corruption from concurrent access.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import fcntl
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# .env file locations (in priority order)
DEFAULT_ENV_FILE_PATHS: list[Path] = [
    Path("/opt/pulldb.service/.env"),  # Installed system
    Path(__file__).parent.parent.parent / ".env",  # Repo root (dev)
]

# Retry configuration for file locking
LOCK_RETRY_COUNT = 3
LOCK_RETRY_DELAY_SECONDS = 5.0


def find_env_file(search_paths: Sequence[Path] | None = None) -> Path | None:
    """Find the .env file to use for read/write operations.

    Args:
        search_paths: Optional list of paths to search. Defaults to
            DEFAULT_ENV_FILE_PATHS.

    Returns:
        Path to first existing .env file, or None if not found.
    """
    paths = search_paths if search_paths is not None else DEFAULT_ENV_FILE_PATHS
    for path in paths:
        if path.exists():
            return path
    return None


def read_env_file(env_path: Path) -> dict[str, str]:
    """Read settings from .env file.

    Args:
        env_path: Path to the .env file.

    Returns:
        Dict mapping env var names to their values.
    """
    settings: dict[str, str] = {}
    if not env_path.exists():
        return settings

    with open(env_path) as f:
        for raw_line in f:
            stripped = raw_line.strip()
            # Skip comments and empty lines
            if not stripped or stripped.startswith("#"):
                continue
            # Handle KEY=value format
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove surrounding quotes if present
                if (value.startswith("'") and value.endswith("'")) or (
                    value.startswith('"') and value.endswith('"')
                ):
                    value = value[1:-1]
                settings[key] = value
    return settings


def _quote_env_value(value: str) -> str:
    """Quote an environment variable value for safe shell sourcing.

    Values containing spaces, special characters, or quotes need to be quoted.
    Uses single quotes by default, escaping any embedded single quotes.

    Args:
        value: The raw value to quote.

    Returns:
        Properly quoted value safe for .env file.
    """
    # If value contains spaces, newlines, or shell special characters, quote it
    needs_quoting = any(c in value for c in " \t\n\r'\"$`\\!#&|;()<>")

    if not needs_quoting:
        return value

    # Use single quotes - escape any embedded single quotes
    # In shell, 'foo'\''bar' produces foo'bar
    escaped = value.replace("'", "'\\''")
    return f"'{escaped}'"


def write_env_setting(
    env_path: Path,
    env_var: str,
    value: str,
    *,
    retries: int = LOCK_RETRY_COUNT,
    retry_delay: float = LOCK_RETRY_DELAY_SECONDS,
) -> tuple[bool, str | None]:
    """Write or update a single setting in the .env file with file locking.

    Uses exclusive file locking (fcntl.LOCK_EX) to prevent concurrent writes.
    Retries on lock contention.

    Args:
        env_path: Path to the .env file.
        env_var: Environment variable name (e.g., 'PULLDB_MYLOADER_TIMEOUT_SECONDS').
        value: Value to set.
        retries: Number of retry attempts on lock failure.
        retry_delay: Seconds to wait between retries.

    Returns:
        Tuple of (success, error_message). On success, error_message is None.
    """
    if not env_path.exists():
        return False, f".env file not found at {env_path}"

    for attempt in range(retries + 1):
        try:
            return _write_env_setting_locked(env_path, env_var, value)
        except BlockingIOError:
            if attempt < retries:
                logger.warning(
                    "Env file locked, retrying in %ss (attempt %d/%d)",
                    retry_delay,
                    attempt + 1,
                    retries,
                )
                time.sleep(retry_delay)
            else:
                return False, f"Could not acquire lock after {retries + 1} attempts"
        except OSError as e:
            return False, f"OS error writing env file: {e}"

    return False, "Unexpected error in write loop"


def _write_env_setting_locked(
    env_path: Path,
    env_var: str,
    value: str,
) -> tuple[bool, str | None]:
    """Write setting with exclusive file lock.

    Internal function - use write_env_setting() for retry logic.

    Raises:
        BlockingIOError: If lock cannot be acquired.
        OSError: On file system errors.
    """
    lines: list[str] = []
    found = False
    pattern = re.compile(rf"^{re.escape(env_var)}\s*=")

    # Quote value if it contains special characters
    quoted_value = _quote_env_value(value)

    # Open for read+write to hold lock during entire operation
    with open(env_path, "r+") as f:
        # Acquire exclusive lock (non-blocking to allow retry logic)
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            # Read current content
            for line in f:
                if pattern.match(line.strip()):
                    # Replace existing line
                    lines.append(f"{env_var}={quoted_value}\n")
                    found = True
                else:
                    lines.append(line)

            if not found:
                # Add new setting at end of file
                if lines and not lines[-1].endswith("\n"):
                    lines.append("\n")
                lines.append(f"{env_var}={quoted_value}\n")

            # Write back
            f.seek(0)
            f.truncate()
            f.writelines(lines)
        finally:
            # Release lock
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    logger.info("Updated env file: %s=%s", env_var, quoted_value)
    return True, None
