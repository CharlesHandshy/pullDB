"""Myloader execution wrapper.

Translates a :class:`MyLoaderSpec` into a concrete myloader command,
invokes it via :func:`infra.exec.run_command`, and maps failures to
domain `MyLoaderError` exceptions (FAIL HARD semantics).

The wrapper intentionally limits scope to command construction +
error translation. Higher-level workflow orchestration (staging
creation, post-SQL, rename) will reside elsewhere.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pulldb.domain.config import Config
from pulldb.domain.errors import MyLoaderError
from pulldb.domain.models import Job
from pulldb.domain.restore_models import (
    MyLoaderResult,
    MyLoaderSpec,
    build_configured_myloader_spec,
)
from pulldb.infra.exec import (
    CommandExecutionError,
    CommandResult,
    CommandTimeoutError,
    run_command,
)
from pulldb.infra.metrics import (
    MetricLabels,
    emit_counter,
    emit_event,
    emit_timer,
    time_operation,
)
from pulldb.worker.atomic_rename import (
    AtomicRenameConnectionSpec,
    AtomicRenameSpec,
    atomic_rename_staging_to_target,
)
from pulldb.worker.metadata import (
    MetadataConnectionSpec,
    MetadataSpec,
    inject_metadata_table,
)
from pulldb.worker.post_sql import PostSQLConnectionSpec, execute_post_sql
from pulldb.worker.staging import (
    StagingConnectionSpec,
    cleanup_orphaned_staging,
)


# Use `MyLoaderSpec.binary_path` to select the myloader binary to execute.
STDOUT_TAIL_LIMIT = 5000
STDERR_TAIL_LIMIT = 5000


@dataclass(slots=True, frozen=True)
class RestoreWorkflowSpec:
    """Specification for complete restore workflow orchestration.

    Groups all required parameters for the restore workflow to satisfy
    argument count style limit (<= 5 arguments).

    Attributes:
        job: Job metadata including id, target, owner.
        backup_filename: S3 backup filename used for restore.
        staging_conn: MySQL connection spec for staging operations.
        post_sql_conn: Connection + script directory spec for post-SQL.
        myloader_spec: Myloader command specification.
        timeout: Optional myloader timeout in seconds.
    """

    job: Job
    backup_filename: str
    staging_conn: StagingConnectionSpec
    post_sql_conn: PostSQLConnectionSpec
    myloader_spec: MyLoaderSpec
    timeout: float | None = None


def build_restore_workflow_spec(
    *,
    config: Config,
    job: Job,
    backup_filename: str,
    backup_dir: str,
    staging_conn: StagingConnectionSpec,
    post_sql_conn: PostSQLConnectionSpec,
    extra_myloader_args: Sequence[str] | None = None,
    myloader_env: Mapping[str, str] | None = None,
    timeout_override: float | None = None,
    format_tag: str | None = None,
) -> RestoreWorkflowSpec:
    """Construct :class:`RestoreWorkflowSpec` using global configuration.

    This helper centralizes how worker code translates configuration + job
    metadata into a ready-to-run workflow specification, ensuring new knobs
    (binary path, timeout, threads) automatically flow to myloader.
    """
    if not job.staging_name:
        raise ValueError("job.staging_name is required to build restore workflow spec")

    myloader_spec = build_configured_myloader_spec(
        config=config,
        job_id=job.id,
        staging_db=job.staging_name,
        backup_dir=backup_dir,
        mysql_host=staging_conn.mysql_host,
        mysql_port=staging_conn.mysql_port,
        mysql_user=staging_conn.mysql_user,
        mysql_password=staging_conn.mysql_password,
        extra_args=extra_myloader_args,
        env=myloader_env,
        format_tag=format_tag,
    )

    timeout = timeout_override
    if timeout is None:
        timeout = config.myloader_timeout_seconds

    return RestoreWorkflowSpec(
        job=job,
        backup_filename=backup_filename,
        staging_conn=staging_conn,
        post_sql_conn=post_sql_conn,
        myloader_spec=myloader_spec,
        timeout=timeout,
    )


def _build_command(spec: MyLoaderSpec) -> list[str]:
    """Build the myloader command from spec fields.

    Notes:
        * We pass credentials explicitly; future enhancement may use
          a defaults file or socket.
        * `--overwrite-tables` deliberately omitted until overwrite
          semantics are fully documented.
    """
    cmd: list[str] = [
        spec.binary_path,
        f"--database={spec.staging_db}",
        f"--host={spec.mysql_host}",
        f"--port={spec.mysql_port}",
        f"--user={spec.mysql_user}",
        f"--password={spec.mysql_password}",
        f"--directory={spec.backup_dir}",
    ]
    cmd.extend(spec.extra_args)
    return cmd


def build_myloader_command(spec: MyLoaderSpec) -> list[str]:
    """Public helper for tests and external callers to build myloader command.

    This wraps the internal `_build_command` to provide a stable public API
    while keeping `_build_command` available for internal use.
    """
    return _build_command(spec)


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


def orchestrate_restore_workflow(
    spec: RestoreWorkflowSpec,
) -> dict[str, object]:
    """Orchestrate the full restore workflow for a single job.

    Steps:
        1. Staging lifecycle: cleanup orphaned staging DBs
        2. Myloader restore to staging DB
        3. Post-SQL execution (if scripts exist)
        4. Metadata table injection
        5. Atomic rename staging → target

    Args:
        spec: Complete workflow specification.

    Returns:
        dict: Structured result with all phase outputs and diagnostics.

    Raises:
        Exception: FAIL HARD on any error with actionable diagnostics.
    """
    logger = logging.getLogger("pulldb.restore.workflow")
    result: dict[str, object] = {}
    restore_started_at = datetime.now(UTC)
    job = spec.job

    try:
        # 1. Staging lifecycle: cleanup orphaned staging databases
        logger.info(
            {
                "phase": "staging",
                "job_id": job.id,
                "target": job.target,
            }
        )
        with time_operation(
            "staging_cleanup_duration_seconds",
            MetricLabels(job_id=job.id, target=job.target, phase="staging"),
        ):
            staging_result = cleanup_orphaned_staging(
                spec.staging_conn,
                job.target,
                job.id,
            )
        emit_counter(
            "staging_cleanup_total",
            labels=MetricLabels(job_id=job.id, target=job.target, phase="staging"),
        )
        result["staging"] = staging_result

        # 2. Myloader restore to staging database
        logger.info(
            {
                "phase": "myloader",
                "job_id": job.id,
                "staging_db": staging_result.staging_db,
            }
        )
        with time_operation(
            "myloader_duration_seconds",
            MetricLabels(job_id=job.id, target=job.target, phase="myloader"),
        ):
            myloader_result = run_myloader(spec.myloader_spec, timeout=spec.timeout)
        result["myloader"] = myloader_result

        # 3. Post-SQL execution (if scripts exist in script_dir)
        logger.info(
            {
                "phase": "post_sql",
                "job_id": job.id,
                "staging_db": staging_result.staging_db,
            }
        )
        with time_operation(
            "post_sql_duration_seconds",
            MetricLabels(job_id=job.id, target=job.target, phase="post_sql"),
        ):
            post_sql_result = execute_post_sql(spec.post_sql_conn)
        result["post_sql"] = post_sql_result

        restore_completed_at = datetime.now(UTC)

        # 4. Metadata table injection
        logger.info(
            {
                "phase": "metadata",
                "job_id": job.id,
                "staging_db": staging_result.staging_db,
            }
        )
        metadata_conn = MetadataConnectionSpec(
            staging_db=staging_result.staging_db,
            mysql_host=spec.staging_conn.mysql_host,
            mysql_port=spec.staging_conn.mysql_port,
            mysql_user=spec.staging_conn.mysql_user,
            mysql_password=spec.staging_conn.mysql_password,
            timeout_seconds=spec.staging_conn.timeout_seconds,
        )
        metadata_spec = MetadataSpec(
            job_id=job.id,
            owner_username=job.owner_username,
            target_db=job.target,
            backup_filename=spec.backup_filename,
            restore_started_at=restore_started_at,
            restore_completed_at=restore_completed_at,
            post_sql_result=post_sql_result,
        )
        with time_operation(
            "metadata_injection_duration_seconds",
            MetricLabels(job_id=job.id, target=job.target, phase="metadata"),
        ):
            inject_metadata_table(metadata_conn, metadata_spec)
        result["metadata"] = "injected"

        # 5. Atomic rename staging → target
        logger.info(
            {
                "phase": "atomic_rename",
                "job_id": job.id,
                "staging_db": staging_result.staging_db,
                "target_db": job.target,
            }
        )
        rename_conn = AtomicRenameConnectionSpec(
            mysql_host=spec.staging_conn.mysql_host,
            mysql_port=spec.staging_conn.mysql_port,
            mysql_user=spec.staging_conn.mysql_user,
            mysql_password=spec.staging_conn.mysql_password,
            timeout_seconds=spec.staging_conn.timeout_seconds,
        )
        rename_spec = AtomicRenameSpec(
            job_id=job.id,
            staging_db=staging_result.staging_db,
            target_db=job.target,
        )
        with time_operation(
            "atomic_rename_duration_seconds",
            MetricLabels(job_id=job.id, target=job.target, phase="atomic_rename"),
        ):
            atomic_rename_staging_to_target(rename_conn, rename_spec)
        result["atomic_rename"] = "complete"

        logger.info(
            {
                "phase": "workflow_complete",
                "job_id": job.id,
                "target": job.target,
                "duration_seconds": (
                    restore_completed_at - restore_started_at
                ).total_seconds(),
            }
        )
        emit_timer(
            "restore_workflow_duration_seconds",
            (restore_completed_at - restore_started_at).total_seconds(),
            MetricLabels(job_id=job.id, target=job.target, phase="workflow"),
        )
        emit_counter(
            "restore_workflow_success_total",
            labels=MetricLabels(
                job_id=job.id,
                target=job.target,
                phase="workflow",
                status="success",
            ),
        )

        return result
    except Exception as e:
        logger.error(
            {
                "phase": "fail_hard",
                "job_id": job.id,
                "target": job.target,
                "error": str(e),
            }
        )
        emit_event(
            "restore_workflow_failure",
            str(e),
            MetricLabels(
                job_id=job.id,
                target=job.target,
                phase="workflow",
                status="failed",
            ),
        )
        emit_counter(
            "restore_workflow_failure_total",
            labels=MetricLabels(
                job_id=job.id,
                target=job.target,
                phase="workflow",
                status="failed",
            ),
        )
        raise


__all__: Sequence[str] = [
    "MyLoaderResult",
    "MyLoaderSpec",
    "RestoreWorkflowSpec",
    "build_restore_workflow_spec",
    "orchestrate_restore_workflow",
    "run_myloader",
]
