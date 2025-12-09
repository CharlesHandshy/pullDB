"""Service for discovering backups and customers in S3."""

from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import typing as t
from dataclasses import dataclass
from datetime import datetime

from pulldb.infra.factory import is_simulation_mode
from pulldb.infra.s3 import BACKUP_FILENAME_REGEX, S3Client


@dataclass
class BackupInfo:
    """Information about a discovered backup."""

    customer: str
    timestamp: datetime
    date: str  # YYYYMMDD format for display
    size_mb: float
    environment: str
    key: str
    bucket: str


@dataclass
class SearchContext:
    """Context for backup search operations."""

    s3: t.Any
    bucket: str
    prefix: str
    profile: str | None
    env_name: str
    filter_date: datetime | None


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

    def _search_customers_simulation(self, query: str, limit: int) -> list[str]:
        mock_customers = [
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
        ]
        query_lower = query.lower()
        matches = [c for c in mock_customers if query_lower in c.lower()]
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
        matches = sorted(
            [c for c in customer_set if query_lower in c.lower()],
            key=lambda x: (not x.lower().startswith(query_lower), x),
        )[:limit]

        return matches

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

        try:
            search_prefix = f"{prefix}{query.lower()}"
            keys = s3.list_keys(bucket, search_prefix, profile=profile)
            for key in keys:
                parts = key[len(prefix) :].split("/")
                if parts:
                    customer_set.add(parts[0])
        except Exception:
            pass

    def search_backups(
        self,
        customer: str,
        environment: str = "both",
        date_from: str | None = None,
        limit: int = 5,
    ) -> list[BackupInfo]:
        """Search for backups for a customer.

        Args:
            customer: Customer name or pattern.
            environment: 'staging', 'prod', or 'both'.
            date_from: Optional YYYYMMDD string.
            limit: Max results.

        Returns:
            List of BackupInfo objects.
        """
        if is_simulation_mode():
            return self._search_backups_simulation(customer, environment, limit)
        return self._search_backups_s3(customer, environment, date_from, limit)

    def _search_backups_simulation(
        self, customer: str, environment: str, limit: int
    ) -> list[BackupInfo]:
        results = []
        for i in range(limit):
            ts = datetime.now()
            env = "staging" if i % 2 == 0 else "prod"
            if environment not in ("both", env):
                continue

            results.append(
                BackupInfo(
                    customer=customer,
                    timestamp=ts,
                    date=ts.strftime("%Y%m%d"),
                    size_mb=1024.5,
                    environment=env,
                    key=f"mock/path/{customer}_{i}.sql.gz",
                    bucket="mock-bucket",
                )
            )
        return results

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
            all_locations = [
                (
                    "staging",
                    "pestroutesrdsdbs",
                    "daily/stg/",
                    os.getenv("PULLDB_S3_STAGING_PROFILE", "pr-staging"),
                ),
                (
                    "prod",
                    "pestroutes-rds-backup-prod-vpc-us-east-1-s3",
                    "daily/prod/",
                    os.getenv("PULLDB_S3_PROD_PROFILE", "pr-prod"),
                ),
            ]
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
    ) -> list[BackupInfo]:
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
            return []

        filter_date: datetime | None = None
        if date_from:
            with contextlib.suppress(ValueError):
                filter_date = datetime.strptime(date_from, "%Y%m%d")

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
            )
            self._search_in_bucket(ctx, customer, all_backups)

        all_backups.sort(key=lambda x: x.timestamp, reverse=True)
        return all_backups[:limit]

    def _search_in_bucket(
        self, ctx: SearchContext, customer: str, results: list[BackupInfo]
    ) -> None:
        try:
            if "*" in customer or "?" in customer:
                self._handle_wildcard_search(ctx, customer, results)
            else:
                self._collect_customer_backups(ctx, customer, results)
        except Exception:
            pass

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

        try:
            keys = ctx.s3.list_keys(
                ctx.bucket, search_prefix, profile=ctx.profile
            )
        except Exception:
            return

        for key in keys:
            self._process_backup_key(ctx, key, customer, results)

    def _process_backup_key(
        self,
        ctx: SearchContext,
        key: str,
        customer: str,
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

        if ctx.filter_date and ts < ctx.filter_date:
            return

        try:
            head = ctx.s3.head_object(ctx.bucket, key, profile=ctx.profile)
            size_bytes = int(head.get("ContentLength", 0))
        except Exception:
            size_bytes = 0

        results.append(
            BackupInfo(
                customer=customer,
                timestamp=ts,
                date=ts.strftime("%Y%m%d"),
                size_mb=round(size_bytes / (1024 * 1024), 1),
                environment=ctx.env_name,
                key=key,
                bucket=ctx.bucket,
            )
        )
