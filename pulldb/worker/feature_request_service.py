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
    FeatureRequestNote,
    FeatureRequestStats,
    FeatureRequestStatus,
    FeatureRequestUpdate,
    NoteCreate,
)
from pulldb.infra.mysql import TypedDictCursor, TypedTupleCursor

if TYPE_CHECKING:
    from pulldb.infra.mysql import MySQLPool


logger = logging.getLogger(__name__)

# Sort column constants for feature request listing
SORT_COLUMN_VOTE_SCORE = "vote_score"
SORT_COLUMN_CREATED_AT = "created_at"
SORT_COLUMN_STATUS = "status"
SORT_COLUMN_TITLE = "title"
VALID_SORT_COLUMNS = frozenset({
    SORT_COLUMN_VOTE_SCORE,
    SORT_COLUMN_CREATED_AT,
    SORT_COLUMN_STATUS,
    SORT_COLUMN_TITLE,
})
DEFAULT_SORT_COLUMN = SORT_COLUMN_VOTE_SCORE
DEFAULT_LIST_LIMIT = 100


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
        with self.db_pool.connection() as conn:
            cur = TypedTupleCursor(conn.cursor())
            try:
                cur.execute(query)
                row = cur.fetchone()
                if row:
                    return FeatureRequestStats(
                        total=row[0] or 0,
                        open=row[1] or 0,
                        in_progress=row[2] or 0,
                        complete=row[3] or 0,
                        declined=row[4] or 0,
                    )
                return FeatureRequestStats()
            finally:
                cur.close()

    async def get_distinct_values(self, column: str) -> list[str]:
        """Get distinct values for a column (for filter dropdowns).
        
        Args:
            column: Column name - 'status' or 'submitted_by_user_code'.
            
        Returns:
            List of distinct values sorted alphabetically.
        """
        if column == "status":
            # Return all possible status values in logical order
            return [s.value for s in FeatureRequestStatus]
        elif column == "submitted_by_user_code":
            query = """
                SELECT DISTINCT u.user_code
                FROM feature_requests fr
                JOIN auth_users u ON fr.submitted_by_user_id = u.user_id
                WHERE u.user_code IS NOT NULL
                ORDER BY u.user_code ASC
            """
            with self.db_pool.connection() as conn:
                cur = TypedTupleCursor(conn.cursor())
                try:
                    cur.execute(query)
                    return [row[0] for row in cur.fetchall()]
                finally:
                    cur.close()
        else:
            return []

    async def list_requests(
        self,
        current_user_id: str | None = None,
        status_filter: list[str] | None = None,
        user_filter: list[str] | None = None,
        title_filter: str | None = None,
        sort_by: str = DEFAULT_SORT_COLUMN,
        sort_order: str = "desc",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> tuple[list[FeatureRequest], int]:
        """List feature requests with optional filtering.
        
        Args:
            current_user_id: If provided, includes the user's vote on each request.
            status_filter: Optional list of statuses to filter by.
            user_filter: Optional list of user_codes to filter by.
            title_filter: Optional title search (supports * wildcards).
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
        
        if user_filter:
            placeholders = ", ".join(["%s"] * len(user_filter))
            where_clauses.append(f"u.user_code IN ({placeholders})")
            params.extend(user_filter)
        
        if title_filter:
            # Convert * wildcards to SQL % wildcards for LIKE query
            like_pattern = title_filter.replace("*", "%")
            if "%" not in like_pattern:
                # No wildcards - add implicit contains search
                like_pattern = f"%{like_pattern}%"
            where_clauses.append("fr.title LIKE %s")
            params.append(like_pattern)
        
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        
        # Validate sort column
        if sort_by not in VALID_SORT_COLUMNS:
            sort_by = DEFAULT_SORT_COLUMN
        sort_order = "DESC" if sort_order.lower() == "desc" else "ASC"
        
        # Count query - needs user join if filtering by user
        if user_filter:
            count_query = f"""
                SELECT COUNT(*) FROM feature_requests fr
                JOIN auth_users u ON fr.submitted_by_user_id = u.user_id
                {where_sql}
            """
        else:
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
        
        with self.db_pool.connection() as conn:
            cur = TypedTupleCursor(conn.cursor())
            try:
                # Get total count
                cur.execute(count_query, params)
                count_row = cur.fetchone()
                total = count_row[0] if count_row else 0
                
                # Get requests
                query_params = []
                if current_user_id:
                    query_params.append(current_user_id)
                query_params.extend(params)
                query_params.extend([limit, offset])
                
                cur.execute(query, query_params)
                rows = cur.fetchall()
                
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
            finally:
                cur.close()

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
        
        with self.db_pool.connection() as conn:
            cur = TypedTupleCursor(conn.cursor())
            try:
                cur.execute(query, params)
                row = cur.fetchone()
                
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
            finally:
                cur.close()

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
        
        with self.db_pool.connection() as conn:
            cur = TypedTupleCursor(conn.cursor())
            try:
                cur.execute(query, (
                    request_id,
                    user_id,
                    data.title,
                    data.description,
                    now,
                    now,
                ))
                conn.commit()
            finally:
                cur.close()
        
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
        
        clear_votes = False
        if data.status is not None:
            updates.append("status = %s")
            params.append(data.status.value)
            
            # Set completed_at when marking complete/declined
            if data.status in (FeatureRequestStatus.COMPLETE, FeatureRequestStatus.DECLINED):
                updates.append("completed_at = %s")
                params.append(datetime.now(UTC))
                # Clear votes when completing - allows request to fall down the list
                clear_votes = True
            else:
                updates.append("completed_at = NULL")
        
        if data.admin_response is not None:
            updates.append("admin_response = %s")
            params.append(data.admin_response)
        
        if not updates:
            return await self.get_request(request_id)
        
        # If clearing votes, also reset vote counts
        if clear_votes:
            updates.extend(["vote_score = 0", "upvote_count = 0", "downvote_count = 0"])
        
        params.append(request_id)
        query = f"""
            UPDATE feature_requests
            SET {', '.join(updates)}
            WHERE request_id = %s
        """
        
        with self.db_pool.connection() as conn:
            cur = TypedTupleCursor(conn.cursor())
            try:
                cur.execute(query, params)
                if cur.rowcount == 0:
                    return None
                
                # Clear all votes for this request so users can vote on other requests
                if clear_votes:
                    cur.execute(
                        "DELETE FROM feature_request_votes WHERE request_id = %s",
                        (request_id,)
                    )
                    logger.info(f"Cleared votes for completed request {request_id}")
                
                conn.commit()
            finally:
                cur.close()
        
        logger.info(f"Updated feature request {request_id}")
        return await self.get_request(request_id)

    async def vote(
        self,
        request_id: str,
        user_id: str,
        vote_value: int,
    ) -> FeatureRequest | None:
        """Cast or change a vote on a feature request.
        
        Users can only vote for ONE request at a time. Voting for a new request
        automatically removes any previous vote from other requests.
        
        Args:
            request_id: The request ID to vote on.
            user_id: ID of the user voting.
            vote_value: 1 to vote, 0 to remove vote.
            
        Returns:
            The updated request or None if not found.
            
        Raises:
            ValueError: If vote_value is not 0 or 1.
        """
        if vote_value not in (0, 1):
            raise ValueError("vote_value must be 0 or 1")
        
        with self.db_pool.connection() as conn:
            cur = TypedTupleCursor(conn.cursor())
            try:
                # Check if request exists
                cur.execute(
                    "SELECT 1 FROM feature_requests WHERE request_id = %s",
                    (request_id,)
                )
                if not cur.fetchone():
                    return None
                
                # Find user's existing vote (on ANY request)
                cur.execute(
                    """SELECT request_id, vote_value FROM feature_request_votes 
                       WHERE user_id = %s""",
                    (user_id,)
                )
                existing = cur.fetchone()
                old_request_id = existing[0] if existing else None
                old_vote = existing[1] if existing else 0
                
                if vote_value == 0:
                    # Remove vote from this request
                    if existing and old_request_id == request_id:
                        cur.execute(
                            """DELETE FROM feature_request_votes 
                               WHERE user_id = %s""",
                            (user_id,)
                        )
                        # Decrement vote count on this request
                        cur.execute(
                            """UPDATE feature_requests 
                               SET vote_score = vote_score - 1,
                                   upvote_count = upvote_count - 1
                               WHERE request_id = %s""",
                            (request_id,)
                        )
                elif existing:
                    # User has existing vote somewhere
                    if old_request_id == request_id:
                        # Already voted for this request - no change needed
                        pass
                    else:
                        # Move vote from old request to new request
                        # Update the vote record to point to new request
                        cur.execute(
                            """UPDATE feature_request_votes 
                               SET request_id = %s, created_at = %s
                               WHERE user_id = %s""",
                            (request_id, datetime.now(UTC), user_id)
                        )
                        # Decrement old request's vote count
                        cur.execute(
                            """UPDATE feature_requests 
                               SET vote_score = vote_score - 1,
                                   upvote_count = upvote_count - 1
                               WHERE request_id = %s""",
                            (old_request_id,)
                        )
                        # Increment new request's vote count
                        cur.execute(
                            """UPDATE feature_requests 
                               SET vote_score = vote_score + 1,
                                   upvote_count = upvote_count + 1
                               WHERE request_id = %s""",
                            (request_id,)
                        )
                else:
                    # New vote - user hasn't voted before
                    vote_id = str(uuid.uuid4())
                    cur.execute(
                        """INSERT INTO feature_request_votes 
                           (vote_id, request_id, user_id, vote_value, created_at)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (vote_id, request_id, user_id, 1, datetime.now(UTC))
                    )
                    # Increment vote count
                    cur.execute(
                        """UPDATE feature_requests 
                           SET vote_score = vote_score + 1,
                               upvote_count = upvote_count + 1
                           WHERE request_id = %s""",
                        (request_id,)
                    )
                
                conn.commit()
            finally:
                cur.close()
        
        return await self.get_request(request_id, user_id)

    async def delete_request(self, request_id: str) -> bool:
        """Delete a feature request (admin only).
        
        Args:
            request_id: The request ID to delete.
            
        Returns:
            True if deleted, False if not found.
        """
        with self.db_pool.connection() as conn:
            cur = TypedTupleCursor(conn.cursor())
            try:
                cur.execute(
                    "DELETE FROM feature_requests WHERE request_id = %s",
                    (request_id,)
                )
                deleted = cur.rowcount > 0
                conn.commit()
            finally:
                cur.close()
        
        if deleted:
            logger.info(f"Deleted feature request {request_id}")
        return deleted

    # =========================================================================
    # Notes Methods
    # =========================================================================

    async def list_notes(
        self,
        request_id: str,
    ) -> list[FeatureRequestNote]:
        """List all notes for a feature request.
        
        Args:
            request_id: The feature request ID.
            
        Returns:
            List of notes ordered by creation date (newest first).
        """
        query = """
            SELECT
                n.note_id,
                n.request_id,
                n.user_id,
                n.note_text,
                n.created_at,
                u.username,
                u.user_code
            FROM feature_request_notes n
            JOIN auth_users u ON n.user_id = u.user_id
            WHERE n.request_id = %s
            ORDER BY n.created_at DESC
        """
        
        with self.db_pool.connection() as conn:
            cur = TypedTupleCursor(conn.cursor())
            try:
                cur.execute(query, (request_id,))
                rows = cur.fetchall()
                
                return [
                    FeatureRequestNote(
                        note_id=row[0],
                        request_id=row[1],
                        user_id=row[2],
                        note_text=row[3],
                        created_at=row[4],
                        username=row[5],
                        user_code=row[6],
                    )
                    for row in rows
                ]
            finally:
                cur.close()

    async def add_note(
        self,
        request_id: str,
        user_id: str,
        data: NoteCreate,
    ) -> FeatureRequestNote | None:
        """Add a note to a feature request.
        
        Args:
            request_id: The feature request ID.
            user_id: The user adding the note.
            data: The note data.
            
        Returns:
            The created note or None if request not found.
        """
        note_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        
        with self.db_pool.connection() as conn:
            cur = TypedTupleCursor(conn.cursor())
            try:
                # Check if request exists
                cur.execute(
                    "SELECT 1 FROM feature_requests WHERE request_id = %s",
                    (request_id,)
                )
                if not cur.fetchone():
                    return None
                
                # Insert note
                cur.execute(
                    """INSERT INTO feature_request_notes 
                       (note_id, request_id, user_id, note_text, created_at)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (note_id, request_id, user_id, data.note_text, now)
                )
                conn.commit()
                
                # Get user info
                cur.execute(
                    "SELECT username, user_code FROM auth_users WHERE user_id = %s",
                    (user_id,)
                )
                user_row = cur.fetchone()
                
                return FeatureRequestNote(
                    note_id=note_id,
                    request_id=request_id,
                    user_id=user_id,
                    note_text=data.note_text,
                    created_at=now,
                    username=user_row[0] if user_row else None,
                    user_code=user_row[1] if user_row else None,
                )
            finally:
                cur.close()

    async def delete_note(
        self,
        note_id: str,
        user_id: str | None = None,
    ) -> bool:
        """Delete a note.
        
        Args:
            note_id: The note ID to delete.
            user_id: If provided, only delete if owned by this user.
                     If None, delete regardless of owner (admin use).
            
        Returns:
            True if deleted, False if not found or not authorized.
        """
        with self.db_pool.connection() as conn:
            cur = TypedTupleCursor(conn.cursor())
            try:
                if user_id:
                    # Only delete if owned by user
                    cur.execute(
                        "DELETE FROM feature_request_notes WHERE note_id = %s AND user_id = %s",
                        (note_id, user_id)
                    )
                else:
                    # Admin delete - any note
                    cur.execute(
                        "DELETE FROM feature_request_notes WHERE note_id = %s",
                        (note_id,)
                    )
                deleted = cur.rowcount > 0
                conn.commit()
            finally:
                cur.close()
        
        return deleted
