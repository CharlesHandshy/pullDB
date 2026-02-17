"""Service for discovering backups and customers in S3.

HCA Layer: entities
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import time
from typing import Any
from dataclasses import dataclass
from datetime import datetime, timedelta

from pulldb.infra.factory import is_simulation_mode
from pulldb.infra.logging import get_logger
from pulldb.infra.s3 import BACKUP_FILENAME_REGEX, S3Client

logger = get_logger("pulldb.domain.services.discovery")

# Customer cache: {(bucket, prefix): (customer_list, timestamp)}
_customer_cache: dict[tuple[str, str], tuple[list[str], float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def format_size(size_bytes: int) -> str:
    """Convert bytes to human-readable string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Human-readable string like "1.2 GB", "856 MB", "12 KB"
    """
    if size_bytes >= 1024 * 1024 * 1024:  # >= 1 GB
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    elif size_bytes >= 1024 * 1024:  # >= 1 MB
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes >= 1024:  # >= 1 KB
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes} B"


@dataclass
class BackupInfo:
    """Information about a discovered backup."""

    customer: str
    timestamp: datetime
    date: str  # YYYYMMDD format for display
    size_mb: float  # Kept for backward compatibility
    size_display: str  # Human-readable size (e.g., "1.2 GB")
    environment: str
    key: str
    bucket: str


@dataclass
class BackupSearchResult:
    """Result of backup search with pagination info."""

    backups: list[BackupInfo]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        """Check if there are more results beyond current page."""
        return self.offset + len(self.backups) < self.total


@dataclass
class SearchContext:
    """Context for backup search operations."""

    s3: Any
    bucket: str
    prefix: str
    profile: str | None
    env_name: str
    filter_date: datetime | None
    filter_date_to: datetime | None = None
    date_mode: str = "on_or_after"


class DiscoveryService:
    """Service for discovering backups and customers."""

    def search_customers(self, query: str, limit: int = 10) -> list[str]:
        """Search for customers matching the query.

        Args:
            query: Search string (min 3 chars recommended).
            limit: Max results to return.

        Returns:
            List of matching customer names.
        """
        if is_simulation_mode():
            return self._search_customers_simulation(query, limit)
        return self._search_customers_s3(query, limit)

    def _get_simulation_customers(self) -> list[str]:
        """Get the list of mock customers for simulation mode.
        
        Returns LEAN_CUSTOMERS if in lean scenario, otherwise full list.
        """
        try:
            from pulldb.simulation import get_simulation_state
            state = get_simulation_state()
            # Check if lean scenario (has limited customers via settings marker)
            if state.settings.get("maintenance_mode") == "false" and len(state.hosts) == 1:
                # Lean mode - use LEAN_CUSTOMERS
                from pulldb.simulation.core.seeding import LEAN_CUSTOMERS
                return list(LEAN_CUSTOMERS)
        except Exception:
            # Graceful fallback to full customer list
            logger.debug("Failed to get lean simulation customers", exc_info=True)
        
        # Full simulation - use standard customer list
        return [
            "actionpest",
            "actionplumbing",
            "acmehvac",
            "bigcorp",
            "cleanpro",
            "deltaplumbing",
            "eliteelectric",
            "fastfix",
            "greenscapes",
            "homeservices",
            "techcorp",
            "globalretail",
            "healthnet",
            "autoparts",
            "buildpro",
            "foodmart",
            "energyco",
            "finserve",
            "edulearn",
            "medisys",
        ]

    def _search_customers_simulation(self, query: str, limit: int) -> list[str]:
        mock_customers = self._get_simulation_customers()
        query_lower = query.lower()
        # Filter: only include customers with lowercase letters only (a-z)
        matches = [c for c in mock_customers 
                   if query_lower in c.lower() and c.isalpha() and c.islower()]
        return sorted(matches)[:limit]

    def _search_customers_s3(self, query: str, limit: int) -> list[str]:
        raw_locations = os.getenv("PULLDB_S3_BACKUP_LOCATIONS")
        if not raw_locations:
            return []

        s3 = S3Client()
        customer_set: set[str] = set()

        with contextlib.suppress(Exception):
            payload = json.loads(raw_locations)
            if isinstance(payload, list):
                for entry in payload:
                    if isinstance(entry, dict):
                        self._process_customer_location(
                            entry, query, s3, customer_set
                        )

        query_lower = query.lower()
        # Filter: only include customers with lowercase letters only (a-z)
        # Exclude any customers with uppercase, numbers, symbols, etc.
        matches = sorted(
            [c for c in customer_set 
             if query_lower in c.lower() and c.isalpha() and c.islower()],
            key=lambda x: (not x.lower().startswith(query_lower), x),
        )[:limit]

        return matches

    def search_customers_pattern(self, pattern: str, limit: int = 100) -> list[str]:
        """Search for customers using wildcard pattern.

        Args:
            pattern: Pattern with * and/or ? wildcards (e.g., 'action*', '*pest').
            limit: Max results to return.

        Returns:
            List of matching customer names.
        """
        if is_simulation_mode():
            return self._search_customers_pattern_simulation(pattern, limit)
        return self._search_customers_pattern_s3(pattern, limit)

    def _search_customers_pattern_simulation(self, pattern: str, limit: int) -> list[str]:
        mock_customers = self._get_simulation_customers()
        matching = [
            c for c in mock_customers
            if fnmatch.fnmatch(c.lower(), pattern.lower())
        ]
        return sorted(matching)[:limit]

    def _search_customers_pattern_s3(self, pattern: str, limit: int) -> list[str]:
        """Search S3 for customers matching wildcard pattern."""
        raw_locations = os.getenv("PULLDB_S3_BACKUP_LOCATIONS")
        if not raw_locations:
            return []

        s3_profile = (
            os.getenv("PULLDB_S3_AWS_PROFILE") or os.getenv("PULLDB_AWS_PROFILE")
        )
        s3 = S3Client(profile=s3_profile)
        customer_set: set[str] = set()

        # Extract prefix before wildcard for efficient S3 listing
        wildcard_pos = min(
            (pattern.find(c) for c in "*?" if c in pattern),
            default=len(pattern),
        )
        search_prefix = pattern[:wildcard_pos].lower()

        with contextlib.suppress(Exception):
            payload = json.loads(raw_locations)
            if isinstance(payload, list):
                for entry in payload:
                    if isinstance(entry, dict):
                        self._collect_pattern_customers(
                            entry, search_prefix, pattern, s3, customer_set
                        )

        # Filter by pattern and return
        matching = sorted([
            c for c in customer_set
            if fnmatch.fnmatch(c.lower(), pattern.lower())
            and c.isalpha() and c.islower()
        ])[:limit]

        return matching

    def _collect_pattern_customers(
        self,
        entry: dict,
        search_prefix: str,
        pattern: str,
        s3: S3Client,
        customer_set: set[str],
    ) -> None:
        """Collect customers matching pattern from a single S3 location."""
        bucket_path = entry.get("bucket_path", "")
        profile = entry.get("profile")

        if not bucket_path.startswith("s3://"):
            return

        path = bucket_path[5:]
        if "/" in path:
            bucket = path.split("/")[0]
            prefix = "/".join(path.split("/")[1:])
            if not prefix.endswith("/"):
                prefix += "/"
        else:
            bucket = path
            prefix = ""

        try:
            # List all prefixes starting with search_prefix
            s3_prefix = f"{prefix}{search_prefix}"
            # list_prefixes returns suffixes after s3_prefix, reconstruct full names
            suffixes = s3.list_prefixes(
                bucket, s3_prefix, profile=profile, max_results=500
            )
            # Reconstruct full customer names by prepending the search prefix
            customers = [f"{search_prefix}{suffix}" for suffix in suffixes]

            # Check for exact-match customer (e.g., "affordable" when searching "affordable*")
            # S3 CommonPrefixes doesn't return the queried prefix itself, only children.
            # We need an explicit check if the exact folder has content.
            if search_prefix:
                exact_folder = f"{prefix}{search_prefix}/"
                try:
                    exact_keys = s3.list_keys(
                        bucket, exact_folder, profile=profile, max_keys=1
                    )
                    if exact_keys:
                        customers.append(search_prefix)
                except Exception:
                    # S3 listing can fail for various reasons - continue without exact match
                    logger.debug("Failed to check exact folder %s", exact_folder, exc_info=True)

            customer_set.update(customers)
        except Exception:
            # Multi-source search - continue with other sources
            logger.debug("Failed to list customers from S3", exc_info=True)

    def _get_cached_customers(
        self, bucket: str, prefix: str
    ) -> list[str] | None:
        """Get cached customer list if not expired."""
        cache_key = (bucket, prefix)
        if cache_key in _customer_cache:
            customers, timestamp = _customer_cache[cache_key]
            if time.time() - timestamp < _CACHE_TTL_SECONDS:
                return customers
            # Expired, remove from cache
            del _customer_cache[cache_key]
        return None

    def _set_cached_customers(
        self, bucket: str, prefix: str, customers: list[str]
    ) -> None:
        """Store customer list in cache."""
        _customer_cache[(bucket, prefix)] = (customers, time.time())

    def _process_customer_location(
        self, entry: dict, query: str, s3: S3Client, customer_set: set[str]
    ) -> None:
        bucket_path = entry.get("bucket_path", "")
        profile = entry.get("profile")

        if not bucket_path.startswith("s3://"):
            return

        path = bucket_path[5:]
        if "/" in path:
            bucket = path.split("/")[0]
            prefix = "/".join(path.split("/")[1:])
            if not prefix.endswith("/"):
                prefix += "/"
        else:
            bucket = path
            prefix = ""

        # Check cache first
        cached = self._get_cached_customers(bucket, prefix)
        if cached is not None:
            customer_set.update(cached)
            return

        try:
            # Use list_prefixes for efficient folder discovery
            # Search with query prefix for faster results
            query_lower = query.lower()
            search_prefix = f"{prefix}{query_lower}"
            
            # list_prefixes returns suffixes after search_prefix, reconstruct full names
            suffixes = s3.list_prefixes(
                bucket, search_prefix, profile=profile, max_results=500
            )
            # Reconstruct full customer names by prepending the query prefix
            customers = [f"{query_lower}{suffix}" for suffix in suffixes]

            # Check for exact-match customer (e.g., "affordable" when searching "affordable")
            # S3 CommonPrefixes doesn't return the queried prefix itself, only children.
            # We need an explicit check if the exact folder has content.
            if query_lower:
                exact_folder = f"{prefix}{query_lower}/"
                try:
                    exact_keys = s3.list_keys(
                        bucket, exact_folder, profile=profile, max_keys=1
                    )
                    if exact_keys:
                        customers.append(query_lower)
                except Exception:
                    # S3 listing can fail - continue without exact match
                    logger.debug("Failed to check exact folder %s", exact_folder, exc_info=True)

            customer_set.update(customers)

            # If query is short (3-4 chars), also cache the full list
            # for future filtered searches
            if len(query) <= 4:
                all_customers = s3.list_prefixes(
                    bucket, prefix, profile=profile, max_results=1000
                )
                self._set_cached_customers(bucket, prefix, all_customers)
        except Exception as exc:
            logger.error(
                "Error listing customer prefixes from S3",
                extra={
                    "bucket": bucket,
                    "prefix": prefix,
                    "profile": profile,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

    def search_backups(
        self,
        customer: str,
        environment: str = "both",
        date_from: str | None = None,
        limit: int = 5,
        offset: int = 0,
        *,
        date_to: str | None = None,
        date_mode: str = "on_or_after",
    ) -> BackupSearchResult:
        """Search for backups for a customer.

        Args:
            customer: Customer name or pattern.
            environment: 'staging', 'prod', or 'both'.
            date_from: Optional YYYYMMDD string.
            limit: Max results per page.
            offset: Number of results to skip for pagination.
            date_to: Optional YYYYMMDD end date (used with 'between' mode).
            date_mode: Date filter mode ('on_or_after', 'on_or_before', 'on_date', 'between').

        Returns:
            BackupSearchResult with backups, total count, and pagination info.
        """
        if is_simulation_mode():
            # Parse date strings for simulation filtering
            sim_filter_date: datetime | None = None
            sim_filter_date_to: datetime | None = None
            if date_from:
                with contextlib.suppress(ValueError):
                    sim_filter_date = datetime.strptime(date_from, "%Y%m%d")
            if date_to:
                with contextlib.suppress(ValueError):
                    sim_filter_date_to = datetime.strptime(date_to, "%Y%m%d").replace(
                        hour=23, minute=59, second=59
                    )
            return self._search_backups_simulation(
                customer, environment, limit, offset,
                date_mode=date_mode,
                filter_date=sim_filter_date,
                filter_date_to=sim_filter_date_to,
            )
        return self._search_backups_s3(customer, environment, date_from, limit, offset, date_to=date_to, date_mode=date_mode)

    def _search_backups_simulation(
        self,
        customer: str,
        environment: str,
        limit: int,
        offset: int = 0,
        *,
        date_mode: str = "on_or_after",
        filter_date: datetime | None = None,
        filter_date_to: datetime | None = None,
    ) -> BackupSearchResult:
        all_results = []
        # Generate more mock results for pagination testing
        base_date = datetime.now()
        for i in range(20):
            # Create timestamps going back in time
            ts = base_date - timedelta(days=i)
            env = "staging" if i % 2 == 0 else "prod"
            if environment not in ("both", env):
                continue

            # Apply date filtering (mirrors _process_backup_key logic)
            if filter_date:
                if date_mode == "on_or_after":
                    if ts < filter_date:
                        continue
                elif date_mode == "on_or_before":
                    end_of_day = filter_date.replace(hour=23, minute=59, second=59)
                    if ts > end_of_day:
                        continue
                elif date_mode == "on_date":
                    if ts.date() != filter_date.date():
                        continue
                elif date_mode == "between":
                    if ts < filter_date:
                        continue
                    if filter_date_to and ts > filter_date_to:
                        continue

            size_bytes = 1024 * 1024 * 1024 + i * 100 * 1024 * 1024  # ~1GB
            # Generate valid backup key format: {customer}/daily_mydumper_{customer}_{timestamp}
            timestamp_str = ts.strftime("%Y-%m-%dT%H-%M-%SZ")
            day_abbr = ts.strftime("%a")
            backup_key = f"s3://mock-bucket/daily/{env}/{customer}/daily_mydumper_{customer}_{timestamp_str}_{day_abbr}_dbimp.tar"
            all_results.append(
                BackupInfo(
                    customer=customer,
                    timestamp=ts,
                    date=ts.strftime("%Y%m%d"),
                    size_mb=round(size_bytes / (1024 * 1024), 1),
                    size_display=format_size(size_bytes),
                    environment=env,
                    key=backup_key,
                    bucket="mock-bucket",
                )
            )
        total = len(all_results)
        page = all_results[offset:offset + limit]
        return BackupSearchResult(backups=page, total=total, offset=offset, limit=limit)

    def _get_backup_locations(self) -> list[tuple[str, str, str, str | None]]:
        raw_locations = os.getenv("PULLDB_S3_BACKUP_LOCATIONS")
        all_locations: list[tuple[str, str, str, str | None]] = []

        if raw_locations:
            with contextlib.suppress(json.JSONDecodeError):
                payload = json.loads(raw_locations)
                if isinstance(payload, list):
                    for entry in payload:
                        if isinstance(entry, dict):
                            self._parse_location_entry(entry, all_locations)

        if not all_locations:
            raise ValueError(
                "PULLDB_S3_BACKUP_LOCATIONS not configured or invalid JSON. "
                "Set this environment variable with a JSON array of location objects. "
                "See packaging/env.example for the expected format."
            )
        return all_locations

    def _parse_location_entry(
        self, entry: dict, locations: list[tuple[str, str, str, str | None]]
    ) -> None:
        bucket_path = entry.get("bucket_path", "")
        name = entry.get("name", "unknown")
        profile = entry.get("profile")

        if not bucket_path.startswith("s3://"):
            return

        path = bucket_path[5:]
        if "/" in path:
            bucket = path.split("/")[0]
            prefix = "/".join(path.split("/")[1:])
            if not prefix.endswith("/"):
                prefix += "/"
        else:
            bucket = path
            prefix = ""
        locations.append((name, bucket, prefix, profile))

    def _search_backups_s3(
        self,
        customer: str,
        environment: str,
        date_from: str | None,
        limit: int,
        offset: int = 0,
        *,
        date_to: str | None = None,
        date_mode: str = "on_or_after",
    ) -> BackupSearchResult:
        all_locations = self._get_backup_locations()

        # Filter by environment
        buckets = []
        env_lower = environment.lower()
        for loc_name, bucket, prefix, profile in all_locations:
            loc_lower = loc_name.lower()
            if (
                environment == "both"
                or loc_lower == env_lower
                or env_lower in loc_lower
            ):
                buckets.append((loc_name, bucket, prefix, profile))

        if not buckets:
            return BackupSearchResult(backups=[], total=0, offset=offset, limit=limit)

        filter_date: datetime | None = None
        if date_from:
            with contextlib.suppress(ValueError):
                filter_date = datetime.strptime(date_from, "%Y%m%d")

        filter_date_to: datetime | None = None
        if date_to:
            with contextlib.suppress(ValueError):
                # Set to end of day so "between" is inclusive of the end date
                filter_date_to = datetime.strptime(date_to, "%Y%m%d").replace(
                    hour=23, minute=59, second=59
                )

        s3_profile = (
            os.getenv("PULLDB_S3_AWS_PROFILE") or os.getenv("PULLDB_AWS_PROFILE")
        )
        s3 = S3Client(profile=s3_profile)
        all_backups: list[BackupInfo] = []

        for env_name, bucket, prefix, profile in buckets:
            ctx = SearchContext(
                s3=s3,
                bucket=bucket,
                prefix=prefix,
                profile=profile,
                env_name=env_name,
                filter_date=filter_date,
                filter_date_to=filter_date_to,
                date_mode=date_mode,
            )
            self._search_in_bucket(ctx, customer, all_backups)

        all_backups.sort(key=lambda x: x.timestamp, reverse=True)
        total = len(all_backups)
        page = all_backups[offset:offset + limit]
        return BackupSearchResult(backups=page, total=total, offset=offset, limit=limit)

    def _search_in_bucket(
        self, ctx: SearchContext, customer: str, results: list[BackupInfo]
    ) -> None:
        try:
            if "*" in customer or "?" in customer:
                self._handle_wildcard_search(ctx, customer, results)
            else:
                self._collect_customer_backups(ctx, customer, results)
        except Exception as exc:
            logger.error(
                "Error searching bucket for backups",
                extra={
                    "bucket": ctx.bucket,
                    "prefix": ctx.prefix,
                    "customer": customer,
                    "profile": ctx.profile,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

    def _handle_wildcard_search(
        self, ctx: SearchContext, customer: str, results: list[BackupInfo]
    ) -> None:
        # Extract prefix before wildcard
        wildcard_pos = min(
            (customer.find(c) for c in "*?" if c in customer),
            default=len(customer),
        )
        search_prefix = customer[:wildcard_pos]
        s3_prefix = f"{ctx.prefix}{search_prefix}"
        keys = ctx.s3.list_keys(ctx.bucket, s3_prefix, profile=ctx.profile)

        # Extract unique customer dirs
        customer_dirs: set[str] = set()
        for key in keys:
            parts = key[len(ctx.prefix) :].split("/")
            if parts:
                customer_dirs.add(parts[0])

        # Filter by wildcard
        matching = [
            c
            for c in customer_dirs
            if fnmatch.fnmatch(c.lower(), customer.lower())
        ]

        for cust in matching[:20]:
            self._collect_customer_backups(ctx, cust, results)

    def _collect_customer_backups(
        self, ctx: SearchContext, customer: str, results: list[BackupInfo]
    ) -> None:
        search_prefix = f"{ctx.prefix}{customer}/daily_mydumper_{customer}_"
        logger.debug(
            "Searching for customer backups",
            extra={
                "bucket": ctx.bucket,
                "search_prefix": search_prefix,
                "profile": ctx.profile,
            },
        )

        try:
            # Use list_keys_with_sizes to get sizes in single API call
            keys_with_sizes = ctx.s3.list_keys_with_sizes(
                ctx.bucket, search_prefix, profile=ctx.profile
            )
            logger.debug(
                "Found backup keys",
                extra={
                    "bucket": ctx.bucket,
                    "count": len(keys_with_sizes),
                    "customer": customer,
                },
            )
        except Exception as exc:
            logger.error(
                "Error listing backup keys from S3",
                extra={
                    "bucket": ctx.bucket,
                    "search_prefix": search_prefix,
                    "profile": ctx.profile,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return

        for key, size_bytes in keys_with_sizes:
            self._process_backup_key(ctx, key, customer, size_bytes, results)

    def _process_backup_key(
        self,
        ctx: SearchContext,
        key: str,
        customer: str,
        size_bytes: int,
        results: list[BackupInfo],
    ) -> None:
        filename = key.rsplit("/", 1)[-1]
        match = BACKUP_FILENAME_REGEX.match(filename)
        if not match:
            return

        ts_str = match.group("ts")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H-%M-%SZ")
        except ValueError:
            return

        # Apply date filter based on mode
        if ctx.filter_date:
            mode = ctx.date_mode
            if mode == "on_or_after":
                if ts < ctx.filter_date:
                    return
            elif mode == "on_or_before":
                # Include backups up to end of the filter day
                end_of_day = ctx.filter_date.replace(hour=23, minute=59, second=59)
                if ts > end_of_day:
                    return
            elif mode == "on_date":
                # Only include backups on the exact calendar date
                if ts.date() != ctx.filter_date.date():
                    return
            elif mode == "between":
                if ts < ctx.filter_date:
                    return
                if ctx.filter_date_to and ts > ctx.filter_date_to:
                    return

        results.append(
            BackupInfo(
                customer=customer,
                timestamp=ts,
                date=ts.strftime("%Y%m%d"),
                size_mb=round(size_bytes / (1024 * 1024), 1),
                size_display=format_size(size_bytes),
                environment=ctx.env_name,
                key=key,
                bucket=ctx.bucket,
            )
        )
