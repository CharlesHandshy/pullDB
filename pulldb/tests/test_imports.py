"""Basic import smoke tests ensuring package scaffolding works."""

def test_import_cli():
    import pulldb.cli.main as m  # noqa: F401


def test_import_daemon():
    import pulldb.daemon.main as m  # noqa: F401


def test_version():
    import pulldb
    assert pulldb.__version__ == "0.0.1.dev0"
