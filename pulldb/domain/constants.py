"""Centralized constants for the pullDB domain layer.

HCA Layer: entities (pulldb/domain/)

Canonical definitions of domain-wide constants. Other layers import from
here instead of duplicating values.
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────────
# Protected (system) databases
# ──────────────────────────────────────────────────────────────────────────────

PROTECTED_DATABASES: frozenset[str] = frozenset({
    "mysql",
    "information_schema",
    "performance_schema",
    "sys",
    "pulldb",
    "pulldb_service",
})
"""System databases that must never be dropped, cleaned up, or enumerated
as user databases. All comparisons should use `.lower()` before checking
membership."""
