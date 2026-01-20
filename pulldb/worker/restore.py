"""Myloader execution wrapper.

Translates a :class:`MyLoaderSpec` into a concrete myloader command,
invokes it via :func:`infra.exec.run_command`, and maps failures to
domain `MyLoaderError` exceptions (FAIL HARD semantics).

The wrapper intentionally limits scope to command construction +
error translation. Higher-level workflow orchestration (staging
creation, post-SQL, rename) will reside elsewhere.

HCA Layer: features
"""

from __future__ import annotations

import logging
import re
import threading
import time
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
    CommandAbortedError,
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
from pulldb.worker.backup_metadata import (
    ensure_myloader_compatibility,
    get_backup_metadata,
)
from pulldb.worker.metadata import (
    MetadataConnectionSpec,
    MetadataSpec,
    inject_metadata_table,
)
from pulldb.worker.post_sql import PostSQLConnectionSpec, execute_post_sql
from pulldb.worker.processlist_monitor import (
    ProcesslistMonitor,
    ProcesslistMonitorConfig,
)
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
    abort_check: Callable[[], bool] | None = None


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
    abort_check: Callable[[], bool] | None = None,
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

    Returns:
        RestoreWorkflowSpec ready for execution.

    Raises:
        ValueError: If job.staging_name is not set.
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
        abort_check=abort_check,
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
            # Graceful degradation: if metadata unreadable, continue to fallback
            logger.debug("Failed to read metadata file %s", metadata_path, exc_info=True)

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
    processlist_monitor: ProcesslistMonitor | None = None,
    abort_check: Callable[[], bool] | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> MyLoaderResult:
    """Execute myloader and return structured result.

    Args:
        spec: Myloader command specification.
        timeout: Optional timeout in seconds.
        progress_callback: Called with (percent, detail_dict) for progress updates.
        processlist_monitor: Optional monitor for per-table progress from MySQL processlist.
        abort_check: Optional callback that returns True if job should abort.
        event_callback: Optional callback for metadata synthesis events.

    Raises:
        MyLoaderError: On non-zero exit, startup failure, or timeout.
        CommandAbortedError: If abort_check returns True during execution.
    """
    logger = logging.getLogger("pulldb.restore.myloader")
    command = _build_command(spec)

    # Detect version
    version_info = _detect_backup_version(spec.backup_dir)
    logger.info(f"Detected backup version info: {version_info}")

    # Get backup metadata (ensures compatibility + extracts row counts)
    # This emits metadata_synthesis_started/complete events if callback provided
    backup_meta = get_backup_metadata(spec.backup_dir, event_callback=event_callback)
    total_rows = backup_meta.total_rows
    logger.info(
        f"Backup metadata: format={backup_meta.format.value}, "
        f"{len(backup_meta.tables)} tables, {total_rows:,} total rows"
    )

    # Count tasks for file-based progress
    total_tasks = _count_restore_tasks(spec.backup_dir)
    completed_tasks = 0
    logger.info(f"Total restore tasks (files): {total_tasks}")

    # Track rows for throughput calculation
    restore_start_time = time.monotonic()
    rows_restored = 0  # Estimated from file completions

    # Build table -> row count mapping for row-based estimates
    table_row_counts: dict[str, int] = {}
    for t in backup_meta.tables:
        table_row_counts[t.table] = t.rows

    # Regex for parsing myloader output
    re_restoring = re.compile(r"(?:Thread \d+|Message: Thread \d+) restoring (.+)")
    re_finished = re.compile(
        r"(?:Thread \d+|Message: Thread \d+) finished restoring (.+)"
    )
    re_verbose_restore = re.compile(
        r"Thread \d+: restoring .+ from (.+?)(?: \||\. Tables|$)"
    )

    def _progress_callback(line: str) -> None:
        nonlocal completed_tasks, rows_restored

        filename = None
        is_finished = False

        # Check for verbose output
        match_verbose = re_verbose_restore.search(line)
        if match_verbose:
            raw_filename = match_verbose.group(1).strip()
            filename = Path(raw_filename).name.rstrip(".")
            is_finished = True
        elif match_finish := re_finished.search(line):
            filename = match_finish.group(1).strip()
            is_finished = True
        elif match_start := re_restoring.search(line):
            filename = match_start.group(1).strip()
            if progress_callback:
                percent = min(
                    100.0,
                    (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0.0,
                )
                # Get processlist snapshot for per-table progress
                tables_progress = {}
                active_threads = 0
                if processlist_monitor:
                    snapshot = processlist_monitor.get_snapshot()
                    if snapshot:
                        active_threads = snapshot.active_threads
                        for tbl_name, tbl_prog in snapshot.tables.items():
                            tables_progress[tbl_name] = {
                                "percent_complete": tbl_prog.percent_complete
                            }
                progress_callback(
                    percent,
                    {
                        "status": "started",
                        "file": filename,
                        "active_threads": active_threads,
                        "tables": tables_progress,
                    },
                )
            return
        elif ("Finished restoring" in line or "Completed" in line) and not is_finished:
            is_finished = True
            parts = line.strip().split()
            filename = parts[-1] if parts else "unknown"

        if is_finished and filename:
            if ".sql" in filename:
                completed_tasks += 1
                # Estimate rows restored from filename (table.sql -> table row count)
                # Extract table name from filename like "database.table.00000.sql.gz"
                parts = Path(filename).stem.replace(".sql", "").split(".")
                if len(parts) >= 2:
                    table_name = parts[1] if parts[0] != parts[1] else parts[0]
                    rows_restored += table_row_counts.get(table_name, 0)

            percent = min(
                100.0, (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
            )

            if progress_callback:
                # Calculate throughput and ETA
                elapsed = time.monotonic() - restore_start_time
                rows_per_second = int(rows_restored / elapsed) if elapsed > 0 else 0
                remaining_rows = total_rows - rows_restored
                eta_seconds = int(remaining_rows / rows_per_second) if rows_per_second > 0 else None

                # Get processlist snapshot for per-table progress
                tables_progress = {}
                active_threads = 0
                if processlist_monitor:
                    snapshot = processlist_monitor.get_snapshot()
                    if snapshot:
                        active_threads = snapshot.active_threads
                        for tbl_name, tbl_prog in snapshot.tables.items():
                            tables_progress[tbl_name] = {
                                "percent_complete": tbl_prog.percent_complete
                            }

                progress_callback(
                    percent,
                    {
                        "status": "finished",
                        "file": filename,
                        "rows_restored": rows_restored,
                        "total_rows": total_rows,
                        "rows_per_second": rows_per_second,
                        "eta_seconds": eta_seconds,
                        "active_threads": active_threads,
                        "tables": tables_progress,
                    },
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
            abort_check=abort_check,
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

    # Helper to emit events if callback provided
    def _emit_event(event_type: str, detail: dict[str, Any]) -> None:
        if spec.event_callback:
            spec.event_callback(event_type, detail)

    try:
        # 1. Staging lifecycle: cleanup orphaned staging databases
        logger.info(
            {
                "phase": "staging",
                "job_id": job.id,
                "target": job.target,
            }
        )
        _emit_event("staging_cleanup_started", {
            "target": job.target,
            "job_id": job.id,
        })
        staging_cleanup_start = datetime.now(UTC)
        with time_operation(
            "staging_cleanup_duration_seconds",
            MetricLabels(job_id=job.id, target=job.target, phase="staging"),
        ):
            staging_result = cleanup_orphaned_staging(
                spec.staging_conn,
                job.target,
                job.id,
                event_callback=_emit_event,
            )
        staging_cleanup_duration = (datetime.now(UTC) - staging_cleanup_start).total_seconds()
        emit_counter(
            "staging_cleanup_total",
            labels=MetricLabels(job_id=job.id, target=job.target, phase="staging"),
        )
        result["staging"] = staging_result
        result["staging_cleanup_duration_seconds"] = staging_cleanup_duration
        _emit_event("staging_cleanup_complete", {
            "staging_db": staging_result.staging_db,
            "orphans_dropped": staging_result.orphans_dropped,
            "orphans_count": len(staging_result.orphans_dropped),
            "duration_seconds": round(staging_cleanup_duration, 2),
        })

        # 2. Myloader restore to staging database
        logger.info(
            {
                "phase": "myloader",
                "job_id": job.id,
                "staging_db": staging_result.staging_db,
            }
        )

        # Start processlist monitor for per-table progress tracking
        processlist_monitor: ProcesslistMonitor | None = None

        # Shared state for progress updates from processlist monitor thread
        progress_state_lock = threading.Lock()
        progress_state: dict[str, Any] = {"percent": 0.0}

        def on_processlist_poll(snapshot: Any) -> None:
            """Emit progress events on each processlist poll (every 2s)."""
            if not spec.progress_callback:
                return
            # Only emit when there's actual activity
            if snapshot.active_threads == 0 and not snapshot.tables:
                return
            # Build tables progress dict
            tables_progress: dict[str, dict[str, float]] = {}
            for tbl_name, tbl_prog in snapshot.tables.items():
                tables_progress[tbl_name] = {
                    "percent_complete": tbl_prog.percent_complete
                }
            # Get current percent from shared state
            with progress_state_lock:
                current_percent = progress_state.get("percent", 0.0)
            # Emit progress event with processlist data
            spec.progress_callback(
                current_percent,
                {
                    "status": "processlist_update",
                    "active_threads": snapshot.active_threads,
                    "tables": tables_progress,
                },
            )

        try:
            monitor_config = ProcesslistMonitorConfig(
                mysql_host=spec.staging_conn.mysql_host,
                mysql_port=spec.staging_conn.mysql_port,
                mysql_user=spec.staging_conn.mysql_user,
                mysql_password=spec.staging_conn.mysql_password,
                staging_db=staging_result.staging_db,
                poll_interval_seconds=2.0,
            )
            processlist_monitor = ProcesslistMonitor(
                monitor_config, progress_callback=on_processlist_poll
            )
            processlist_monitor.start()
            logger.info(f"Started processlist monitor for {staging_result.staging_db}")
        except Exception as e:
            # Non-fatal: continue without processlist monitoring
            logger.warning(f"Failed to start processlist monitor: {e}")
            processlist_monitor = None

        # Wrap progress callback to update shared state for processlist thread
        def wrapped_progress_callback(
            percent: float, detail: dict[str, Any]
        ) -> None:
            with progress_state_lock:
                progress_state["percent"] = percent
            if spec.progress_callback:
                spec.progress_callback(percent, detail)

        _emit_event("myloader_started", {
            "staging_db": staging_result.staging_db,
            "backup_dir": str(spec.myloader_spec.backup_dir),
        })

        try:
            with time_operation(
                "myloader_duration_seconds",
                MetricLabels(job_id=job.id, target=job.target, phase="myloader"),
            ):
                myloader_result = run_myloader(
                    spec.myloader_spec,
                    timeout=spec.timeout,
                    progress_callback=wrapped_progress_callback,
                    processlist_monitor=processlist_monitor,
                    abort_check=spec.abort_check,
                    event_callback=_emit_event,
                )
        finally:
            # Always stop the monitor
            if processlist_monitor:
                processlist_monitor.stop()
                logger.info("Stopped processlist monitor")

        result["myloader"] = myloader_result

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
            post_sql_result = execute_post_sql(spec.post_sql_conn, event_callback=_emit_event)
        post_sql_duration = (datetime.now(UTC) - post_sql_started_at).total_seconds()
        result["post_sql"] = post_sql_result
        result["post_sql_duration_seconds"] = post_sql_duration
        _emit_event("post_sql_complete", {
            "scripts_executed": len(post_sql_result.scripts_executed),
            "duration_seconds": round(post_sql_duration, 2),
            "scripts": [
                {
                    "name": s.script_name,
                    "duration": round(s.duration_seconds, 3),
                    "rows": s.rows_affected,
                }
                for s in post_sql_result.scripts_executed
            ],
            "source": str(spec.post_sql_conn.script_dir),
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
            owner_user_id=job.owner_user_id,
            owner_user_code=job.owner_user_code,
            owner_username=job.owner_username,
            target_db=job.target,
            backup_filename=spec.backup_filename,
            restore_started_at=restore_started_at,
            restore_completed_at=restore_completed_at,
            custom_target=(job.options_json or {}).get("custom_target_used") == "true",
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
            atomic_rename_staging_to_target(rename_conn, rename_spec, event_callback=_emit_event)
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
