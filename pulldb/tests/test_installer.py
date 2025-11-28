"""Basic tests for install_pulldb.sh flag parsing and env file generation.

These tests run the installer in a temp directory with non-root override.
They do NOT attempt systemd operations (skipped via --no-systemd).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install_pulldb.sh"

pytestmark = pytest.mark.timeout(30)


def run_installer(prefix: Path, aws_profile: str, secret: str) -> str:
    env = os.environ.copy()
    env["PULLDB_INSTALLER_ALLOW_NON_ROOT"] = "1"
    env["PULLDB_INSTALLER_SKIP_PIP"] = "1"
    cmd = [
        "bash",
        str(SCRIPT),
        "--yes",
        "--no-systemd",
        "--prefix",
        str(prefix),
        "--aws-profile",
        aws_profile,
        "--secret",
        secret,
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, env=env, check=True)
    return result.stdout + result.stderr


def run_installer_validate(
    prefix: Path,
    aws_profile: str,
    secret: str,
    aws_stub_dir: Path,
) -> str:
    env = os.environ.copy()
    env["PULLDB_INSTALLER_ALLOW_NON_ROOT"] = "1"
    env["PULLDB_INSTALLER_SKIP_PIP"] = "1"
    # Prepend stub aws directory
    env["PATH"] = f"{aws_stub_dir}:{env['PATH']}"
    cmd = [
        "bash",
        str(SCRIPT),
        "--yes",
        "--no-systemd",
        "--validate",
        "--prefix",
        str(prefix),
        "--aws-profile",
        aws_profile,
        "--secret",
        secret,
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, env=env, check=True)
    return result.stdout + result.stderr


def test_installer_creates_env_and_venv(tmp_path: Path) -> None:
    prefix = tmp_path / "pulldb_test_install"
    output = run_installer(prefix, "devtest", "/pulldb/mysql/coordination-db")
    env_file = prefix / ".env"
    venv_dir = prefix / "venv"
    assert env_file.exists(), f".env not created. Output: {output}"
    assert venv_dir.exists(), f"venv not created. Output: {output}"
    content = env_file.read_text()
    assert "PULLDB_AWS_PROFILE=devtest" in content
    assert "PULLDB_COORDINATION_SECRET=/pulldb/mysql/coordination-db" in content


def test_installer_respects_no_systemd(tmp_path: Path) -> None:
    prefix = tmp_path / "pulldb_test_install2"
    output = run_installer(prefix, "dev", "/pulldb/mysql/coordination-db")
    # Ensure systemd unit not copied automatically (we passed --no-systemd)
    assert (
        "--no-systemd specified" in output or "skipping unit install" in output.lower()
    )
    unit_path = Path("/etc/systemd/system/pulldb-worker.service")
    # Unit path should not exist in test environment (soft assertion if present)
    try:
        if unit_path.exists():
            pytest.skip("Systemd unit already present on host; cannot assert absence.")
    except PermissionError:
        # Cannot read /etc/systemd/system - skip check (common in unprivileged tests)
        pass


def test_installer_usage_help(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PULLDB_INSTALLER_ALLOW_NON_ROOT"] = "1"
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    assert "Usage:" in result.stdout
    assert "--prefix" in result.stdout
    assert "--aws-profile" in result.stdout
    assert "--validate" in result.stdout


def test_installer_validate_warns_on_missing_aws(tmp_path: Path) -> None:
    prefix = tmp_path / "pulldb_test_install_validate"
    aws_stub_dir = tmp_path / "aws_stub"
    aws_stub_dir.mkdir()
    # Create stub aws executable that always fails
    stub = aws_stub_dir / "aws"
    stub.write_text("#!/usr/bin/env bash\nexit 2\n")
    stub.chmod(0o755)
    output = run_installer_validate(
        prefix,
        "devprofile",
        "/pulldb/mysql/coordination-db",
        aws_stub_dir,
    )
    # Expect validation attempts logged
    assert "Validating AWS profile" in output
    assert "Checking secret" in output
    # Warnings should appear because stub exits non-zero
    assert (
        "AWS profile validation failed" in output or "Secret describe failed" in output
    )


def test_installer_requires_root_without_override() -> None:
    """Installer must abort when not root and override env var absent.

    Skipped if tests run as root (cannot assert failure path).
    """
    if os.geteuid() == 0:  # pragma: no cover - environment dependent
        pytest.skip("Running as root; cannot test non-root failure path.")
    env = os.environ.copy()
    # Ensure override vars not set
    env.pop("PULLDB_INSTALLER_ALLOW_NON_ROOT", None)
    env.pop("PULLDB_INSTALLER_SKIP_PIP", None)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode != 0, (
        "Expected non-zero exit when run without root override"
    )
    assert "Installer must be run as root" in result.stderr
