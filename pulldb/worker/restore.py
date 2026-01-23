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
from pulldb.worker.backup_metadata import (
    get_backup_metadata,
)
from pulldb.worker.early_analyze import EarlyAnalyzeStats, EarlyAnalyzeWorker
from pulldb.worker.metadata import (
    MetadataConnectionSpec,
    MetadataSpec,
    inject_metadata_table,
)
from pulldb.worker.post_sql import PostSQLConnectionSpec, execute_post_sql
from pulldb.worker.processlist_monitor import (
    ProcesslistMonitor,
    ProcesslistMonitorConfig,
    ProcesslistSnapshot,
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
        early_analyze_timeout: Timeout for early analyze worker (default 300s).
    """

    job: Job
    backup_filename: str
    staging_conn: StagingConnectionSpec
    post_sql_conn: PostSQLConnectionSpec
    myloader_spec: MyLoaderSpec
    timeout: float | None = None
    early_analyze_timeout: float = 300.0  # 5 minute default
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
            logger.debug(
                "Failed to read metadata file %s", metadata_path, exc_info=True
            )

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
    early_analyze_worker: EarlyAnalyzeWorker | None = None,
) -> MyLoaderResult:
    """Execute myloader and return structured result.

    Uses RestoreProgressTracker for unified, row-based progress tracking.
    Progress is primarily derived from processlist polling (real-time per-table
    progress), with myloader stdout confirming completions.

    Args:
        spec: Myloader command specification.
        timeout: Optional timeout in seconds.
        progress_callback: Called with (percent, detail_dict) for progress updates.
        processlist_monitor: Optional monitor for per-table progress from MySQL processlist.
        early_analyze_worker: Optional worker to receive active thread updates.
        abort_check: Optional callback that returns True if job should abort.
        event_callback: Optional callback for metadata synthesis events.

    Raises:
        MyLoaderError: On non-zero exit, startup failure, or timeout.
        CommandAbortedError: If abort_check returns True during execution.
    """
    from pulldb.worker.restore_progress import create_progress_tracker

    logger = logging.getLogger("pulldb.restore.myloader")
    command = _build_command(spec)

    # Detect version
    version_info = _detect_backup_version(spec.backup_dir)
    logger.info(f"Detected backup version info: {version_info}")

    # Get backup metadata (ensures compatibility + extracts row counts)
    # This emits metadata_synthesis_started/complete events if callback provided
    backup_meta = get_backup_metadata(spec.backup_dir, event_callback=event_callback)
    logger.info(
        f"Backup metadata: format={backup_meta.format.value}, "
        f"{len(backup_meta.tables)} tables, {backup_meta.total_rows:,} total rows"
    )

    # Create progress tracker - single source of truth
    tracker = create_progress_tracker(
        table_metadata=backup_meta.tables,
        progress_callback=progress_callback,
        event_callback=event_callback,
    )

    # Connect early analyze worker to tracker for UI updates
    if early_analyze_worker is not None:
        early_analyze_worker.set_progress_tracker(tracker)

    # Connect processlist monitor to tracker
    if processlist_monitor is not None:
        # Store original callback and chain through tracker
        original_pl_callback = processlist_monitor._progress_callback

        def tracker_processlist_callback(snapshot: ProcesslistSnapshot) -> None:
            tracker.update_from_processlist(snapshot)
            # Update early analyze worker with active thread count
            if early_analyze_worker:
                early_analyze_worker.update_active_threads(snapshot.active_threads)
            # Also call original if set
            if original_pl_callback:
                original_pl_callback(snapshot)

        processlist_monitor._progress_callback = tracker_processlist_callback

    # Line callback feeds tracker
    def _line_callback(line: str) -> None:
        """Parse myloader output line and update tracker."""
        tracker.update_from_myloader_line(line)

    try:
        result: CommandResult = run_command_streaming(
            command,
            line_callback=_line_callback,
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

    # Finalize tracker - marks all tables complete
    tracker.finalize()

    return MyLoaderResult(
        command=result.command,
        exit_code=result.exit_code,
        started_at=result.started_at,
        completed_at=result.completed_at,
        duration_seconds=result.duration_seconds,
        stdout=result.stdout[-STDOUT_TAIL_LIMIT:],
        stderr=result.stderr[-STDERR_TAIL_LIMIT:],
        table_count=len(backup_meta.tables),
        total_rows=backup_meta.total_rows,
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
        _emit_event(
            "staging_cleanup_started",
            {
                "target": job.target,
                "job_id": job.id,
            },
        )
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
        staging_cleanup_duration = (
            datetime.now(UTC) - staging_cleanup_start
        ).total_seconds()
        emit_counter(
            "staging_cleanup_total",
            labels=MetricLabels(job_id=job.id, target=job.target, phase="staging"),
        )
        result["staging"] = staging_result
        result["staging_cleanup_duration_seconds"] = staging_cleanup_duration
        _emit_event(
            "staging_cleanup_complete",
            {
                "staging_db": staging_result.staging_db,
                "orphans_dropped": staging_result.orphans_dropped,
                "orphans_count": len(staging_result.orphans_dropped),
                "duration_seconds": round(staging_cleanup_duration, 2),
            },
        )

        # 2. Myloader restore to staging database
        logger.info(
            {
                "phase": "myloader",
                "job_id": job.id,
                "staging_db": staging_result.staging_db,
            }
        )

        # Start processlist monitor for per-table progress tracking
        # The RestoreProgressTracker in run_myloader will connect to this monitor
        processlist_monitor: ProcesslistMonitor | None = None

        try:
            monitor_config = ProcesslistMonitorConfig(
                mysql_host=spec.staging_conn.mysql_host,
                mysql_port=spec.staging_conn.mysql_port,
                mysql_user=spec.staging_conn.mysql_user,
                mysql_password=spec.staging_conn.mysql_password,
                staging_db=staging_result.staging_db,
                poll_interval_seconds=2.0,
            )
            processlist_monitor = ProcesslistMonitor(monitor_config)
            processlist_monitor.start()
            logger.info(f"Started processlist monitor for {staging_result.staging_db}")
        except Exception as e:
            # Non-fatal: continue without processlist monitoring
            logger.warning(f"Failed to start processlist monitor: {e}")
            processlist_monitor = None

        _emit_event(
            "myloader_started",
            {
                "staging_db": staging_result.staging_db,
                "backup_dir": str(spec.myloader_spec.backup_dir),
            },
        )

        # Start early analyze worker for ANALYZE TABLE as tables complete
        early_analyze_worker: EarlyAnalyzeWorker | None = None
        try:

            def _create_analyze_connection() -> Any:
                """Factory for MySQL connections for analyze worker."""
                import mysql.connector

                return mysql.connector.connect(
                    host=spec.staging_conn.mysql_host,
                    port=spec.staging_conn.mysql_port,
                    user=spec.staging_conn.mysql_user,
                    password=spec.staging_conn.mysql_password,
                    database=staging_result.staging_db,
                    connect_timeout=10,
                )

            # Extract thread count from myloader extra_args (--threads=N)
            max_threads = 4  # default
            for arg in spec.myloader_spec.extra_args:
                if arg.startswith("--threads="):
                    try:
                        max_threads = int(arg.split("=")[1])
                    except (ValueError, IndexError):
                        pass
                    break

            early_analyze_worker = EarlyAnalyzeWorker(
                connection_factory=_create_analyze_connection,
                staging_db=staging_result.staging_db,
                max_threads=max_threads,
                event_callback=_emit_event,
            )
            early_analyze_worker.start()
            logger.info(f"Started early analyze worker for {staging_result.staging_db}")
        except Exception as e:
            # Non-fatal: continue without early analysis
            logger.warning(f"Failed to start early analyze worker: {e}")
            early_analyze_worker = None

        # Create wrapped event callback that queues tables for analysis
        def _event_with_analyze(event_type: str, data: dict) -> None:
            """Event callback that also queues completed tables for analysis."""
            _emit_event(event_type, data)
            # Queue table for analysis when restore completes
            if event_type == "table_restore_complete" and early_analyze_worker:
                table_name = data.get("table")
                if table_name:
                    early_analyze_worker.queue_table(table_name)

        try:
            with time_operation(
                "myloader_duration_seconds",
                MetricLabels(job_id=job.id, target=job.target, phase="myloader"),
            ):
                myloader_result = run_myloader(
                    spec.myloader_spec,
                    timeout=spec.timeout,
                    progress_callback=spec.progress_callback,
                    processlist_monitor=processlist_monitor,
                    abort_check=spec.abort_check,
                    event_callback=_event_with_analyze,
                    early_analyze_worker=early_analyze_worker,
                )
        finally:
            # Always stop the monitor - no final_poll needed since tracker handles finalization
            if processlist_monitor:
                processlist_monitor.stop(final_poll=False)
                logger.info("Stopped processlist monitor")

        # Wait for early analysis to complete after myloader finishes
        early_analyze_stats: EarlyAnalyzeStats | None = None
        if early_analyze_worker:
            try:
                # Signal that myloader is done - analyzer can use full thread capacity
                early_analyze_worker.notify_myloader_complete()
                logger.info("Waiting for early analyze worker to complete...")
                # Wait for all queued tables to be analyzed (with timeout)
                early_analyze_stats = early_analyze_worker.wait_for_completion(
                    timeout=spec.early_analyze_timeout
                )
                early_analyze_worker.stop()
                logger.info(
                    f"Early analyze complete: {early_analyze_stats.tables_analyzed} analyzed, "
                    f"{early_analyze_stats.tables_failed} failed"
                )
                result["early_analyze"] = {
                    "tables_analyzed": early_analyze_stats.tables_analyzed,
                    "tables_failed": early_analyze_stats.tables_failed,
                    "total_duration_seconds": round(
                        early_analyze_stats.total_duration_seconds, 2
                    ),
                }
            except Exception as e:
                logger.warning(f"Early analyze worker error: {e}")
                if early_analyze_worker:
                    early_analyze_worker.stop()
                result["early_analyze"] = {"error": str(e)}

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
            post_sql_result = execute_post_sql(
                spec.post_sql_conn, event_callback=_emit_event
            )
        post_sql_duration = (datetime.now(UTC) - post_sql_started_at).total_seconds()
        result["post_sql"] = post_sql_result
        result["post_sql_duration_seconds"] = post_sql_duration
        _emit_event(
            "post_sql_complete",
            {
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
            },
        )

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
        _emit_event(
            "metadata_complete", {"duration_seconds": round(metadata_duration, 2)}
        )

        # 5. Atomic rename staging → target
        logger.info(
            {
                "phase": "atomic_rename",
                "job_id": job.id,
                "staging_db": staging_result.staging_db,
                "target_db": job.target,
            }
        )
        _emit_event(
            "atomic_rename_started",
            {
                "staging_db": staging_result.staging_db,
                "target_db": job.target,
            },
        )
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
            atomic_rename_staging_to_target(
                rename_conn, rename_spec, event_callback=_emit_event
            )
        rename_duration = (datetime.now(UTC) - rename_started_at).total_seconds()
        result["atomic_rename"] = "complete"
        result["atomic_rename_duration_seconds"] = rename_duration
        _emit_event(
            "atomic_rename_complete",
            {
                "target_db": job.target,
                "duration_seconds": round(rename_duration, 2),
            },
        )

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
