"""Pytest configuration for admin web API tests.

These are unit tests that use FastAPI's TestClient to test API endpoints directly.
They don't need the browser/playwright fixtures from the parent conftest.py.
"""

from __future__ import annotations

import pytest


# Override the base_url fixture from parent conftest - we don't use it
@pytest.fixture(scope="session")
def base_url() -> str | None:
    """Disabled base_url fixture - admin tests don't use browser automation."""
    return None
