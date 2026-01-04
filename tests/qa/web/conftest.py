"""Pytest fixtures for web UI tests using Playwright MCP.

This module provides fixtures for testing the pullDB visualization web app.
Tests use the Playwright MCP browser tools for browser automation.
"""

from __future__ import annotations

import http.server
import os
import socketserver
import threading
from collections.abc import Generator
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------

WEB_DIR = Path(__file__).parent.parent.parent.parent / "graph-tools" / "web"


# ---------------------------------------------------------------------------
# HTTP Server Fixtures
# ---------------------------------------------------------------------------


class QuietHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that suppresses logging."""

    def log_message(self, format: str, *args: object) -> None:
        """Suppress all log messages."""
        pass


@pytest.fixture(scope="module")
def web_server() -> Generator[str, None, None]:
    """Start a local HTTP server for the web directory.
    
    Returns:
        Base URL of the local server (e.g., http://localhost:8765)
    """
    port = 8765
    
    # Change to web directory
    original_dir = os.getcwd()
    os.chdir(WEB_DIR)
    
    handler = QuietHTTPHandler
    httpd = socketserver.TCPServer(("", port), handler)
    httpd.allow_reuse_address = True
    
    # Start server in background thread
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    yield f"http://localhost:{port}"
    
    # Cleanup
    httpd.shutdown()
    os.chdir(original_dir)


@pytest.fixture(scope="module")
def graph_base_url(web_server: str) -> str:
    """Get the base URL for the web server."""
    return web_server


# ---------------------------------------------------------------------------
# Page URL Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def index_url(graph_base_url: str) -> str:
    """URL for the main index page."""
    return f"{graph_base_url}/index.html"


@pytest.fixture(scope="module")
def flow_url(graph_base_url: str) -> str:
    """URL for the flow chart page."""
    return f"{graph_base_url}/flow.html"


@pytest.fixture(scope="module")
def code_url(graph_base_url: str) -> str:
    """URL for the code graph page."""
    return f"{graph_base_url}/code.html"


# ---------------------------------------------------------------------------
# Test Data
# ---------------------------------------------------------------------------


@pytest.fixture
def expected_menu_items() -> list[dict[str, str]]:
    """Expected menu items on the index page."""
    return [
        {
            "text": "Code Structure Graph",
            "description": "Interactive 2D visualization of Python modules and classes",
            "href": "code.html",
        },
        {
            "text": "Logical Flow Graph",
            "description": "Interactive 2D Flow Chart with Drill-down",
            "href": "flow.html",
        },
    ]


@pytest.fixture
def flow_node_types() -> list[str]:
    """Expected node types in the flow chart legend."""
    return ["Start", "Process", "Decision", "Database", "End/Fail"]


@pytest.fixture
def code_control_buttons() -> list[str]:
    """Expected control buttons in the code graph."""
    return ["Search", "Minimize All", "Save & Exit"]
