from __future__ import annotations

"""Basic import smoke tests ensuring package scaffolding works.

HCA Layer: tests (pulldb/tests/)
"""


def test_import_cli() -> None:
    """CLI module import exposes main entry function."""
    from pulldb.cli import main as cli_main

    assert callable(cli_main.main)


def test_import_api() -> None:
    """API module import exposes application factory."""
    from pulldb.api import main as api_main

    assert callable(api_main.create_app)


def test_import_worker() -> None:
    """Worker service module import exposes main stub."""
    from pulldb.worker import service as worker_service

    assert callable(worker_service.main)


def test_version() -> None:
    """Test that version string is accessible."""
    import pulldb

    assert pulldb.__version__ == "1.0.6"
