import os
import shlex
import subprocess
from typing import Any


def test_installer_help_references_quickstart(tmp_path: Any) -> None:
    cmd = "bash scripts/install_pulldb.sh --help"
    env = {**os.environ, "PULLDB_INSTALLER_ALLOW_NON_ROOT": "1"}
    proc = subprocess.run(
        shlex.split(cmd), capture_output=True, text=True, check=False, env=env
    )
    # exit code 0 expected for --help
    assert proc.returncode == 0
    out = proc.stdout + proc.stderr
    assert "docs/AWS-SETUP.md" in out
