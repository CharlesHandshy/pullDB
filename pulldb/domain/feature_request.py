from __future__ import annotations

"""
Feature Request Domain Models

HCA Layer: entities (pulldb/domain/)
Pydantic models for feature requests and votes.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FeatureRequestStatus(str, Enum):
    """Status of a feature request."""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    DECLINED = "declined"


# Primary admin UUID - only this user can change feature request status
PRIMARY_ADMIN_ID = "00000000-0000-0000-0000-000000000002"


class FeatureRequest(BaseModel):
    """Feature request submitted by a user."""
    request_id: str
    submitted_by_user_id: str
    title: str
    description: str | None = None
    status: FeatureRequestStatus = FeatureRequestStatus.OPEN
    vote_score: int = 0
    upvote_count: int = 0
    downvote_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    admin_response: str | None = None
    
    # Joined fields (from queries)
    submitted_by_username: str | None = None
    submitted_by_user_code: str | None = None
    user_vote: int | None = None  # Current user's vote: 1, -1, or None


class FeatureRequestCreate(BaseModel):
    """Input for creating a new feature request."""
    title: str = Field(..., min_length=5, max_length=200)
    description: str | None = Field(None, max_length=2000)


class FeatureRequestUpdate(BaseModel):
    """Admin input for updating a feature request."""
    status: FeatureRequestStatus | None = None
    admin_response: str | None = Field(None, max_length=2000)


class FeatureRequestVote(BaseModel):
    """A user's vote on a feature request."""
    vote_id: str
    request_id: str
    user_id: str
    vote_value: int  # 1 = upvote, -1 = downvote
    created_at: datetime


class VoteInput(BaseModel):
    """Input for casting a vote."""
    vote_value: int = Field(..., ge=-1, le=1)  # -1, 0, or 1


class FeatureRequestStats(BaseModel):
    """Statistics for feature requests."""
    total: int = 0
    open: int = 0
    in_progress: int = 0
    complete: int = 0
    declined: int = 0


class FeatureRequestNote(BaseModel):
    """A note on a feature request."""
    note_id: str
    request_id: str
    user_id: str
    note_text: str
    created_at: datetime
    # Joined fields
    username: str | None = None
    user_code: str | None = None


class NoteCreate(BaseModel):
    """Input for creating a note."""
    note_text: str = Field(..., min_length=1, max_length=2000)
