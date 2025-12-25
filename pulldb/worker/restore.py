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
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pulldb.domain.config import Config
from pulldb.domain.errors import MyLoaderError
from pulldb.domain.models import CommandResult, Job
from pulldb.domain.restore_models import (
    MyLoaderResult,
    MyLoaderSpec,
    build_configured_myloader_spec,
)
from pulldb.infra.exec import (
    CommandExecutionError,
    CommandTimeoutError,
    run_command_streaming,
)
from pulldb.infra.logging import get_logger
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
from pulldb.worker.metadata_synthesis import ensure_compatible_metadata
from pulldb.worker.post_sql import PostSQLConnectionSpec, execute_post_sql
from pulldb.worker.staging import (
    StagingConnectionSpec,
    cleanup_orphaned_staging,
)


# Use `MyLoaderSpec.binary_path` to select the myloader binary to execute.
STDOUT_TAIL_LIMIT = 5000
STDERR_TAIL_LIMIT = 5000

logger = get_logger("pulldb.worker.restore")


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
    progress_callback: Callable[[float, dict[str, Any]], None] | None = None
    event_callback: Callable[[str, dict[str, Any]], None] | None = None


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
    progress_callback: Callable[[float, dict[str, Any]], None] | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> RestoreWorkflowSpec:
    """Construct :class:`RestoreWorkflowSpec` using global configuration.

    This helper centralizes how worker code translates configuration + job
    metadata into a ready-to-run workflow specification, ensuring new knobs
    (binary path, timeout, threads) automatically flow to myloader.

    Args:
        event_callback: Optional callback for emitting phase events. Called with
            (event_type, detail_dict) for post_sql_started, post_sql_complete,
            metadata_started, metadata_complete, atomic_rename_started,
            atomic_rename_complete events.
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
        progress_callback=progress_callback,
        event_callback=event_callback,
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


def _count_restore_tasks(backup_dir: str) -> int:
    path = Path(backup_dir)
    count = 0
    # Count .sql, .sql.gz, .sql.zst files
    for p in path.glob("**/*.sql*"):
        if p.is_file():
            count += 1
    return count


def _detect_backup_version(backup_dir: str) -> str:
    """Detect backup version based on metadata content and extensions.

    Priority:
    1. Metadata file content (INI = 0.19+, Text = 0.9)
    2. File extensions (.zst = 0.19+, .gz = 0.9)
    """
    path = Path(backup_dir)
    metadata_path = path / "metadata"

    # 1. Primary Check: Metadata File Content
    if metadata_path.exists():
        try:
            with open(metadata_path, encoding="utf-8", errors="ignore") as f:
                # Read first non-empty line
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("["):
                        return "0.19+ (INI metadata)"
                    return "0.9 (Legacy metadata)"
        except Exception:
            pass  # Fallback if unreadable

    # 2. Fallback: .zst extension is definitive for 0.19+
    #    (.gz is NOT reliable - both formats can use gzip compression)
    if any(path.glob("**/*.zst")):
        return "0.19+ (zst extension)"

    # 3. No metadata and no .zst - assume legacy (conservative)
    #    Metadata synthesis will handle conversion if needed
    return "unknown (assuming legacy)"


def run_myloader(
    spec: MyLoaderSpec,
    *,
    timeout: float | None = None,
    progress_callback: Callable[[float, dict[str, Any]], None] | None = None,
) -> MyLoaderResult:
    """Execute myloader and return structured result.

    Raises:
        MyLoaderError: On non-zero exit, startup failure, or timeout.
    """
    logger = logging.getLogger("pulldb.restore.myloader")
    command = _build_command(spec)

    # Detect version
    version_info = _detect_backup_version(spec.backup_dir)
    logger.info(f"Detected backup version info: {version_info}")

    # Ensure metadata compatibility (synthesize if needed)
    ensure_compatible_metadata(spec.backup_dir)

    # Count tasks for progress
    total_tasks = _count_restore_tasks(spec.backup_dir)
    completed_tasks = 0
    logger.info(f"Total restore tasks (files): {total_tasks}")

    # Regex for parsing myloader output
    # Matches: "Thread 1 restoring ..." or "** Message: Thread 1 restoring ..."
    re_restoring = re.compile(r"(?:Thread \d+|Message: Thread \d+) restoring (.+)")
    re_finished = re.compile(
        r"(?:Thread \d+|Message: Thread \d+) finished restoring (.+)"
    )

    # Matches verbose output: "** Message: <time>: Thread <id>: restoring <content> from <filename> ..."
    # We capture the filename after "from" until " |" (progress bar) or ". Tables" (status) or end of line.
    re_verbose_restore = re.compile(
        r"Thread \d+: restoring .+ from (.+?)(?: \||\. Tables|$)"
    )

    def _progress_callback(line: str) -> None:
        nonlocal completed_tasks

        filename = None
        is_finished = False

        # Check for verbose output (matches both start/finish in one line effectively)
        # This format is common in newer myloader versions or specific verbosity levels
        match_verbose = re_verbose_restore.search(line)
        if match_verbose:
            raw_filename = match_verbose.group(1).strip()
            # Clean up path if present (e.g. /tmp/.../file.sql) and remove trailing period if caught
            filename = Path(raw_filename).name.rstrip(".")
            is_finished = True

        # Check for file completion (standard output)
        elif match_finish := re_finished.search(line):
            filename = match_finish.group(1).strip()
            is_finished = True

        # Check for file start
        elif match_start := re_restoring.search(line):
            filename = match_start.group(1).strip()
            if progress_callback:
                percent = min(
                    100.0,
                    (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0.0,
                )
                progress_callback(
                    percent,
                    {"status": "started", "file": filename},
                )
            return

        # Fallback for older myloader versions or different output
        elif ("Finished restoring" in line or "Completed" in line) and not is_finished:
            # This might double count if regex matched, but "Finished restoring" usually refers to a table/file
            # In myloader 0.9/0.19, "Thread X finished restoring Y" is the standard line.
            is_finished = True
            parts = line.strip().split()
            filename = parts[-1] if parts else "unknown"

        if is_finished and filename:
            # Only increment if it looks like a file we counted (contains .sql)
            # This filters out "index", "trigger", etc. which cause >100% progress
            if ".sql" in filename:
                completed_tasks += 1

            percent = min(
                100.0, (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
            )

            if progress_callback:
                progress_callback(
                    percent,
                    {"status": "finished", "file": filename},
                )

            # Log every 10%
            if completed_tasks % max(1, total_tasks // 10) == 0:
                logger.info(
                    f"Restore progress: {percent:.1f}% "
                    f"({completed_tasks}/{total_tasks})"
                )

    try:
        result: CommandResult = run_command_streaming(
            command,
            line_callback=_progress_callback,
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
            myloader_result = run_myloader(
                spec.myloader_spec,
                timeout=spec.timeout,
                progress_callback=spec.progress_callback,
            )
        result["myloader"] = myloader_result

        # Helper to emit events if callback provided
        def _emit_event(event_type: str, detail: dict[str, Any]) -> None:
            if spec.event_callback:
                spec.event_callback(event_type, detail)

        # 3. Post-SQL execution (if scripts exist in script_dir)
        logger.info(
            {
                "phase": "post_sql",
                "job_id": job.id,
                "staging_db": staging_result.staging_db,
            }
        )
        _emit_event("post_sql_started", {"staging_db": staging_result.staging_db})
        post_sql_started_at = datetime.now(UTC)
        with time_operation(
            "post_sql_duration_seconds",
            MetricLabels(job_id=job.id, target=job.target, phase="post_sql"),
        ):
            post_sql_result = execute_post_sql(spec.post_sql_conn)
        post_sql_duration = (datetime.now(UTC) - post_sql_started_at).total_seconds()
        result["post_sql"] = post_sql_result
        result["post_sql_duration_seconds"] = post_sql_duration
        _emit_event("post_sql_complete", {
            "scripts_executed": len(post_sql_result.scripts_executed),
            "duration_seconds": round(post_sql_duration, 2),
        })

        restore_completed_at = datetime.now(UTC)

        # 4. Metadata table injection
        logger.info(
            {
                "phase": "metadata",
                "job_id": job.id,
                "staging_db": staging_result.staging_db,
            }
        )
        _emit_event("metadata_started", {"staging_db": staging_result.staging_db})
        metadata_started_at = datetime.now(UTC)
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
        metadata_duration = (datetime.now(UTC) - metadata_started_at).total_seconds()
        result["metadata"] = "injected"
        result["metadata_duration_seconds"] = metadata_duration
        _emit_event("metadata_complete", {"duration_seconds": round(metadata_duration, 2)})

        # 5. Atomic rename staging → target
        logger.info(
            {
                "phase": "atomic_rename",
                "job_id": job.id,
                "staging_db": staging_result.staging_db,
                "target_db": job.target,
            }
        )
        _emit_event("atomic_rename_started", {
            "staging_db": staging_result.staging_db,
            "target_db": job.target,
        })
        rename_started_at = datetime.now(UTC)
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
        rename_duration = (datetime.now(UTC) - rename_started_at).total_seconds()
        result["atomic_rename"] = "complete"
        result["atomic_rename_duration_seconds"] = rename_duration
        _emit_event("atomic_rename_complete", {
            "target_db": job.target,
            "duration_seconds": round(rename_duration, 2),
        })

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
