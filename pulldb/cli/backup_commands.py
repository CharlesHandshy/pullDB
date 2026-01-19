"""Backup archive CLI commands for pulldb-admin.

Diagnostic utility for searching and analyzing S3 backup archives
by size, date, and customer.

Commands:
- backups list: List customers with backup statistics (aggregated)
- backups search: Search backups by customer pattern with filters

HCA Layer: pages
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime

import click

from pulldb.domain.services.discovery import format_size
from pulldb.infra.s3 import BACKUP_FILENAME_REGEX, S3Client


# =============================================================================
# Parsing Utilities
# =============================================================================

_SIZE_REGEX = re.compile(r"^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?$", re.IGNORECASE)
_SIZE_MULTIPLIERS = {
    "B": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}


def _parse_size(value: str) -> int:
    """Parse human-readable size string to bytes.

    Accepts formats: "5GB", "500MB", "1TB", "1024KB", "1024" (defaults to B).

    Args:
        value: Size string like "5GB" or "500MB".

    Returns:
        Size in bytes.

    Raises:
        click.BadParameter: If format is invalid.
    """
    match = _SIZE_REGEX.match(value.strip())
    if not match:
        raise click.BadParameter(
            f"Invalid size format: {value}. Use format like '5GB', '500MB', '1TB'."
        )

    number = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    multiplier = _SIZE_MULTIPLIERS.get(unit, 1)

    return int(number * multiplier)


def _parse_date(value: str) -> str:
    """Parse date string to YYYYMMDD format.

    Accepts formats: "YYYYMMDD" or "YYYY-MM-DD".

    Args:
        value: Date string.

    Returns:
        Normalized YYYYMMDD string.

    Raises:
        click.BadParameter: If format is invalid.
    """
    # Remove dashes if present
    normalized = value.replace("-", "")

    if len(normalized) != 8 or not normalized.isdigit():
        raise click.BadParameter(
            f"Invalid date format: {value}. Use YYYYMMDD or YYYY-MM-DD."
        )

    # Validate it's a real date
    try:
        datetime.strptime(normalized, "%Y%m%d")
    except ValueError as exc:
        raise click.BadParameter(f"Invalid date: {value}") from exc

    return normalized


def _extract_date_from_key(key: str) -> str | None:
    """Extract YYYYMMDD date from backup filename.

    Args:
        key: S3 object key.

    Returns:
        YYYYMMDD string or None if not parseable.
    """
    filename = key.rsplit("/", 1)[-1]
    match = BACKUP_FILENAME_REGEX.match(filename)
    if match:
        ts_str = match.group("ts")  # e.g., "2026-01-01T06-18-55Z"
        # Extract date part
        date_part = ts_str[:10].replace("-", "")
        return date_part
    return None


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class CustomerBackupStats:
    """Aggregated backup statistics for a customer."""

    customer: str
    count: int = 0
    total_bytes: int = 0
    min_bytes: int = 0
    max_bytes: int = 0
    oldest_date: str = ""  # YYYYMMDD
    newest_date: str = ""  # YYYYMMDD

    @property
    def avg_bytes(self) -> int:
        """Average backup size in bytes."""
        return self.total_bytes // self.count if self.count > 0 else 0

    @property
    def min_display(self) -> str:
        """Human-readable minimum size."""
        return format_size(self.min_bytes) if self.min_bytes else "-"

    @property
    def avg_display(self) -> str:
        """Human-readable average size."""
        return format_size(self.avg_bytes) if self.avg_bytes else "-"

    @property
    def max_display(self) -> str:
        """Human-readable maximum size."""
        return format_size(self.max_bytes) if self.max_bytes else "-"

    def add_backup(self, size_bytes: int, date_str: str) -> None:
        """Add a backup to the statistics.

        Args:
            size_bytes: Size of the backup in bytes.
            date_str: Date string in YYYYMMDD format.
        """
        self.count += 1
        self.total_bytes += size_bytes

        if self.min_bytes == 0 or size_bytes < self.min_bytes:
            self.min_bytes = size_bytes
        if size_bytes > self.max_bytes:
            self.max_bytes = size_bytes

        if date_str:
            if not self.oldest_date or date_str < self.oldest_date:
                self.oldest_date = date_str
            if not self.newest_date or date_str > self.newest_date:
                self.newest_date = date_str


# =============================================================================
# S3 Location Helpers
# =============================================================================


def _get_backup_locations(
    environment: str,
) -> list[tuple[str, str, str, str | None]]:
    """Get S3 backup locations filtered by environment.

    Args:
        environment: 'staging', 'prod', or 'both'.

    Returns:
        List of (name, bucket, prefix, profile) tuples.

    Raises:
        click.ClickException: If no locations configured.
    """
    raw_locations = os.getenv("PULLDB_S3_BACKUP_LOCATIONS")
    if not raw_locations:
        raise click.ClickException(
            click.style("Error: ", fg="red", bold=True)
            + "PULLDB_S3_BACKUP_LOCATIONS not configured.\n"
            + click.style("Hint: ", fg="yellow")
            + "Set this environment variable with S3 backup location JSON."
        )

    try:
        payload = json.loads(raw_locations)
    except json.JSONDecodeError as e:
        raise click.ClickException(
            f"Invalid JSON in PULLDB_S3_BACKUP_LOCATIONS: {e}"
        ) from e

    if not isinstance(payload, list):
        raise click.ClickException(
            "PULLDB_S3_BACKUP_LOCATIONS must be a JSON array."
        )

    locations: list[tuple[str, str, str, str | None]] = []
    env_lower = environment.lower()

    for entry in payload:
        if not isinstance(entry, dict):
            continue

        bucket_path = entry.get("bucket_path", "")
        name = entry.get("name", "unknown")
        profile = entry.get("profile")

        if not bucket_path.startswith("s3://"):
            continue

        # Filter by environment
        loc_lower = name.lower()
        if environment != "both":
            if loc_lower != env_lower and env_lower not in loc_lower:
                continue

        # Parse bucket and prefix
        path = bucket_path[5:]  # Remove "s3://"
        if "/" in path:
            bucket = path.split("/")[0]
            prefix = "/".join(path.split("/")[1:])
            if not prefix.endswith("/"):
                prefix += "/"
        else:
            bucket = path
            prefix = ""

        locations.append((name, bucket, prefix, profile))

    if not locations:
        raise click.ClickException(
            f"No backup locations found for environment: {environment}"
        )

    return locations


# =============================================================================
# Backup Collection Logic
# =============================================================================


def _collect_all_backups(
    locations: list[tuple[str, str, str, str | None]],
    customer_filter: str | None,
    date_from: str | None,
    date_to: str | None,
    min_bytes: int | None,
    max_bytes: int | None,
    verbose: bool,
) -> dict[str, CustomerBackupStats]:
    """Collect and aggregate backup statistics from S3.

    Uses efficient single-pass listing of all .tar files to avoid
    per-customer API calls.

    Args:
        locations: List of (name, bucket, prefix, profile) tuples.
        customer_filter: Optional customer name filter (exact match).
        date_from: Optional start date (YYYYMMDD).
        date_to: Optional end date (YYYYMMDD).
        min_bytes: Optional minimum size filter.
        max_bytes: Optional maximum size filter.
        verbose: Show detailed progress.

    Returns:
        Dict mapping customer name to CustomerBackupStats.
    """
    s3 = S3Client()
    stats: dict[str, CustomerBackupStats] = {}

    for loc_name, bucket, prefix, profile in locations:
        if verbose:
            click.echo(f"  Scanning {loc_name}: s3://{bucket}/{prefix}")

        # If customer filter provided, search only that customer's prefix
        if customer_filter:
            search_prefix = f"{prefix}{customer_filter}/"
        else:
            search_prefix = prefix

        try:
            # Single API call to get all keys with sizes
            keys_with_sizes = s3.list_keys_with_sizes(
                bucket, search_prefix, profile=profile
            )
        except Exception as exc:
            if verbose:
                click.echo(
                    click.style(f"    Error listing {bucket}: ", fg="yellow")
                    + str(exc)
                )
            continue

        if verbose:
            click.echo(f"    Found {len(keys_with_sizes)} objects")

        backup_count = 0
        for key, size_bytes in keys_with_sizes:
            # Only process .tar files
            if not key.endswith(".tar"):
                continue

            # Extract customer from path: prefix/customer/filename.tar
            rel_path = key[len(prefix):]
            if "/" not in rel_path:
                continue
            customer = rel_path.split("/")[0]

            # Skip non-lowercase customers (invalid names)
            if not customer.isalpha() or not customer.islower():
                continue

            # Apply customer filter
            if customer_filter and customer != customer_filter:
                continue

            # Extract date from filename
            date_str = _extract_date_from_key(key)
            if not date_str:
                continue

            # Apply date filters
            if date_from and date_str < date_from:
                continue
            if date_to and date_str > date_to:
                continue

            # Apply size filters
            if min_bytes and size_bytes < min_bytes:
                continue
            if max_bytes and size_bytes > max_bytes:
                continue

            # Add to stats
            if customer not in stats:
                stats[customer] = CustomerBackupStats(customer=customer)
            stats[customer].add_backup(size_bytes, date_str)
            backup_count += 1

        if verbose:
            click.echo(f"    Matched {backup_count} backups across {len(stats)} customers")

    return stats


def _collect_pattern_backups(
    locations: list[tuple[str, str, str, str | None]],
    pattern: str,
    date_from: str | None,
    date_to: str | None,
    min_bytes: int | None,
    max_bytes: int | None,
    verbose: bool,
) -> dict[str, CustomerBackupStats]:
    """Collect backups matching a wildcard pattern.

    Uses efficient single-pass listing with client-side pattern matching.

    Args:
        locations: List of (name, bucket, prefix, profile) tuples.
        pattern: Wildcard pattern (supports * and ?).
        date_from: Optional start date (YYYYMMDD).
        date_to: Optional end date (YYYYMMDD).
        min_bytes: Optional minimum size filter.
        max_bytes: Optional maximum size filter.
        verbose: Show detailed progress.

    Returns:
        Dict mapping customer name to CustomerBackupStats.
    """
    s3 = S3Client()
    stats: dict[str, CustomerBackupStats] = {}

    # Extract prefix before first wildcard for efficient listing
    wildcard_pos = min(
        (pattern.find(c) for c in "*?" if c in pattern),
        default=len(pattern),
    )
    search_prefix_part = pattern[:wildcard_pos].lower()

    for loc_name, bucket, prefix, profile in locations:
        if verbose:
            click.echo(f"  Scanning {loc_name}: s3://{bucket}/{prefix}")

        # Construct S3 prefix for listing
        s3_prefix = f"{prefix}{search_prefix_part}"

        try:
            keys_with_sizes = s3.list_keys_with_sizes(
                bucket, s3_prefix, profile=profile
            )
        except Exception as exc:
            if verbose:
                click.echo(
                    click.style(f"    Error listing {bucket}: ", fg="yellow")
                    + str(exc)
                )
            continue

        if verbose:
            click.echo(f"    Found {len(keys_with_sizes)} objects")

        backup_count = 0
        for key, size_bytes in keys_with_sizes:
            # Only process .tar files
            if not key.endswith(".tar"):
                continue

            # Extract customer from path
            rel_path = key[len(prefix):]
            if "/" not in rel_path:
                continue
            customer = rel_path.split("/")[0]

            # Skip non-lowercase customers
            if not customer.isalpha() or not customer.islower():
                continue

            # Apply wildcard pattern filter
            if not fnmatch.fnmatch(customer.lower(), pattern.lower()):
                continue

            # Extract date from filename
            date_str = _extract_date_from_key(key)
            if not date_str:
                continue

            # Apply date filters
            if date_from and date_str < date_from:
                continue
            if date_to and date_str > date_to:
                continue

            # Apply size filters
            if min_bytes and size_bytes < min_bytes:
                continue
            if max_bytes and size_bytes > max_bytes:
                continue

            # Add to stats
            if customer not in stats:
                stats[customer] = CustomerBackupStats(customer=customer)
            stats[customer].add_backup(size_bytes, date_str)
            backup_count += 1

        if verbose:
            click.echo(f"    Matched {backup_count} backups across {len(stats)} customers")

    return stats


# =============================================================================
# Output Formatting
# =============================================================================


def _print_stats_table(
    sorted_stats: list[CustomerBackupStats],
    all_stats: dict[str, CustomerBackupStats],
) -> None:
    """Print statistics as a formatted table with summary.

    Args:
        sorted_stats: List of stats to display (possibly limited).
        all_stats: Full stats dict for summary calculation.
    """
    if not sorted_stats:
        click.echo("No backups found matching criteria.")
        return

    # Table headers and rows
    headers = ["CUSTOMER", "COUNT", "DATE RANGE", "MIN", "AVG", "MAX"]
    rows: list[list[str]] = []

    for s in sorted_stats:
        date_range = f"{s.oldest_date} - {s.newest_date}" if s.oldest_date else "-"
        rows.append(
            [
                s.customer[:20],
                str(s.count),
                date_range,
                s.min_display,
                s.avg_display,
                s.max_display,
            ]
        )

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Print table
    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in col_widths))

    for row in rows:
        click.echo("  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))

    # Summary footer
    total_count = sum(s.count for s in all_stats.values())
    total_bytes = sum(s.total_bytes for s in all_stats.values())

    all_dates: list[str] = []
    for s in all_stats.values():
        if s.oldest_date:
            all_dates.append(s.oldest_date)
        if s.newest_date:
            all_dates.append(s.newest_date)

    click.echo(f"\n{len(all_stats)} customers, {total_count} backups")

    if all_dates:
        click.echo(f"  Date Range: {min(all_dates)} - {max(all_dates)}")

    all_sizes: list[int] = []
    for s in all_stats.values():
        if s.min_bytes:
            all_sizes.append(s.min_bytes)
        if s.max_bytes:
            all_sizes.append(s.max_bytes)

    if all_sizes and total_count > 0:
        overall_min = format_size(min(all_sizes))
        overall_avg = format_size(total_bytes // total_count)
        overall_max = format_size(max(all_sizes))
        overall_total = format_size(total_bytes)
        click.echo(
            f"  Size: MIN {overall_min} | AVG {overall_avg} | "
            f"MAX {overall_max} | TOTAL {overall_total}"
        )


def _stats_to_json(stats: dict[str, CustomerBackupStats]) -> str:
    """Convert stats dict to JSON string.

    Args:
        stats: Stats dictionary.

    Returns:
        JSON string.
    """
    output = []
    for s in sorted(stats.values(), key=lambda x: x.count, reverse=True):
        d = asdict(s)
        # Add display fields
        d["min_display"] = s.min_display
        d["avg_display"] = s.avg_display
        d["max_display"] = s.max_display
        d["avg_bytes"] = s.avg_bytes
        output.append(d)
    return json.dumps(output, indent=2)


# =============================================================================
# Click Command Group
# =============================================================================


@click.group(name="backups", help="List and search S3 backup archives")
@click.option(
    "--env",
    "environment",
    type=click.Choice(["staging", "prod", "both"]),
    default="prod",
    show_default=True,
    help="Environment to search",
)
@click.option("--verbose", "-v", is_flag=True, help="Show detailed progress")
@click.pass_context
def backups_group(ctx: click.Context, environment: str, verbose: bool) -> None:
    """Backup archive diagnostic commands."""
    ctx.ensure_object(dict)
    ctx.obj["environment"] = environment
    ctx.obj["verbose"] = verbose


@backups_group.command("list")
@click.option("--min-size", help="Minimum backup size (e.g., 5GB, 500MB)")
@click.option("--max-size", help="Maximum backup size (e.g., 20GB)")
@click.option("--from", "date_from", help="Start date (YYYYMMDD or YYYY-MM-DD)")
@click.option("--to", "date_to", help="End date (YYYYMMDD or YYYY-MM-DD)")
@click.option("--customer", help="Filter by exact customer name")
@click.option(
    "--limit",
    type=int,
    default=50,
    show_default=True,
    help="Max customers to show (0=unlimited)",
)
@click.option("--json", "json_out", is_flag=True, help="Output JSON")
@click.pass_context
def backups_list(
    ctx: click.Context,
    min_size: str | None,
    max_size: str | None,
    date_from: str | None,
    date_to: str | None,
    customer: str | None,
    limit: int,
    json_out: bool,
) -> None:
    """List customers with aggregated backup statistics.

    Shows per-customer backup count, date range, and size statistics
    (MIN/AVG/MAX). Use filters to narrow results.

    Examples:

        \b
        pulldb-admin backups list --min-size 5GB --max-size 20GB
        pulldb-admin backups list --from 20260101 --customer acme
        pulldb-admin backups list --env prod --limit 10
    """
    # Parse options
    min_bytes = _parse_size(min_size) if min_size else None
    max_bytes = _parse_size(max_size) if max_size else None
    date_from_normalized = _parse_date(date_from) if date_from else None
    date_to_normalized = _parse_date(date_to) if date_to else None

    verbose = ctx.obj["verbose"]
    environment = ctx.obj["environment"]

    # Show spinner unless verbose
    if not verbose and not json_out:
        click.echo("Scanning S3 backup locations...", nl=False)

    # Get locations and collect stats
    locations = _get_backup_locations(environment)
    stats = _collect_all_backups(
        locations,
        customer,
        date_from_normalized,
        date_to_normalized,
        min_bytes,
        max_bytes,
        verbose,
    )

    if not verbose and not json_out:
        click.echo(" done.\n")

    # JSON output
    if json_out:
        click.echo(_stats_to_json(stats))
        return

    # Sort by count descending
    sorted_stats = sorted(stats.values(), key=lambda s: s.count, reverse=True)
    if limit > 0:
        sorted_stats = sorted_stats[:limit]

    _print_stats_table(sorted_stats, stats)


@backups_group.command("search")
@click.argument("pattern")
@click.option("--min-size", help="Minimum backup size (e.g., 5GB, 500MB)")
@click.option("--max-size", help="Maximum backup size (e.g., 20GB)")
@click.option("--from", "date_from", help="Start date (YYYYMMDD or YYYY-MM-DD)")
@click.option("--to", "date_to", help="End date (YYYYMMDD or YYYY-MM-DD)")
@click.option(
    "--limit",
    type=int,
    default=20,
    show_default=True,
    help="Max customers to show (0=unlimited)",
)
@click.option("--json", "json_out", is_flag=True, help="Output JSON")
@click.pass_context
def backups_search(
    ctx: click.Context,
    pattern: str,
    min_size: str | None,
    max_size: str | None,
    date_from: str | None,
    date_to: str | None,
    limit: int,
    json_out: bool,
) -> None:
    """Search backups by customer pattern with wildcards.

    PATTERN supports * and ? wildcards:

    \b
        pest*     - customers starting with "pest"
        *routes*  - customers containing "routes"
        acme?     - customers like "acme1", "acme2"

    Examples:

    \b
        pulldb-admin backups search "pest*" --min-size 5GB
        pulldb-admin backups search "*routes*" --from 20260101
        pulldb-admin backups search "a*" --env prod --limit 10
    """
    # Reject overly broad patterns
    if not pattern or pattern.strip() == "" or pattern.strip() == "*":
        click.secho(
            "Error: Pattern cannot be blank or just '*'. "
            "Please provide a more specific pattern (e.g., 'a*', '*routes*').",
            fg="red",
            err=True,
        )
        raise SystemExit(1)

    # Parse options
    min_bytes = _parse_size(min_size) if min_size else None
    max_bytes = _parse_size(max_size) if max_size else None
    date_from_normalized = _parse_date(date_from) if date_from else None
    date_to_normalized = _parse_date(date_to) if date_to else None

    verbose = ctx.obj["verbose"]
    environment = ctx.obj["environment"]

    # Show spinner unless verbose
    if not verbose and not json_out:
        click.echo(f"Searching for '{pattern}'...", nl=False)

    # Get locations and collect stats
    locations = _get_backup_locations(environment)
    stats = _collect_pattern_backups(
        locations,
        pattern,
        date_from_normalized,
        date_to_normalized,
        min_bytes,
        max_bytes,
        verbose,
    )

    if not verbose and not json_out:
        click.echo(" done.\n")

    # JSON output
    if json_out:
        click.echo(_stats_to_json(stats))
        return

    # Sort by count descending
    sorted_stats = sorted(stats.values(), key=lambda s: s.count, reverse=True)
    if limit > 0:
        sorted_stats = sorted_stats[:limit]

    _print_stats_table(sorted_stats, stats)
