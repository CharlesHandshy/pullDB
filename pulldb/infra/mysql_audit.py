"""MySQL audit repository for pullDB.

Implements the AuditRepository class for recording and querying
audit log entries.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from pulldb.infra.mysql_pool import (
    MySQLPool,
    TypedDictCursor,
    TypedTupleCursor,
)

logger = logging.getLogger(__name__)

class AuditRepository:
    """Repository for audit log operations.

    Records manager/admin actions for transparency and compliance.
    All users can view audit logs.
    """

    def __init__(self, pool: MySQLPool) -> None:
        """Initialize audit repository.

        Args:
            pool: MySQL connection pool.
        """
        self.pool = pool

    def log_action(
        self,
        actor_user_id: str,
        action: str,
        target_user_id: str | None = None,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Record an audit log entry.

        Args:
            actor_user_id: User ID of who performed the action.
            action: Action type (e.g., 'submit_for_user', 'create_user', 'cancel_job').
            target_user_id: User ID of the user affected (if applicable).
            detail: Human-readable detail of the action.
            context: Additional JSON context data.

        Returns:
            Audit log ID.
        """

        audit_id = str(uuid.uuid4())
        context_json = json.dumps(context) if context else None

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                """
                INSERT INTO audit_logs
                    (audit_id, actor_user_id, target_user_id, action, detail, context_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))
                """,
                (audit_id, actor_user_id, target_user_id, action, detail, context_json),
            )
            conn.commit()
        return audit_id

    def get_audit_logs(
        self,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve audit log entries with optional filtering.

        Args:
            actor_user_id: Filter by actor (who did the action).
            target_user_id: Filter by target user (who was affected).
            action: Filter by action type.
            limit: Maximum number of results.
            offset: Offset for pagination.

        Returns:
            List of audit log dictionaries with user details.
        """

        conditions = []
        params: list[Any] = []

        if actor_user_id:
            conditions.append("a.actor_user_id = %s")
            params.append(actor_user_id)
        if target_user_id:
            conditions.append("a.target_user_id = %s")
            params.append(target_user_id)
        if action:
            conditions.append("a.action = %s")
            params.append(action)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self.pool.connection() as conn:
            cursor = TypedDictCursor(conn.cursor(dictionary=True))
            cursor.execute(
                f"""
                SELECT 
                    a.audit_id, a.actor_user_id, a.target_user_id, a.action,
                    a.detail, a.context_json, a.created_at,
                    actor.username as actor_username,
                    target.username as target_username
                FROM audit_logs a
                LEFT JOIN auth_users actor ON a.actor_user_id = actor.user_id
                LEFT JOIN auth_users target ON a.target_user_id = target.user_id
                WHERE {where_clause}
                ORDER BY a.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = cursor.fetchall()

            # Parse context_json for each row
            results = []
            for row in rows:
                result = dict(row)
                if result.get("context_json"):
                    result["context"] = json.loads(result["context_json"])
                else:
                    result["context"] = {}
                del result["context_json"]
                results.append(result)
            return results

    def get_audit_logs_count(
        self,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        action: str | None = None,
    ) -> int:
        """Count audit log entries with optional filtering.

        Args:
            actor_user_id: Filter by actor (who did the action).
            target_user_id: Filter by target user (who was affected).
            action: Filter by action type.

        Returns:
            Count of matching audit log entries.
        """
        conditions = []
        params: list[Any] = []

        if actor_user_id:
            conditions.append("actor_user_id = %s")
            params.append(actor_user_id)
        if target_user_id:
            conditions.append("target_user_id = %s")
            params.append(target_user_id)
        if action:
            conditions.append("action = %s")
            params.append(action)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self.pool.connection() as conn:
            cursor = TypedTupleCursor(conn.cursor())
            cursor.execute(
                f"SELECT COUNT(*) FROM audit_logs WHERE {where_clause}",
                params,
            )
            result = cursor.fetchone()
            return int(result[0]) if result else 0


