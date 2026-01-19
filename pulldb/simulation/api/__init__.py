from __future__ import annotations

"""Simulation Control API.

REST endpoints for controlling the simulation engine.
Only mounted when PULLDB_MODE=SIMULATION.

HCA Layer: pages (pulldb/simulation/api/)
"""

from pulldb.simulation.api.router import router

__all__ = ["router"]
