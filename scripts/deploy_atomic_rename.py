"""Deployment script for pulldb_atomic_rename stored procedure.

Reads `docs/atomic_rename_procedure.sql` and applies it to one or more MySQL
hosts. FAIL HARD semantics: any failure aborts with actionable diagnostics.

Usage:
    python3 scripts/deploy_atomic_rename.py --host db1.example.com \
        --user root --password secret

    python3 scripts/deploy_atomic_rename.py \
        --hosts db1.example.com,db2.example.com --user admin --password pw

Options:
    --sql-file    Path to procedure SQL (default: docs/atomic_rename_procedure.sql)
    --host        Single host (mutually exclusive with --hosts)
    --hosts       Comma-separated list of hosts
    --port        MySQL port (default: 3306)
    --user        MySQL user with CREATE/DROP/ALTER/PROCEDURE privileges
    --password    Password for MySQL user (or set MYSQL_PWD env var)
    --dry-run     Only validates input & shows target hosts (no changes)

Exit Codes:
    0 on success for all hosts
    1 on validation or deployment failure
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import mysql.connector


PROCEDURE_NAME = "pulldb_atomic_rename"
PREVIEW_PROCEDURE_NAME = "pulldb_atomic_rename_preview"
EXPECTED_VERSION = "1.2.0"


@runtime_checkable
class MySQLCursorProtocol(Protocol):  # pragma: no cover - structural only
    """Minimal cursor protocol supporting execute + close."""

    def execute(self, __query: str) -> Any:  # pragma: no cover - signature only
        """Execute a SQL statement."""
        ...

    def close(self) -> None:  # pragma: no cover - signature only
        """Close the cursor (best-effort)."""
        ...


@runtime_checkable
class MySQLConnectionProtocol(Protocol):  # pragma: no cover - structural only
    """Minimal connection protocol supporting cursor + close."""

    def cursor(self) -> MySQLCursorProtocol:  # pragma: no cover - signature only
        """Return a new cursor object."""
        ...

    def close(self) -> None:  # pragma: no cover - signature only
        """Close the connection (best-effort)."""
        ...


def _fail(goal: str, problem: str, root_cause: str, solutions: Sequence[str]) -> None:
    lines = [
        f"Goal: {goal}",
        f"Problem: {problem}",
        f"Root Cause: {root_cause}",
        "Solutions:",
    ]
    for i, s in enumerate(solutions, 1):
        lines.append(f"  {i}. {s}")
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments containing sql-file, host(s), port,
            user, password, and dry-run flag.
    """
    parser = argparse.ArgumentParser(
        description="Deploy pulldb atomic rename stored procedure"
    )
    parser.add_argument(
        "--sql-file",
        default="docs/atomic_rename_procedure.sql",
        help="Path to atomic rename procedure SQL file",
    )
    parser.add_argument("--host", help="Single MySQL host", default=None)
    parser.add_argument(
        "--hosts", help="Comma-separated list of MySQL hosts", default=None
    )
    parser.add_argument("--port", type=int, default=3306, help="MySQL port")
    parser.add_argument(
        "--user", required=True, help="MySQL user with required privileges"
    )
    parser.add_argument(
        "--password", required=True, help="MySQL user password (avoid shells history)"
    )
    parser.add_argument(
        "--database", default="pulldb_service", help="Database to deploy procedure into"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate only; no deployment"
    )
    parser.add_argument(
        "--deploy-preview", action="store_true", help="Also deploy preview procedure"
    )
    parser.add_argument(
        "--skip-version-check",
        action="store_true",
        help="Skip validation that existing procedure version matches expected",
    )
    return parser.parse_args()


def load_sql(path: Path) -> str:
    """Read SQL file contents.

    Args:
        path: Path to the SQL file.

    Returns:
        Raw SQL file content as a string.

    Raises:
        SystemExit: When file does not exist (FAIL HARD protocol).
    """
    if not path.exists():
        _fail(
            goal="Load atomic rename SQL file",
            problem=f"SQL file '{path}' not found",
            root_cause="Path does not exist",
            solutions=["Provide correct --sql-file path", "Run from repo root"],
        )
    return path.read_text(encoding="utf-8")


def deploy_to_host(
    host: str, port: int, user: str, password: str, database: str, sql: str
) -> None:
    """Deploy the atomic rename stored procedure to a single MySQL host.

    Args:
        host: Hostname or IP of MySQL server.
        port: MySQL port (default 3306 typically).
        user: MySQL user with CREATE ROUTINE/DROP/ALTER privileges.
        password: Password for the MySQL user.
        database: Database to deploy procedure into.
        sql: Raw SQL contents of the procedure definition file.

    Raises:
        SystemExit: On any failure (connection, drop, create) with FAIL HARD
            diagnostics.
    """
    conn: Any | None = None  # fallback to Any due to mysql-connector types variability
    try:
        try:
            conn = mysql.connector.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                connect_timeout=5,
                autocommit=True,
            )
        except mysql.connector.Error as e:
            _fail(
                goal=f"Connect to MySQL host {host}:{port} db={database}",
                problem="Connection failed",
                root_cause=str(e),
                solutions=[
                    "Verify host/port accessible (firewall/security group)",
                    "Check credentials (user/password correct)",
                    f"Verify database '{database}' exists",
                    "Test with: mysql -h host -u user -p -D database",
                ],
            )
        assert conn is not None
        cursor = conn.cursor()
        try:  # drop existing (primary procedure)
            cursor.execute(f"DROP PROCEDURE IF EXISTS {PROCEDURE_NAME}")
        except mysql.connector.Error as e:
            _fail(
                goal="Drop existing procedure (idempotent step)",
                problem="DROP PROCEDURE failed",
                root_cause=str(e),
                solutions=[
                    "Verify user has DROP privilege",
                    "Check if procedure name differs (schema)",
                ],
            )
        # Attempt dropping preview (ignore errors if it does not exist)
        with contextlib.suppress(mysql.connector.Error):
            cursor.execute(f"DROP PROCEDURE IF EXISTS {PREVIEW_PROCEDURE_NAME}")
        try:  # create procedure
            # Parse and execute statements separated by $$
            # We assume the file uses DELIMITER $$ for the procedures

            # First, remove the DELIMITER lines to avoid confusion
            # We keep the content, just remove the delimiter commands
            clean_sql = sql.replace("DELIMITER $$", "").replace("DELIMITER ;", "")

            # Now split by $$
            statements = clean_sql.split("$$")

            for stmt in statements:
                stmt = stmt.strip()
                if not stmt:
                    continue

                # Skip comments-only blocks or empty blocks
                # (Simple heuristic: if it doesn't start with DROP or CREATE, skip it)
                # But comments might precede DROP/CREATE.
                # Let's just try to execute it if it has content.
                # But we should probably strip leading comments to check.

                # Actually, mysql-connector might handle comments fine.
                # But let's be safe and skip if it's just comments.
                lines = stmt.splitlines()
                effective_lines = [l for l in lines if not l.strip().startswith("--")]
                if not effective_lines:
                    continue

                # Reconstruct statement without leading/trailing whitespace
                # We keep internal comments

                try:
                    cursor.execute(stmt)
                    # Consume results to avoid "Commands out of sync"
                    # Some statements (like DROP) might return results or warnings
                    while cursor.nextset():
                        pass
                except mysql.connector.Error as e:
                    _fail(
                        goal="Execute SQL statement",
                        problem="Statement execution failed",
                        root_cause=str(e) + f"\nStatement start: {stmt[:100]}...",
                        solutions=[
                            "Inspect SQL file for syntax errors",
                            "Check MySQL version compatibility",
                            "Verify CREATE ROUTINE privilege",
                        ],
                    )
        except mysql.connector.Error as e:
            _fail(
                goal="Create atomic rename procedure",
                problem="Procedure creation failed",
                root_cause=str(e),
                solutions=[
                    "Inspect SQL file for syntax errors",
                    "Check MySQL version compatibility",
                    "Verify CREATE ROUTINE privilege",
                ],
            )
        finally:
            with contextlib.suppress(Exception):
                cursor.close()
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


def main() -> int:
    """Entrypoint orchestrating argument parsing and deployment loop.

    Returns:
        Process exit status code (0 success, 1 already handled by _fail).
    """
    args = parse_args()

    def resolve_hosts(a: argparse.Namespace) -> list[str]:
        if bool(a.host) == bool(a.hosts):
            _fail(
                goal="Validate host selection",
                problem="Provide either --host or --hosts (mutually exclusive)",
                root_cause="Ambiguous target host configuration",
                solutions=[
                    "Use --host for single host",
                    "Use --hosts for multiple",
                ],
            )
        if a.host:
            return [a.host]
        hosts_list = [h.strip() for h in a.hosts.split(",") if h.strip()]
        if not hosts_list:
            _fail(
                goal="Parse hosts list",
                problem="--hosts produced empty host list",
                root_cause="Comma-separated list was empty or whitespace",
                solutions=[
                    "Provide at least one hostname",
                    "Use --host instead",
                ],
            )
        return hosts_list

    hosts = resolve_hosts(args)

    sql_path = Path(args.sql_file)
    raw_sql = load_sql(sql_path)

    # Version check: ensure expected version comment present
    def validate_version(sql: str) -> None:
        if args.skip_version_check:
            return
        if f"Version: {EXPECTED_VERSION}" not in sql:
            _fail(
                goal="Validate procedure version",
                problem="Expected version comment not found in SQL file",
                root_cause=f"Missing 'Version: {EXPECTED_VERSION}' header",
                solutions=[
                    "Ensure you are deploying the correct procedure version",
                    "Add version header comment to SQL file",
                    "Use --skip-version-check to bypass (not recommended)",
                ],
            )

    validate_version(raw_sql)

    # If preview deployment disabled, strip preview procedure blocks to avoid creation
    sql: str
    if not args.deploy_preview:
        # Strip both DROP + CREATE blocks for preview procedure while retaining
        # the primary procedure body. We detect start at DROP statement and end
        # at matching DELIMITER ; following its CREATE body.
        lines = raw_sql.splitlines()
        filtered: list[str] = []
        skipping = False
        preview_start_phrases = (
            "DROP PROCEDURE IF EXISTS pulldb_atomic_rename_preview",
            "CREATE PROCEDURE pulldb_atomic_rename_preview",
        )
        for line in lines:
            stripped = line.strip()
            if not skipping and any(
                stripped.startswith(p) for p in preview_start_phrases
            ):
                skipping = True
                continue
            if skipping:
                if stripped == "DELIMITER ;":
                    skipping = False
                continue
            filtered.append(line)
        sql = "\n".join(filtered)
    else:
        sql = raw_sql

    if args.dry_run:
        print("DRY RUN: would deploy procedure to hosts:")
        for h in hosts:
            print(f"  - {h}:{args.port}")
        print(f"Procedure version expected: {EXPECTED_VERSION}")
        if args.deploy_preview:
            print("Preview procedure will be deployed.")
        else:
            print("Preview procedure will NOT be deployed (use --deploy-preview).")
        return 0

    for host in hosts:
        print(
            f"Deploying {PROCEDURE_NAME} to {host}:{args.port} "
            f"(version {EXPECTED_VERSION}) ...",
            end="",
        )
        deploy_to_host(host, args.port, args.user, args.password, args.database, sql)
        print(" OK")

    print("Deployment complete for all hosts.")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry
    sys.exit(main())
