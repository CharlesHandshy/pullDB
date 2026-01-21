"""Post-restore table analysis utilities.

Runs ANALYZE TABLE after restore to update index statistics for the query
optimizer. This is critical for accurate query plans on freshly restored tables.

myloader disables keys during load, and after re-enabling them the statistics
are stale. Running ANALYZE TABLE ensures the optimizer has accurate cardinality
data.

Uses NO_WRITE_TO_BINLOG to prevent replicating ANALYZE TABLE to slaves
(which may have different data states).

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from pulldb.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = get_logger("pulldb.worker.table_analyzer")


class AnalyzeStatus(Enum):
    """Status of ANALYZE TABLE result."""
    OK = auto()
    TABLE_NOT_FOUND = auto()
    ERROR = auto()
    SKIPPED = auto()


@dataclass
class AnalyzeResult:
    """Result of ANALYZE TABLE for a single table.
    
    Attributes:
        table_name: Full qualified table name (db.table)
        status: Result status
        duration_seconds: Time taken to analyze
        message: MySQL message (if any)
        error: Error message if status is ERROR
    """
    table_name: str
    status: AnalyzeStatus
    duration_seconds: float = 0.0
    message: str = ""
    error: str = ""


@dataclass
class AnalyzeBatchResult:
    """Result of analyzing multiple tables.
    
    Attributes:
        tables: Individual results per table
        total_tables: Number of tables attempted
        successful: Number of tables analyzed successfully
        failed: Number of tables that failed
        total_duration_seconds: Total time for all analyses
        started_at: When batch analysis started
        completed_at: When batch analysis completed
    """
    tables: list[AnalyzeResult] = field(default_factory=list)
    total_tables: int = 0
    successful: int = 0
    failed: int = 0
    total_duration_seconds: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    
    def add_result(self, result: AnalyzeResult) -> None:
        """Add a result and update counters."""
        self.tables.append(result)
        self.total_tables += 1
        if result.status == AnalyzeStatus.OK:
            self.successful += 1
        elif result.status == AnalyzeStatus.ERROR:
            self.failed += 1
        self.total_duration_seconds += result.duration_seconds
    
    def finalize(self) -> None:
        """Mark batch as complete."""
        self.completed_at = datetime.now(UTC)


def analyze_table(
    connection: Any,
    table_name: str,
    *,
    no_write_to_binlog: bool = True,
) -> AnalyzeResult:
    """Run ANALYZE TABLE on a single table.
    
    Args:
        connection: MySQL connection object (must have cursor() method).
        table_name: Full qualified table name (db.table).
        no_write_to_binlog: If True, use NO_WRITE_TO_BINLOG option.
            This prevents the ANALYZE from being logged to binary log
            and replicated to slaves.
    
    Returns:
        AnalyzeResult with status and timing info.
    """
    # Parse db.table format
    parts = table_name.split(".", 1)
    if len(parts) != 2:
        return AnalyzeResult(
            table_name=table_name,
            status=AnalyzeStatus.ERROR,
            error=f"Invalid table name format: {table_name} (expected db.table)",
        )
    
    db_name, tbl_name = parts
    
    # Build query - quote identifiers
    binlog_opt = "NO_WRITE_TO_BINLOG " if no_write_to_binlog else ""
    query = f"ANALYZE {binlog_opt}TABLE `{db_name}`.`{tbl_name}`"
    
    logger.info("analyze_table_start", extra={
        "table": table_name,
        "no_write_to_binlog": no_write_to_binlog,
    })
    
    start_time = time.monotonic()
    
    try:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(query)
            results = cursor.fetchall()
        finally:
            cursor.close()
        
        duration = time.monotonic() - start_time
        
        # ANALYZE TABLE returns result set with status
        # Columns: Table, Op, Msg_type, Msg_text
        status = AnalyzeStatus.OK
        message = ""
        
        if results:
            row = results[0]
            msg_type = row.get("Msg_type", "").lower()
            msg_text = row.get("Msg_text", "")
            message = msg_text
            
            if msg_type == "error":
                status = AnalyzeStatus.ERROR
            elif msg_type == "warning":
                # Warnings are still OK but log them
                logger.warning("analyze_table_warning", extra={
                    "table": table_name,
                    "message": msg_text,
                })
            elif "doesn't exist" in msg_text.lower():
                status = AnalyzeStatus.TABLE_NOT_FOUND
        
        logger.info("analyze_table_complete", extra={
            "table": table_name,
            "duration_seconds": duration,
            "status": status.name,
        })
        
        return AnalyzeResult(
            table_name=table_name,
            status=status,
            duration_seconds=duration,
            message=message,
        )
    
    except Exception as e:
        duration = time.monotonic() - start_time
        logger.error("analyze_table_error", extra={
            "table": table_name,
            "error": str(e),
            "duration_seconds": duration,
        })
        return AnalyzeResult(
            table_name=table_name,
            status=AnalyzeStatus.ERROR,
            duration_seconds=duration,
            error=str(e),
        )


def analyze_tables(
    connection: Any,
    table_names: Sequence[str],
    *,
    no_write_to_binlog: bool = True,
    stop_on_error: bool = False,
) -> AnalyzeBatchResult:
    """Run ANALYZE TABLE on multiple tables.
    
    Args:
        connection: MySQL connection object.
        table_names: List of full qualified table names (db.table).
        no_write_to_binlog: If True, use NO_WRITE_TO_BINLOG option.
        stop_on_error: If True, stop on first error.
    
    Returns:
        AnalyzeBatchResult with all results and summary.
    """
    batch_result = AnalyzeBatchResult()
    
    logger.info("analyze_batch_start", extra={
        "total_tables": len(table_names),
        "no_write_to_binlog": no_write_to_binlog,
    })
    
    for table_name in table_names:
        result = analyze_table(
            connection,
            table_name,
            no_write_to_binlog=no_write_to_binlog,
        )
        batch_result.add_result(result)
        
        if stop_on_error and result.status == AnalyzeStatus.ERROR:
            logger.warning("analyze_batch_stopped_on_error", extra={
                "table": table_name,
                "error": result.error,
            })
            break
    
    batch_result.finalize()
    
    logger.info("analyze_batch_complete", extra={
        "total_tables": batch_result.total_tables,
        "successful": batch_result.successful,
        "failed": batch_result.failed,
        "total_duration_seconds": batch_result.total_duration_seconds,
    })
    
    return batch_result


def analyze_database_tables(
    connection: Any,
    database: str,
    *,
    no_write_to_binlog: bool = True,
    exclude_patterns: Sequence[str] | None = None,
) -> AnalyzeBatchResult:
    """Run ANALYZE TABLE on all tables in a database.
    
    Args:
        connection: MySQL connection object.
        database: Database name.
        no_write_to_binlog: If True, use NO_WRITE_TO_BINLOG option.
        exclude_patterns: Table name patterns to exclude (SQL LIKE patterns).
    
    Returns:
        AnalyzeBatchResult with all results and summary.
    """
    logger.info("analyze_database_start", extra={
        "database": database,
        "exclude_patterns": exclude_patterns or [],
    })
    
    # Get list of tables in database
    try:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SHOW TABLES FROM `%s`" % database)
            rows = cursor.fetchall()
        finally:
            cursor.close()
        
        # Result is dict with column named "Tables_in_<database>"
        column_name = f"Tables_in_{database}"
        tables = [row.get(column_name, row.get(list(row.keys())[0])) for row in rows]
    
    except Exception as e:
        logger.error("analyze_database_list_tables_error", extra={
            "database": database,
            "error": str(e),
        })
        result = AnalyzeBatchResult()
        result.finalize()
        return result
    
    # Filter out excluded tables
    if exclude_patterns:
        import fnmatch
        filtered_tables = []
        for table in tables:
            excluded = False
            for pattern in exclude_patterns:
                # Convert SQL LIKE to fnmatch pattern
                fn_pattern = pattern.replace("%", "*").replace("_", "?")
                if fnmatch.fnmatch(table, fn_pattern):
                    excluded = True
                    break
            if not excluded:
                filtered_tables.append(table)
        tables = filtered_tables
    
    # Build full qualified names
    table_names = [f"{database}.{table}" for table in tables]
    
    logger.info("analyze_database_tables_found", extra={
        "database": database,
        "table_count": len(table_names),
    })
    
    return analyze_tables(
        connection,
        table_names,
        no_write_to_binlog=no_write_to_binlog,
    )
