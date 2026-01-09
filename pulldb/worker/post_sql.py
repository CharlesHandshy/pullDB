"""Post-restore SQL execution module.

Executes a sequence of SQL scripts (lexicographically ordered) against the
staging database after a successful myloader restore. Produces a structured
result capturing per-script success, row counts (best-effort), and timing.

Design Principles (FAIL HARD):
- Stop on first failure. Preserve staging database for diagnostics.
- Provide clear diagnostics: failing script name, MySQL error message, and
  list of previously successful scripts.
- Do not mutate scripts or attempt retries.
- Scripts are treated as idempotent within a single run; we do not attempt
  detection of partial application beyond surface error propagation.

Deferred / Future Enhancements:
- Row count diffs & anomaly detection
- Transactional wrapping for smaller batches of scripts
- Parallelizable categorization (not needed for current sanitized scripts)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# ruff: noqa: I001
from datetime import UTC, datetime
from pathlib import Path
from contextlib import suppress
from collections.abc import Sequence

import mysql.connector

from pulldb.domain.errors import PostSQLError
from pulldb.infra.logging import get_logger

SCRIPT_EXTENSION = ".sql"
MAX_SCRIPT_SIZE_BYTES = 2_000_000  # 2 MB safety cap to prevent runaway memory

logger = get_logger("pulldb.worker.post_sql")


@dataclass(slots=True)
class PostSQLScriptResult:
    """Result metadata for a single executed post-restore script."""

    script_name: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    rows_affected: int | None


@dataclass(slots=True)
class PostSQLExecutionResult:
    """Aggregate result of post-restore SQL execution."""

    staging_db: str
    scripts_executed: list[PostSQLScriptResult]
    total_duration_seconds: float


@dataclass(slots=True)
class PostSQLConnectionSpec:
    """Connection + directory specification for post-SQL execution.

    Combines related parameters to keep public function signature small and
    satisfy style limits on argument count.
    """

    staging_db: str
    script_dir: Path
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    connect_timeout: int = 5


def _discover_scripts(directory: Path) -> list[Path]:
    if not directory.exists():
        logger.warning(
            f"Post-SQL directory not found: {directory}. "
            "Skipping post-restore SQL execution."
        )
        return []
    scripts = [
        p for p in directory.iterdir() if p.is_file() and p.suffix == SCRIPT_EXTENSION
    ]
    scripts.sort(key=lambda p: p.name)
    return scripts


def _read_script(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > MAX_SCRIPT_SIZE_BYTES:
        raise ValueError(
            f"Script {path.name} exceeds max size {MAX_SCRIPT_SIZE_BYTES} bytes "
            f"(size={len(data)})"
        )
    return data.decode("utf-8", errors="replace")


def execute_post_sql(
    spec: PostSQLConnectionSpec,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> PostSQLExecutionResult:
    """Execute ordered SQL scripts for a restored staging database.

    Args:
        spec: Connection + script directory specification.
        event_callback: Optional callback for emitting per-script events.
            Called with (event_type, detail_dict) after each script completes.

    Returns:
        PostSQLExecutionResult summarizing executed scripts (empty if none).

    Raises:
        PostSQLError: On first script failure (execution stops immediately).
        ValueError: If a script exceeds MAX_SCRIPT_SIZE_BYTES.
    """
    directory = spec.script_dir
    scripts = _discover_scripts(directory)
    start_total = datetime.now(UTC)
    results: list[PostSQLScriptResult] = []

    logger.info(
        f"Found {len(scripts)} post-SQL scripts to execute",
        extra={
            "staging_db": spec.staging_db,
            "script_dir": str(directory),
            "script_count": len(scripts),
        },
    )

    if not scripts:
        return PostSQLExecutionResult(
            staging_db=spec.staging_db,
            scripts_executed=[],
            total_duration_seconds=0.0,
        )

    try:
        conn = mysql.connector.connect(
            host=spec.mysql_host,
            port=spec.mysql_port,
            user=spec.mysql_user,
            password=spec.mysql_password,
            database=spec.staging_db,
            connection_timeout=spec.connect_timeout,
            autocommit=True,
        )
    except Exception as e:  # pragma: no cover - connection failure path
        raise PostSQLError(
            job_id="unknown",
            script_name="<connection>",
            error_message=str(e),
            completed_scripts=[r.script_name for r in results],
        ) from e

    try:
        cursor = conn.cursor()
        for path in scripts:
            script_sql = _read_script(path)
            started = datetime.now(UTC)
            logger.info(f"Executing script: {path.name}")
            try:
                # Support multiple statements per script
                affected = 0
                cursor.execute(script_sql)
                while True:
                    if cursor.with_rows:  # type: ignore
                        cursor.fetchall()  # Consume any result sets
                    if cursor.rowcount > 0:
                        affected += cursor.rowcount
                    if not cursor.nextset():
                        break
            except Exception as e:  # pragma: no cover - converted to PostSQLError
                logger.error(
                    f"Script failed: {path.name}",
                    extra={"error": str(e)},
                )
                raise PostSQLError(
                    job_id="unknown",
                    script_name=path.name,
                    error_message=str(e),
                    completed_scripts=[r.script_name for r in results],
                ) from e
            completed = datetime.now(UTC)
            duration = (completed - started).total_seconds()
            logger.info(
                f"Script completed: {path.name}",
                extra={"duration_seconds": duration, "rows_affected": affected},
            )
            script_result = PostSQLScriptResult(
                script_name=path.name,
                started_at=started,
                completed_at=completed,
                duration_seconds=duration,
                rows_affected=affected,
            )
            results.append(script_result)

            # Emit per-script event for live progress visibility
            if event_callback:
                event_callback("post_sql_script_complete", {
                    "script_name": path.name,
                    "script_index": len(results),
                    "total_scripts": len(scripts),
                    "duration_seconds": round(duration, 3),
                    "rows_affected": affected,
                    "source": str(directory),
                })
    finally:
        with suppress(Exception):  # pragma: no cover - best effort
            conn.close()

    total_duration = (datetime.now(UTC) - start_total).total_seconds()
    return PostSQLExecutionResult(
        staging_db=spec.staging_db,
        scripts_executed=results,
        total_duration_seconds=total_duration,
    )


__all__: Sequence[str] = [
    "PostSQLConnectionSpec",
    "PostSQLExecutionResult",
    "PostSQLScriptResult",
    "execute_post_sql",
]
