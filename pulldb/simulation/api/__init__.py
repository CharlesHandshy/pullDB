"""Simulation Control API.

REST endpoints for controlling the simulation engine.
Only mounted when PULLDB_MODE=SIMULATION.
"""

from pulldb.simulation.api.router import router

__all__ = ["router"]
