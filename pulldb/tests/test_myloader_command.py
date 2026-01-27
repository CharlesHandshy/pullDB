from __future__ import annotations

"""HCA Layer: tests."""
import pulldb.worker.restore as restore_module
from pulldb.domain.restore_models import MyLoaderSpec


def test_build_command_uses_binary_and_extra_args() -> None:
    spec = MyLoaderSpec(
        job_id="j1",
        staging_db="stg_db",
        backup_dir="/tmp/backup",
        mysql_host="db",
        mysql_port=3306,
        mysql_user="u",
        mysql_password="p",
        extra_args=("--threads=4", "--drop-table"),
        binary_path="/opt/custom/bin/myloader",
    )
    cmd = restore_module.build_myloader_command(spec)
    assert cmd[0] == "/opt/custom/bin/myloader"
    assert "--threads=4" in cmd
    assert "--drop-table" in cmd
