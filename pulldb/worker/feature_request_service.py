"""Feature Request Service.

Business logic for feature requests and voting.

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pulldb.domain.feature_request import (
    FeatureRequest,
    FeatureRequestCreate,
    FeatureRequestStats,
    FeatureRequestStatus,
    FeatureRequestUpdate,
)

if TYPE_CHECKING:
    from pulldb.infra.mysql import MySQLPool


logger = logging.getLogger(__name__)


class FeatureRequestService:
    """Service for managing feature requests and votes.
    
    Provides business logic for:
    - Creating and listing feature requests
    - Voting on requests (upvote/downvote)
    - Updating request status (admin only)
    """

    def __init__(self, db_pool: "MySQLPool") -> None:
        """Initialize feature request service.
        
        Args:
            db_pool: Database connection pool.
        """
        self.db_pool = db_pool

    async def get_stats(self) -> FeatureRequestStats:
        """Get feature request statistics."""
        query = """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) as open_count,
                SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_count,
                SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) as complete_count,
                SUM(CASE WHEN status = 'declined' THEN 1 ELSE 0 END) as declined_count
            FROM feature_requests
        """
        async with self.db_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query)
                row = await cur.fetchone()
                if row:
                    return FeatureRequestStats(
                        total=row[0] or 0,
                        open=row[1] or 0,
                        in_progress=row[2] or 0,
                        complete=row[3] or 0,
                        declined=row[4] or 0,
                    )
                return FeatureRequestStats()

    async def list_requests(
        self,
        current_user_id: str | None = None,
        status_filter: list[str] | None = None,
        sort_by: str = "vote_score",
        sort_order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[FeatureRequest], int]:
        """List feature requests with optional filtering.
        
        Args:
            current_user_id: If provided, includes the user's vote on each request.
            status_filter: Optional list of statuses to filter by.
            sort_by: Column to sort by (vote_score, created_at, status).
            sort_order: Sort direction (asc, desc).
            limit: Maximum results to return.
            offset: Number of results to skip.
            
        Returns:
            Tuple of (list of requests, total count).
        """
        # Build WHERE clause
        where_clauses = []
        params: list[Any] = []
        
        if status_filter:
            placeholders = ", ".join(["%s"] * len(status_filter))
            where_clauses.append(f"fr.status IN ({placeholders})")
            params.extend(status_filter)
        
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        
        # Validate sort column
        valid_sort_cols = {"vote_score", "created_at", "status", "title"}
        if sort_by not in valid_sort_cols:
            sort_by = "vote_score"
        sort_order = "DESC" if sort_order.lower() == "desc" else "ASC"
        
        # Count query
        count_query = f"""
            SELECT COUNT(*) FROM feature_requests fr {where_sql}
        """
        
        # Main query with user vote join
        vote_join = ""
        vote_select = "NULL as user_vote"
        if current_user_id:
            vote_join = """
                LEFT JOIN feature_request_votes v 
                    ON fr.request_id = v.request_id AND v.user_id = %s
            """
            vote_select = "v.vote_value as user_vote"
        
        query = f"""
            SELECT
                fr.request_id,
                fr.submitted_by_user_id,
                fr.title,
                fr.description,
                fr.status,
                fr.vote_score,
                fr.upvote_count,
                fr.downvote_count,
                fr.created_at,
                fr.updated_at,
                fr.completed_at,
                fr.admin_response,
                u.username as submitted_by_username,
                u.user_code as submitted_by_user_code,
                {vote_select}
            FROM feature_requests fr
            JOIN auth_users u ON fr.submitted_by_user_id = u.user_id
            {vote_join}
            {where_sql}
            ORDER BY fr.{sort_by} {sort_order}
            LIMIT %s OFFSET %s
        """
        
        async with self.db_pool.connection() as conn:
            async with conn.cursor() as cur:
                # Get total count
                await cur.execute(count_query, params)
                count_row = await cur.fetchone()
                total = count_row[0] if count_row else 0
                
                # Get requests
                query_params = []
                if current_user_id:
                    query_params.append(current_user_id)
                query_params.extend(params)
                query_params.extend([limit, offset])
                
                await cur.execute(query, query_params)
                rows = await cur.fetchall()
                
                requests = []
                for row in rows:
                    requests.append(FeatureRequest(
                        request_id=row[0],
                        submitted_by_user_id=row[1],
                        title=row[2],
                        description=row[3],
                        status=FeatureRequestStatus(row[4]),
                        vote_score=row[5],
                        upvote_count=row[6],
                        downvote_count=row[7],
                        created_at=row[8],
                        updated_at=row[9],
                        completed_at=row[10],
                        admin_response=row[11],
                        submitted_by_username=row[12],
                        submitted_by_user_code=row[13],
                        user_vote=row[14],
                    ))
                
                return requests, total

    async def get_request(
        self,
        request_id: str,
        current_user_id: str | None = None,
    ) -> FeatureRequest | None:
        """Get a single feature request by ID.
        
        Args:
            request_id: The request ID.
            current_user_id: If provided, includes the user's vote.
            
        Returns:
            The feature request or None if not found.
        """
        vote_join = ""
        vote_select = "NULL as user_vote"
        params: list[Any] = [request_id]
        
        if current_user_id:
            vote_join = """
                LEFT JOIN feature_request_votes v 
                    ON fr.request_id = v.request_id AND v.user_id = %s
            """
            vote_select = "v.vote_value as user_vote"
            params = [current_user_id, request_id]
        
        query = f"""
            SELECT
                fr.request_id,
                fr.submitted_by_user_id,
                fr.title,
                fr.description,
                fr.status,
                fr.vote_score,
                fr.upvote_count,
                fr.downvote_count,
                fr.created_at,
                fr.updated_at,
                fr.completed_at,
                fr.admin_response,
                u.username as submitted_by_username,
                u.user_code as submitted_by_user_code,
                {vote_select}
            FROM feature_requests fr
            JOIN auth_users u ON fr.submitted_by_user_id = u.user_id
            {vote_join}
            WHERE fr.request_id = %s
        """
        
        async with self.db_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
                
                if not row:
                    return None
                
                return FeatureRequest(
                    request_id=row[0],
                    submitted_by_user_id=row[1],
                    title=row[2],
                    description=row[3],
                    status=FeatureRequestStatus(row[4]),
                    vote_score=row[5],
                    upvote_count=row[6],
                    downvote_count=row[7],
                    created_at=row[8],
                    updated_at=row[9],
                    completed_at=row[10],
                    admin_response=row[11],
                    submitted_by_username=row[12],
                    submitted_by_user_code=row[13],
                    user_vote=row[14],
                )

    async def create_request(
        self,
        data: FeatureRequestCreate,
        user_id: str,
    ) -> FeatureRequest:
        """Create a new feature request.
        
        Args:
            data: The request data.
            user_id: ID of the user creating the request.
            
        Returns:
            The created feature request.
        """
        request_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        
        query = """
            INSERT INTO feature_requests (
                request_id, submitted_by_user_id, title, description,
                status, vote_score, upvote_count, downvote_count,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, 'open', 0, 0, 0, %s, %s)
        """
        
        async with self.db_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (
                    request_id,
                    user_id,
                    data.title,
                    data.description,
                    now,
                    now,
                ))
            await conn.commit()
        
        logger.info(f"Created feature request {request_id}: {data.title}")
        
        # Return the created request
        return await self.get_request(request_id, user_id)  # type: ignore

    async def update_request(
        self,
        request_id: str,
        data: FeatureRequestUpdate,
    ) -> FeatureRequest | None:
        """Update a feature request (admin only).
        
        Args:
            request_id: The request ID to update.
            data: The update data.
            
        Returns:
            The updated request or None if not found.
        """
        updates = []
        params: list[Any] = []
        
        if data.status is not None:
            updates.append("status = %s")
            params.append(data.status.value)
            
            # Set completed_at when marking complete/declined
            if data.status in (FeatureRequestStatus.COMPLETE, FeatureRequestStatus.DECLINED):
                updates.append("completed_at = %s")
                params.append(datetime.now(UTC))
            else:
                updates.append("completed_at = NULL")
        
        if data.admin_response is not None:
            updates.append("admin_response = %s")
            params.append(data.admin_response)
        
        if not updates:
            return await self.get_request(request_id)
        
        params.append(request_id)
        query = f"""
            UPDATE feature_requests
            SET {', '.join(updates)}
            WHERE request_id = %s
        """
        
        async with self.db_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                if cur.rowcount == 0:
                    return None
            await conn.commit()
        
        logger.info(f"Updated feature request {request_id}")
        return await self.get_request(request_id)

    async def vote(
        self,
        request_id: str,
        user_id: str,
        vote_value: int,
    ) -> FeatureRequest | None:
        """Cast or change a vote on a feature request.
        
        Args:
            request_id: The request ID to vote on.
            user_id: ID of the user voting.
            vote_value: 1 for upvote, -1 for downvote, 0 to remove vote.
            
        Returns:
            The updated request or None if not found.
        """
        if vote_value not in (-1, 0, 1):
            raise ValueError("vote_value must be -1, 0, or 1")
        
        async with self.db_pool.connection() as conn:
            async with conn.cursor() as cur:
                # Check if request exists
                await cur.execute(
                    "SELECT 1 FROM feature_requests WHERE request_id = %s",
                    (request_id,)
                )
                if not await cur.fetchone():
                    return None
                
                # Get existing vote
                await cur.execute(
                    """SELECT vote_value FROM feature_request_votes 
                       WHERE request_id = %s AND user_id = %s""",
                    (request_id, user_id)
                )
                existing = await cur.fetchone()
                old_vote = existing[0] if existing else 0
                
                if vote_value == 0:
                    # Remove vote
                    if existing:
                        await cur.execute(
                            """DELETE FROM feature_request_votes 
                               WHERE request_id = %s AND user_id = %s""",
                            (request_id, user_id)
                        )
                        delta = -old_vote
                    else:
                        delta = 0  # No vote to remove
                elif existing:
                    # Update existing vote
                    if vote_value != old_vote:
                        await cur.execute(
                            """UPDATE feature_request_votes 
                               SET vote_value = %s, created_at = %s
                               WHERE request_id = %s AND user_id = %s""",
                            (vote_value, datetime.now(UTC), request_id, user_id)
                        )
                        delta = vote_value - old_vote
                    else:
                        delta = 0  # Same vote, no change
                else:
                    # New vote
                    vote_id = str(uuid.uuid4())
                    await cur.execute(
                        """INSERT INTO feature_request_votes 
                           (vote_id, request_id, user_id, vote_value, created_at)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (vote_id, request_id, user_id, vote_value, datetime.now(UTC))
                    )
                    delta = vote_value
                
                # Update aggregates
                if delta != 0:
                    up_delta = 1 if delta > 0 else (-1 if old_vote == 1 else 0)
                    down_delta = 1 if delta < 0 else (-1 if old_vote == -1 else 0)
                    
                    # Actually calculate correct deltas based on state change
                    up_delta = 0
                    down_delta = 0
                    
                    if old_vote == 1 and vote_value != 1:
                        up_delta = -1
                    if old_vote == -1 and vote_value != -1:
                        down_delta = -1
                    if vote_value == 1 and old_vote != 1:
                        up_delta += 1
                    if vote_value == -1 and old_vote != -1:
                        down_delta += 1
                    
                    await cur.execute(
                        """UPDATE feature_requests 
                           SET vote_score = vote_score + %s,
                               upvote_count = upvote_count + %s,
                               downvote_count = downvote_count + %s
                           WHERE request_id = %s""",
                        (delta, up_delta, down_delta, request_id)
                    )
            
            await conn.commit()
        
        return await self.get_request(request_id, user_id)

    async def delete_request(self, request_id: str) -> bool:
        """Delete a feature request (admin only).
        
        Args:
            request_id: The request ID to delete.
            
        Returns:
            True if deleted, False if not found.
        """
        async with self.db_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM feature_requests WHERE request_id = %s",
                    (request_id,)
                )
                deleted = cur.rowcount > 0
            await conn.commit()
        
        if deleted:
            logger.info(f"Deleted feature request {request_id}")
        return deleted
