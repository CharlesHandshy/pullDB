"""Myloader execution wrapper.

Translates a :class:`MyLoaderSpec` into a concrete myloader command,
invokes it via :func:`infra.exec.run_command`, and maps failures to
domain `MyLoaderError` exceptions (FAIL HARD semantics).

The wrapper intentionally limits scope to command construction +
error translation. Higher-level workflow orchestration (staging
creation, post-SQL, rename) will reside elsewhere.
"""

from __future__ import annotations

from collections.abc import Sequence

from pulldb.domain.errors import MyLoaderError
from pulldb.domain.restore_models import MyLoaderResult, MyLoaderSpec
from pulldb.infra.exec import (
    CommandExecutionError,
    CommandResult,
    CommandTimeoutError,
    run_command,
)


DEFAULT_MYLOADER_PATH = "myloader"  # Allow PATH resolution; override via extra_args
STDOUT_TAIL_LIMIT = 5000
STDERR_TAIL_LIMIT = 5000


def _build_command(spec: MyLoaderSpec) -> list[str]:
    """Build the myloader command from spec fields.

    Notes:
        * We pass credentials explicitly; future enhancement may use
          a defaults file or socket.
        * `--overwrite-tables` deliberately omitted until overwrite
          semantics are fully documented.
    """
    cmd: list[str] = [
        DEFAULT_MYLOADER_PATH,
        f"--database={spec.staging_db}",
        f"--host={spec.mysql_host}",
        f"--port={spec.mysql_port}",
        f"--user={spec.mysql_user}",
        f"--password={spec.mysql_password}",
        f"--directory={spec.backup_dir}",
    ]
    cmd.extend(spec.extra_args)
    return cmd


def run_myloader(
    spec: MyLoaderSpec,
    *,
    timeout: float | None = None,
) -> MyLoaderResult:
    """Execute myloader and return structured result.

    Raises:
        MyLoaderError: On non-zero exit, startup failure, or timeout.
    """
    command = _build_command(spec)

    try:
        result: CommandResult = run_command(
            command,
            env=spec.env,
            timeout=timeout,
        )
    except CommandTimeoutError as e:  # pragma: no cover - covered via higher-level test
        raise MyLoaderError(
            job_id=spec.job_id,
            command=e.command,
            exit_code=-1,
            stdout=e.partial_stdout[-STDOUT_TAIL_LIMIT:],
            stderr=e.partial_stderr[-STDERR_TAIL_LIMIT:],
        ) from e
    except CommandExecutionError as e:  # OS-level failure to start
        raise MyLoaderError(
            job_id=spec.job_id,
            command=command,
            exit_code=-1,
            stdout="",
            stderr=str(e),
        ) from e

    if result.exit_code != 0:
        raise MyLoaderError(
            job_id=spec.job_id,
            command=result.command,
            exit_code=result.exit_code,
            stdout=result.stdout[-STDOUT_TAIL_LIMIT:],
            stderr=result.stderr[-STDERR_TAIL_LIMIT:],
        )

    return MyLoaderResult(
        command=result.command,
        exit_code=result.exit_code,
        started_at=result.started_at,
        completed_at=result.completed_at,
        duration_seconds=result.duration_seconds,
        stdout=result.stdout[-STDOUT_TAIL_LIMIT:],
        stderr=result.stderr[-STDERR_TAIL_LIMIT:],
    )


__all__: Sequence[str] = ["MyLoaderResult", "MyLoaderSpec", "run_myloader"]
