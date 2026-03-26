"""Overlord database integration infrastructure.

Provides connection management and repository for interacting with the 
external overlord.companies table. This module handles:
- Safe connection to overlord database (separate from pulldb_service)
- CRUD operations on overlord.companies rows
- Tracking of pullDB ownership in our local overlord_tracking table

SAFETY: This module interacts with a PRODUCTION routing table.
All operations must verify ownership before modifying data.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

import mysql.connector
from mysql.connector.abstracts import MySQLConnectionAbstract

from pulldb.domain.overlord import (
    OverlordAlreadyClaimedError,
    OverlordCompany,
    OverlordConnectionError,
    OverlordError,
    OverlordExternalChangeError,
    OverlordOwnershipError,
    OverlordRowDeletedError,
    OverlordSafetyError,
    OverlordTracking,
    OverlordTrackingStatus,
)
from pulldb.infra.secrets import CredentialResolver, MySQLCredentials

if TYPE_CHECKING:
    from pulldb.infra.mysql import MySQLPool


logger = logging.getLogger(__name__)


# Re-export domain types for backward compatibility
__all__ = [
    "OverlordAlreadyClaimedError",
    "OverlordCompany",
    "OverlordConnection",
    "OverlordConnectionError",
    "OverlordError",
    "OverlordExternalChangeError",
    "OverlordOwnershipError",
    "OverlordRepository",
    "OverlordRowDeletedError",
    "OverlordSafetyError",
    "OverlordTracking",
    "OverlordTrackingRepository",
    "OverlordTrackingStatus",
]


# =============================================================================
# Overlord Connection (External Database)
# =============================================================================


class OverlordConnection:
    """Connection manager for external overlord database.
    
    This is a SEPARATE database from pulldb_service. We connect with
    limited permissions (SELECT, INSERT, UPDATE, DELETE on companies table only).
    
    SAFETY: All operations are parameterized. No dynamic SQL construction.
    """
    
    # Connection limits - overlord is not our database
    CONNECT_TIMEOUT_SECONDS = 5
    QUERY_TIMEOUT_SECONDS = 10
    
    def __init__(
        self,
        host: str,
        database: str,
        user: str,
        password: str,
        port: int = 3306,
    ) -> None:
        """Initialize overlord connection.
        
        Args:
            host: Overlord database hostname
            database: Database name (usually 'overlord')
            user: MySQL username (usually 'pulldb_service')
            password: MySQL password
            port: MySQL port (default 3306)
        """
        self._host = host
        self._database = database
        self._user = user
        self._password = password
        self._port = port
        
        # Store settings for refresh capability (set by from_settings classmethod)
        self._settings_repo: Any = None
        self._credential_resolver: CredentialResolver | None = None
    
    @classmethod
    def from_settings(
        cls,
        settings_repo: Any,
        credential_resolver: CredentialResolver,
    ) -> OverlordConnection | None:
        """Create connection from pullDB settings.
        
        Args:
            settings_repo: SettingsRepository to read config from
            credential_resolver: Resolver for AWS Secrets Manager
            
        Returns:
            OverlordConnection if configured, None if disabled
        """
        # Check if enabled
        enabled = settings_repo.get("overlord_enabled") or "false"
        if enabled.lower() != "true":
            return None
        
        # Get connection settings
        host = settings_repo.get("overlord_dbhost")
        database = settings_repo.get("overlord_database") or "overlord"
        credential_ref = settings_repo.get("overlord_credential_ref")
        
        if not host or not credential_ref:
            logger.warning("Overlord enabled but missing dbhost or credential_ref")
            return None
        
        # Resolve credentials
        try:
            creds = credential_resolver.resolve(credential_ref)
        except Exception as e:
            logger.error(f"Failed to resolve overlord credentials: {e}")
            return None
        
        conn = cls(
            host=host,
            database=database,
            user=creds.username if hasattr(creds, 'username') else 'pulldb_service',
            password=creds.password,
            port=creds.port if hasattr(creds, 'port') else 3306,
        )
        # Store references for credential refresh
        conn._settings_repo = settings_repo
        conn._credential_resolver = credential_resolver
        return conn
    
    def refresh_credentials(self) -> bool:
        """Refresh credentials from AWS Secrets Manager.
        
        Call this after rotating credentials to update the cached password.
        
        Returns:
            True if credentials were refreshed successfully
            
        Raises:
            OverlordConnectionError: If refresh fails
        """
        if not self._settings_repo or not self._credential_resolver:
            raise OverlordConnectionError(
                "Cannot refresh: connection was not created from settings"
            )
        
        credential_ref = self._settings_repo.get("overlord_credential_ref")
        if not credential_ref:
            raise OverlordConnectionError("No credential_ref in settings")
        
        try:
            # Force fresh fetch by clearing any caching
            creds = self._credential_resolver.resolve(credential_ref)
            self._password = creds.password
            if hasattr(creds, 'username'):
                self._user = creds.username
            if hasattr(creds, 'port'):
                self._port = creds.port
            logger.info("Overlord credentials refreshed from AWS Secrets Manager")
            return True
        except Exception as e:
            raise OverlordConnectionError(f"Failed to refresh credentials: {e}") from e
    
    @contextmanager
    def connection(self) -> Iterator[MySQLConnectionAbstract]:
        """Get a connection to overlord database.
        
        Yields:
            MySQL connection with automatic cleanup
        """
        try:
            conn = mysql.connector.connect(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
                connect_timeout=self.CONNECT_TIMEOUT_SECONDS,
            )
        except mysql.connector.Error as e:
            raise OverlordConnectionError(f"Failed to connect to overlord: {e}") from e
        
        try:
            self._apply_session_timeouts(conn)
            yield conn
        finally:
            conn.close()
    
    @contextmanager
    def transaction(self) -> Iterator[MySQLConnectionAbstract]:
        """Get a connection with transaction control.
        
        Yields:
            MySQL connection with autocommit disabled
        """
        try:
            conn = mysql.connector.connect(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
                connect_timeout=self.CONNECT_TIMEOUT_SECONDS,
                autocommit=False,
            )
        except mysql.connector.Error as e:
            raise OverlordConnectionError(f"Failed to connect to overlord: {e}") from e
        
        try:
            self._apply_session_timeouts(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _apply_session_timeouts(self, conn: Any) -> None:
        """Set session-level query timeouts on a fresh connection.

        - max_execution_time: Kills SELECT queries exceeding the limit (ms).
        - net_read_timeout / net_write_timeout: Socket-level guards for DML.

        These protect against hung queries on the external overlord database.
        """
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SET SESSION max_execution_time = %s",
                (self.QUERY_TIMEOUT_SECONDS * 1000,),
            )
            cursor.execute(
                "SET SESSION net_read_timeout = %s",
                (self.QUERY_TIMEOUT_SECONDS,),
            )
            cursor.execute(
                "SET SESSION net_write_timeout = %s",
                (self.QUERY_TIMEOUT_SECONDS,),
            )
            cursor.close()
        except mysql.connector.Error:
            # Non-fatal: some MySQL versions may not support max_execution_time.
            # The connect_timeout still provides baseline protection.
            logger.debug("Could not set session timeouts on overlord connection")


# =============================================================================
# Overlord Repository (External Database Operations)
# =============================================================================

# Allowlist of valid table names for SQL safety
_VALID_TABLES: frozenset[str] = frozenset({"companies"})

# Allowlist of valid column names for SQL safety
# These are ALL columns in the overlord.companies table (27 total)
_VALID_COLUMNS: frozenset[str] = frozenset({
    # Core identification
    "companyID", "database", "company", "name",
    # Routing fields
    "dbHost", "dbHostRead", "dbServer", "subdomain",
    "dbHostDynamicRead", "enableDynamicRead", "dbHostApiRead",
    # Metadata fields
    "owner", "visible", "order",
    # Branding fields
    "brandingPrefix", "brandingLogo", "logo", "branding",
    "legacyBranding", "exclusiveDomain", "mascot",
    # Contact & billing fields
    "adminContact", "adminPhone", "adminEmail",
    "billingEmail", "billingName", "sendTRInvoice",
    # Franchise fields
    "canFranchise", "franchiseName", "franchiseLogo",
    # Operations
    "blockPrtDate",
})


def _validate_table_name(table: str) -> None:
    """Validate table name against allowlist.
    
    Raises:
        ValueError: If table name is not in the allowlist
    """
    if table not in _VALID_TABLES:
        raise ValueError(f"Invalid table name: {table}. Allowed: {_VALID_TABLES}")


def _validate_column_names(columns: list[str]) -> None:
    """Validate column names against allowlist.
    
    Raises:
        ValueError: If any column name is not in the allowlist
    """
    invalid = set(columns) - _VALID_COLUMNS
    if invalid:
        raise ValueError(f"Invalid column names: {invalid}. Allowed: {_VALID_COLUMNS}")


class OverlordRepository:
    """Repository for overlord.companies table operations.
    
    Provides safe CRUD operations on the external overlord database.
    All queries are parameterized to prevent SQL injection.
    Column and table names are validated against allowlists.
    
    SAFETY: This interacts with a production routing table!
    """
    
    def __init__(self, connection: OverlordConnection, table: str = "companies") -> None:
        """Initialize repository.
        
        Args:
            connection: OverlordConnection instance
            table: Table name (default 'companies')
            
        Raises:
            ValueError: If table name is not in the allowlist
        """
        _validate_table_name(table)
        self._conn = connection
        self._table = table
        self._real_columns: frozenset[str] | None = None  # lazily discovered

    def _get_real_columns(self) -> frozenset[str]:
        """Discover actual column names from the external table.

        Cached after the first call so we only run SHOW COLUMNS once
        per OverlordRepository lifetime.
        """
        if self._real_columns is not None:
            return self._real_columns

        with self._conn.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SHOW COLUMNS FROM {self._table}")
            cols = frozenset(row[0] for row in cursor.fetchall())
            cursor.close()

        self._real_columns = cols
        logger.debug("Discovered %d columns in %s: %s", len(cols), self._table, cols)
        return cols

    def _filter_to_real_columns(self, data: dict[str, Any]) -> dict[str, Any]:
        """Remove keys that don't exist as columns in the real table."""
        real = self._get_real_columns()
        filtered = {k: v for k, v in data.items() if k in real}
        dropped = set(data.keys()) - set(filtered.keys())
        if dropped:
            logger.debug("Dropped non-existent columns: %s", dropped)
        return filtered
    
    def get_by_database(self, database_name: str) -> OverlordCompany | None:
        """Get company record by database name.
        
        Args:
            database_name: The database field value (matches job.target)
            
        Returns:
            OverlordCompany if found, None otherwise
        """
        with self._conn.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"SELECT * FROM {self._table} WHERE `database` = %s LIMIT 1",
                (database_name,)
            )
            row = cursor.fetchone()
            cursor.close()
            
            if not row:
                return None
            return OverlordCompany.from_row(row)
    
    def get_all_by_database(self, database_name: str) -> list[dict[str, Any]]:
        """Get ALL company records for a database name.

        Unlike get_by_database() which returns only the first match,
        this returns every row where ``database = %s``, supporting
        databases with multiple company/subdomain records.

        Args:
            database_name: The database field value (matches job.target)

        Returns:
            List of all matching rows as dicts, ordered by companyID ASC.
            Empty list if none found.
        """
        with self._conn.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"SELECT * FROM {self._table} WHERE `database` = %s ORDER BY `companyID` ASC",
                (database_name,),
            )
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows]

    def get_row_snapshot(self, database_name: str) -> dict[str, Any] | None:
        """Get full row as dictionary for backup purposes.
        
        Args:
            database_name: The database field value
            
        Returns:
            Full row as dict, or None if not found
        """
        with self._conn.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"SELECT * FROM {self._table} WHERE `database` = %s LIMIT 1",
                (database_name,)
            )
            row = cursor.fetchone()
            cursor.close()
            return dict(row) if row else None
    
    def insert(self, data: dict[str, Any]) -> int:
        """Insert a new company record.
        
        Args:
            data: Column name -> value mapping
            
        Returns:
            Inserted companyID
            
        Raises:
            ValueError: If any column name is not in the allowlist
        """
        data = self._filter_to_real_columns(data)
        columns = list(data.keys())
        _validate_column_names(columns)  # Security: validate before building SQL
        
        placeholders = ", ".join(["%s"] * len(columns))
        column_names = ", ".join([f"`{c}`" for c in columns])
        
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO {self._table} ({column_names}) VALUES ({placeholders})",
                tuple(data.values())
            )
            company_id = cursor.lastrowid
            cursor.close()
            logger.info(f"Inserted overlord company: database={data.get('database')}, id={company_id}")
            return company_id
    
    def update(self, database_name: str, data: dict[str, Any]) -> bool:
        """Update an existing company record.
        
        Args:
            database_name: The database field to identify the row
            data: Column name -> value mapping (what to update)
            
        Returns:
            True if row was updated, False if not found
            
        Raises:
            ValueError: If any column name is not in the allowlist
        """
        if not data:
            return False
        
        data = self._filter_to_real_columns(data)
        if not data:
            return False
        
        columns = list(data.keys())
        _validate_column_names(columns)  # Security: validate before building SQL
        
        set_clauses = ", ".join([f"`{k}` = %s" for k in columns])
        values = list(data.values()) + [database_name]
        
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE {self._table} SET {set_clauses} WHERE `database` = %s",
                tuple(values)
            )
            affected = cursor.rowcount
            cursor.close()
            
            if affected > 0:
                logger.info(f"Updated overlord company: database={database_name}")
            return affected > 0
    
    def delete(self, database_name: str) -> bool:
        """Delete a company record.
        
        SAFETY: Only call this for rows pullDB created (row_existed_before=False)
        
        Args:
            database_name: The database field to identify the row
            
        Returns:
            True if row was deleted, False if not found
        """
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"DELETE FROM {self._table} WHERE `database` = %s",
                (database_name,)
            )
            affected = cursor.rowcount
            cursor.close()
            
            if affected > 0:
                logger.info(f"Deleted overlord company: database={database_name}")
            return affected > 0
    
    def get_all(self, limit: int = 50_000) -> list[dict[str, Any]]:
        """Get all company records from the overlord table.

        Returns all rows as dictionaries. For tables < 15k rows,
        this is the preferred approach — pagination/filtering/sorting
        happens in Python to allow cross-database enrichment with
        local tracking data.

        Args:
            limit: Maximum rows to return. Defaults to 50,000 to prevent
                unbounded memory allocation on unexpectedly large tables.

        Returns:
            List of rows as dicts (up to `limit` rows)
        """
        _validate_table_name(self._table)
        with self._conn.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"SELECT * FROM {self._table} ORDER BY `companyID` ASC LIMIT %s",
                (limit,),
            )
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows]

    def get_paginated(
        self,
        *,
        filters: dict[str, str] | None = None,
        sort_column: str = "companyID",
        sort_dir: str = "ASC",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get paginated company records with SQL-side filtering and sorting.

        Args:
            filters: Column→value substring filters (applied as ``LIKE %val%``).
            sort_column: Column to sort by (validated against allowlist).
            sort_dir: ``ASC`` or ``DESC``.
            offset: Number of rows to skip.
            limit: Maximum rows to return.

        Returns:
            Tuple of ``(rows, total_count)`` where *total_count* reflects
            the filtered (pre-pagination) row count.
        """
        _validate_table_name(self._table)

        # Validate sort direction
        sort_dir = sort_dir.upper()
        if sort_dir not in ("ASC", "DESC"):
            sort_dir = "ASC"

        # Build WHERE clause from filters
        where_clauses: list[str] = []
        params: list[Any] = []
        if filters:
            for col, val in filters.items():
                if col not in _VALID_COLUMNS:
                    continue
                where_clauses.append(f"`{col}` LIKE %s")
                params.append(f"%{val}%")

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Validate sort_column — use companyID as fallback for unknown columns
        if sort_column not in _VALID_COLUMNS:
            sort_column = "companyID"

        with self._conn.connection() as conn:
            cursor = conn.cursor(dictionary=True)

            # Count query
            cursor.execute(
                f"SELECT COUNT(*) AS cnt FROM {self._table}{where_sql}",
                params,
            )
            count_row = cursor.fetchone()
            total = int(count_row["cnt"]) if count_row else 0  # type: ignore[index]

            # Data query
            cursor.execute(
                f"SELECT * FROM {self._table}{where_sql} "
                f"ORDER BY `{sort_column}` {sort_dir} LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows], total

    def get_by_id(self, company_id: int) -> dict[str, Any] | None:
        """Get a single company record by companyID.
        
        Args:
            company_id: The companyID primary key
            
        Returns:
            Row as dict, or None if not found
        """
        _validate_table_name(self._table)
        with self._conn.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                f"SELECT * FROM {self._table} WHERE `companyID` = %s",
                (company_id,)
            )
            row = cursor.fetchone()
            cursor.close()
            return dict(row) if row else None
    
    def update_by_id(self, company_id: int, data: dict[str, Any]) -> bool:
        """Update a company record by companyID.
        
        Args:
            company_id: The companyID primary key
            data: Column name -> value mapping (what to update)
            
        Returns:
            True if row was updated, False if not found
            
        Raises:
            ValueError: If any column name is not in the allowlist
        """
        if not data:
            return False
        
        data = self._filter_to_real_columns(data)
        if not data:
            return False
        
        _validate_table_name(self._table)
        columns = list(data.keys())
        _validate_column_names(columns)
        
        set_clauses = ", ".join([f"`{k}` = %s" for k in columns])
        values = list(data.values()) + [company_id]
        
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE {self._table} SET {set_clauses} WHERE `companyID` = %s",
                tuple(values)
            )
            affected = cursor.rowcount
            cursor.close()
            
            if affected > 0:
                logger.info(f"Updated overlord company by ID: companyID={company_id}")
            return affected > 0
    
    def delete_by_id(self, company_id: int) -> bool:
        """Delete a company record by companyID.
        
        Args:
            company_id: The companyID primary key
            
        Returns:
            True if row was deleted, False if not found
        """
        _validate_table_name(self._table)
        with self._conn.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"DELETE FROM {self._table} WHERE `companyID` = %s",
                (company_id,)
            )
            affected = cursor.rowcount
            cursor.close()
            
            if affected > 0:
                logger.info(f"Deleted overlord company by ID: companyID={company_id}")
            return affected > 0
    
    def find_by_subdomain(
        self,
        subdomain: str,
        exclude_database: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find companies using a specific subdomain.
        
        Used for duplicate detection before sync.
        
        Args:
            subdomain: Subdomain to search for.
            exclude_database: Database name to exclude from results (the current record).
            
        Returns:
            List of matching rows with companyID, database, subdomain, dbHost.
        """
        with self._conn.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            if exclude_database:
                cursor.execute(
                    f"SELECT `companyID`, `database`, `subdomain`, `dbHost` "
                    f"FROM {self._table} WHERE `subdomain` = %s AND `database` != %s",
                    (subdomain, exclude_database),
                )
            else:
                cursor.execute(
                    f"SELECT `companyID`, `database`, `subdomain`, `dbHost` "
                    f"FROM {self._table} WHERE `subdomain` = %s",
                    (subdomain,),
                )
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows]


# =============================================================================
# Overlord Tracking Repository (Local Database)
# =============================================================================


class OverlordTrackingRepository:
    """Repository for local overlord_tracking table.
    
    Tracks which overlord.companies rows pullDB is managing.
    This is in our pulldb_service database (not overlord).
    """
    
    def __init__(self, pool: MySQLPool) -> None:
        """Initialize repository.
        
        Args:
            pool: MySQL pool for pulldb_service database
        """
        self.pool = pool
    
    def get(self, database_name: str) -> OverlordTracking | None:
        """Get tracking record by database name.
        
        Args:
            database_name: Database name to look up
            
        Returns:
            OverlordTracking if found, None otherwise
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """SELECT * FROM overlord_tracking WHERE database_name = %s""",
                (database_name,)
            )
            row = cursor.fetchone()
            cursor.close()
            
            if not row:
                return None
            return self._row_to_tracking(row)
    
    def get_by_job_id(self, job_id: str) -> OverlordTracking | None:
        """Get tracking record by job ID.
        
        Args:
            job_id: Job UUID
            
        Returns:
            OverlordTracking if found, None otherwise
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """SELECT * FROM overlord_tracking 
                   WHERE job_id = %s AND status IN ('claimed', 'synced')""",
                (job_id,)
            )
            row = cursor.fetchone()
            cursor.close()
            
            if not row:
                return None
            return self._row_to_tracking(row)
    
    def create(
        self,
        database_name: str,
        job_id: str,
        job_target: str,
        created_by: str,
        row_existed_before: bool = False,
        previous_dbhost: str | None = None,
        previous_dbhost_read: str | None = None,
        previous_snapshot: dict[str, Any] | None = None,
        company_id: int | None = None,
    ) -> int:
        """Create a new tracking record (claim).
        
        Args:
            database_name: Database name being claimed
            job_id: Job UUID
            job_target: Copy of job.target
            created_by: User initiating the claim
            row_existed_before: Whether overlord row already existed
            previous_dbhost: Original dbHost (if row existed)
            previous_dbhost_read: Original dbHostRead (if row existed)
            previous_snapshot: Full row backup (if row existed)
            company_id: Overlord companyID (if row existed)
            
        Returns:
            Tracking record ID

        Raises:
            OverlordAlreadyClaimedError: If another job holds an active claim
        """
        snapshot_json = json.dumps(previous_snapshot) if previous_snapshot else None
        
        with self.pool.transaction() as conn:
            cursor = conn.cursor()
            
            # Lock any existing row to prevent concurrent claim races (G1)
            cursor.execute(
                "SELECT job_id, status FROM overlord_tracking "
                "WHERE database_name = %s FOR UPDATE",
                (database_name,),
            )
            existing = cursor.fetchone()
            
            if existing:
                existing_job_id, existing_status = existing
                # Reject if actively claimed by a different job.
                # Raising here triggers transaction rollback, which
                # releases the FOR UPDATE lock automatically.
                if existing_status != "released" and existing_job_id != job_id:
                    cursor.close()
                    raise OverlordAlreadyClaimedError(
                        f"Database '{database_name}' is already claimed "
                        f"by job {str(existing_job_id)}"
                    )
                # Re-claim: update the existing released/same-job row
                cursor.execute(
                    """UPDATE overlord_tracking SET
                        job_id = %s, job_target = %s, created_by = %s,
                        status = 'claimed',
                        row_existed_before = %s, previous_dbhost = %s,
                        previous_dbhost_read = %s, previous_snapshot = %s,
                        company_id = %s, released_at = NULL
                    WHERE database_name = %s""",
                    (
                        job_id, job_target, created_by,
                        row_existed_before, previous_dbhost, previous_dbhost_read,
                        snapshot_json, company_id, database_name,
                    ),
                )
            else:
                # Fresh insert — no existing record
                cursor.execute(
                    """INSERT INTO overlord_tracking (
                        database_name, job_id, job_target, created_by, status,
                        row_existed_before, previous_dbhost, previous_dbhost_read,
                        previous_snapshot, company_id
                    ) VALUES (%s, %s, %s, %s, 'claimed', %s, %s, %s, %s, %s)""",
                    (
                        database_name, job_id, job_target, created_by,
                        row_existed_before, previous_dbhost, previous_dbhost_read,
                        snapshot_json, company_id,
                    ),
                )
            
            record_id = cursor.lastrowid or 0
            # transaction() auto-commits on successful exit
            cursor.close()
            
            logger.info(f"Created overlord tracking: {database_name} -> job {job_id}")
            return record_id
    
    def update_synced(
        self,
        database_name: str,
        current_dbhost: str,
        current_dbhost_read: str | None = None,
        company_id: int | None = None,
        current_subdomain: str | None = None,
    ) -> bool:
        """Mark tracking as synced with current values.
        
        Args:
            database_name: Database name
            current_dbhost: dbHost value written to overlord
            current_dbhost_read: dbHostRead value written to overlord
            company_id: Overlord companyID (for new rows)
            current_subdomain: Subdomain value written to overlord
            
        Returns:
            True if updated, False if not found
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE overlord_tracking
                   SET status = 'synced',
                       current_dbhost = %s,
                       current_dbhost_read = %s,
                       current_subdomain = %s,
                       company_id = COALESCE(%s, company_id)
                   WHERE database_name = %s AND status IN ('claimed', 'synced')""",
                (current_dbhost, current_dbhost_read, current_subdomain, company_id, database_name)
            )
            affected = cursor.rowcount
            conn.commit()
            cursor.close()
            return affected > 0
    
    def update_released(self, database_name: str, expected_job_id: str | None = None) -> bool:
        """Mark tracking as released.
        
        Args:
            database_name: Database name
            expected_job_id: If provided, only release if job_id matches (optimistic locking)
            
        Returns:
            True if updated, False if not found or job_id mismatch
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            if expected_job_id:
                cursor.execute(
                    """UPDATE overlord_tracking
                       SET status = 'released', released_at = NOW()
                       WHERE database_name = %s 
                         AND job_id = %s
                         AND status IN ('claimed', 'synced')""",
                    (database_name, expected_job_id)
                )
            else:
                cursor.execute(
                    """UPDATE overlord_tracking
                       SET status = 'released', released_at = NOW()
                       WHERE database_name = %s AND status IN ('claimed', 'synced')""",
                    (database_name,)
                )
            affected = cursor.rowcount
            conn.commit()
            cursor.close()
            
            if affected > 0:
                logger.info(f"Released overlord tracking: {database_name}")
            return affected > 0
    
    def list_active(self) -> list[OverlordTracking]:
        """List all active (claimed or synced) tracking records.
        
        Returns:
            List of active tracking records
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """SELECT * FROM overlord_tracking 
                   WHERE status IN ('claimed', 'synced')
                   ORDER BY created_at DESC"""
            )
            rows = cursor.fetchall()
            cursor.close()
            return [self._row_to_tracking(row) for row in rows]

    def delete_by_database_name(self, database_name: str) -> bool:
        """Hard-delete a tracking record by database name.

        Used for orphan cleanup when the remote overlord company is removed.

        Args:
            database_name: Database name to remove.

        Returns:
            True if a row was deleted, False if not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM overlord_tracking WHERE database_name = %s",
                (database_name,),
            )
            affected = cursor.rowcount
            conn.commit()
            cursor.close()
            if affected > 0:
                logger.info("Deleted orphaned tracking record: %s", database_name)
            return affected > 0
    
    def _row_to_tracking(self, row: dict[str, Any]) -> OverlordTracking:
        """Convert database row to OverlordTracking."""
        snapshot = None
        if row.get("previous_snapshot"):
            try:
                snapshot = json.loads(row["previous_snapshot"])
            except json.JSONDecodeError:
                pass
        
        return OverlordTracking(
            id=row["id"],
            database_name=row["database_name"],
            company_id=row.get("company_id"),
            job_id=row["job_id"],
            job_target=row["job_target"],
            created_by=row["created_by"],
            status=OverlordTrackingStatus(row["status"]),
            row_existed_before=bool(row["row_existed_before"]),
            previous_dbhost=row.get("previous_dbhost"),
            previous_dbhost_read=row.get("previous_dbhost_read"),
            previous_snapshot=snapshot,
            current_dbhost=row.get("current_dbhost"),
            current_dbhost_read=row.get("current_dbhost_read"),
            current_subdomain=row.get("current_subdomain"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            released_at=row.get("released_at"),
        )
