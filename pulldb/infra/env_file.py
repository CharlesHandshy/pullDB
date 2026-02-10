"""Shared .env file operations for pullDB.

Provides unified env file discovery, reading, and writing across CLI and web layers.
This eliminates duplication of write_env_setting / find_env_file logic.

HCA Layer: shared (infrastructure)
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Canonical .env file paths in priority order.
# Production installs use /opt/pulldb.service/.env.
# Dev environments may use the repo root .env.
_REPO_ROOT = Path(__file__).parent.parent.parent

ENV_FILE_PATHS: list[Path] = [
    Path("/opt/pulldb.service/.env"),  # Installed system
    _REPO_ROOT / ".env",              # Repo root (dev)
]


def find_env_file() -> Path | None:
    """Locate the .env file, respecting PULLDB_ENV_FILE override.

    Search order:
      1. ``PULLDB_ENV_FILE`` environment variable (explicit override)
      2. ``/opt/pulldb.service/.env`` (production)
      3. Repo root ``.env`` (development)

    Returns:
        Path to the first existing .env, or None.
    """
    override = os.environ.get("PULLDB_ENV_FILE")
    if override:
        p = Path(override)
        return p if p.exists() else None

    for path in ENV_FILE_PATHS:
        if path.exists():
            return path
    return None


def read_env_file(env_path: Path) -> dict[str, str]:
    """Read all key=value pairs from a .env file.

    Handles comments, blank lines, and surrounding quotes.

    Returns:
        Dict mapping env var names to their unquoted values.
    """
    settings: dict[str, str] = {}
    if not env_path.exists():
        return settings

    with open(env_path) as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip()
                if (value.startswith("'") and value.endswith("'")) or (
                    value.startswith('"') and value.endswith('"')
                ):
                    value = value[1:-1]
                settings[key] = value
    return settings


def read_env_value(env_path: Path, env_var: str) -> str | None:
    """Read a single env var value from a .env file.

    Returns:
        The value string, or None if not found.
    """
    values = read_env_file(env_path)
    return values.get(env_var)


def write_env_setting(env_path: Path, env_var: str, value: str) -> bool:
    """Write or update a single setting in a .env file.

    If the env var already exists, its line is replaced in-place.
    If it doesn't exist, it is appended at the end.

    Args:
        env_path: Path to the .env file.
        env_var: The environment variable name (e.g. ``PULLDB_THREADS``).
        value: The value to write.

    Returns:
        True if the file was written successfully, False if the file does not exist.
    """
    if not env_path.exists():
        return False

    lines: list[str] = []
    found = False
    pattern = re.compile(rf"^{re.escape(env_var)}\s*=")

    with open(env_path) as f:
        for line in f:
            if pattern.match(line.strip()):
                lines.append(f"{env_var}={value}\n")
                found = True
            else:
                lines.append(line)

    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"{env_var}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)

    return True
