"""Basic import smoke tests ensuring package scaffolding works."""


def test_import_cli() -> None:
    """Test that CLI module can be imported."""
    import pulldb.cli.main as m  # noqa: F401


def test_import_daemon() -> None:
    """Test that daemon module can be imported."""
    import pulldb.daemon.main as m  # noqa: F401


def test_version() -> None:
    """Test that version string is accessible."""
    import pulldb

    assert pulldb.__version__ == "0.0.1.dev0"
