import shlex
import subprocess
from typing import Any


def test_setup_test_env_dry_run(tmp_path: Any) -> None:
    cmd = "bash scripts/setup_test_env.sh --dry-run --venv .venv-temp"
    proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout + proc.stderr
    assert "Virtualenv directory: .venv-temp" in out
    assert "Packages to install" in out
    assert "mypy" in out  # sanity check a known package is listed
