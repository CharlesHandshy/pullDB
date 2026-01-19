# Feature Requests System

> **Version**: 1.0.1 | **Last Updated**: January 2026

The Feature Requests system allows users to submit, vote on, and track feature requests for pullDB.

---

## Table of Contents

1. [Overview](#overview)
2. [User Workflow](#user-workflow)
3. [Admin Workflow](#admin-workflow)
4. [Status Lifecycle](#status-lifecycle)
5. [API Reference](#api-reference)
6. [Web UI Guide](#web-ui-guide)

---

## Overview

### Purpose

- Allow users to suggest new features
- Enable community voting to prioritize requests
- Provide transparency into product roadmap
- Track feature progress from idea to completion

### Key Features

- **Submit requests**: Any authenticated user can submit
- **Vote system**: Users vote to show interest (one vote per user per request)
- **Status tracking**: Track progress through lifecycle
- **Admin notes**: Admins can add notes and status updates
- **Ownership**: Users can edit/delete their own requests

---

## User Workflow

### Submitting a Request

**Web UI:** Feature Requests → **New Request**

1. Click "New Request"
2. Enter a clear, descriptive title
3. Provide detailed description (what, why, use case)
4. Submit

**API:**
```bash
curl -X POST http://localhost:8080/api/feature-requests \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Export job history to CSV",
    "description": "Allow exporting filtered job history..."
  }'
```

### Voting

- Click the **Vote** button on any request
- Your vote increases the vote count
- Click again to remove your vote
- Vote count helps admins prioritize

### Managing Your Requests

**Edit:** Click edit icon on your request to modify title/description.

**Delete:** Click delete icon to remove (only if you own it).

### Viewing Requests

**Filters available:**
- Status: new, under-review, planned, in-progress, done, declined
- My Requests: Show only requests you created

---

## Admin Workflow

### Reviewing Requests

**Web UI:** Feature Requests (admin view shows all actions)

1. Review new requests regularly
2. Change status to `under-review` when considering
3. Add notes to explain decisions or ask for clarification

### Managing Status

Admins can change status to:

| Status | Meaning |
|--------|---------|
| `new` | Just submitted, not reviewed |
| `under-review` | Being considered |
| `planned` | Accepted for future implementation |
| `in-progress` | Currently being worked on |
| `done` | Implemented and released |
| `declined` | Not accepted (with reason in notes) |

### Adding Admin Notes

Notes provide communication channel:
- Acknowledge receipt
- Ask clarifying questions
- Explain decisions
- Announce completion

**API:**
```bash
curl -X PATCH http://localhost:8080/api/feature-requests/{id} \
  -H "Content-Type: application/json" \
  -d '{
    "status": "planned",
    "admin_note": "Great idea! Targeting v1.2 release."
  }'
```

### Deleting Requests

Admins can delete any request (e.g., spam, duplicates, inappropriate).

---

## Status Lifecycle

```
   ┌─────────────────────────────────────────────────────────────┐
   │                                                             │
   │    new ──► under-review ──┬──► planned ──► in-progress ──► done
   │                           │
   │                           └──► declined
   │
   └─────────────────────────────────────────────────────────────┘
```

### Status Definitions

| Status | Description | Who Changes |
|--------|-------------|-------------|
| **new** | Initial state after submission | Auto |
| **under-review** | Admin is evaluating | Admin |
| **planned** | Approved for implementation | Admin |
| **in-progress** | Active development | Admin |
| **done** | Completed and released | Admin |
| **declined** | Not accepted | Admin |

### Best Practices

1. Move to `under-review` quickly so users know it's seen
2. Add notes when declining to explain reasoning
3. Update status when development starts
4. Reference release version when marking `done`

---

## API Reference

### List Feature Requests

```
GET /api/feature-requests
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | - | Filter by status |
| `mine_only` | boolean | false | Only user's requests |

**Response:**
```json
{
  "feature_requests": [
    {
      "id": "fr_abc123",
      "title": "Dark mode for dashboard",
      "description": "Add a dark theme option...",
      "status": "under-review",
      "vote_count": 15,
      "created_by": "jsmith",
      "created_at": "2026-01-01T10:00:00Z",
      "has_voted": true
    }
  ],
  "total": 42
}
```

### Get Statistics

```
GET /api/feature-requests/stats
```

**Response:**
```json
{
  "total": 42,
  "by_status": {
    "new": 10,
    "under-review": 8,
    "planned": 5,
    "in-progress": 3,
    "done": 12,
    "declined": 4
  }
}
```

### Create Request

```
POST /api/feature-requests
```

**Request:**
```json
{
  "title": "Export job history to CSV",
  "description": "Allow exporting filtered job history..."
}
```

### Update Request

```
PATCH /api/feature-requests/{id}
```

**Request (user editing own request):**
```json
{
  "title": "Updated title",
  "description": "Updated description"
}
```

**Request (admin changing status):**
```json
{
  "status": "planned"
}
```

### Vote/Unvote

```
POST /api/feature-requests/{id}/vote
```

Toggles vote state. Returns updated request with new vote count.

### Delete Request

```
DELETE /api/feature-requests/{id}
```

Users can delete own requests. Admins can delete any.

---

## Web UI Guide

### Navigation

- Access via main menu: **Feature Requests**
- Badge shows count of new requests (admin view)

### Request List View

- Sortable by: votes, created date, status
- Filterable by status
- Toggle "My Requests" to filter
- Click row to view details

### Request Detail View

Shows:
- Title and description
- Current status with badge
- Vote count and vote button
- Created by and date
- Admin notes (if any)
- Edit/Delete buttons (if owner or admin)

### Creating a Request

1. Click **+ New Request**
2. Fill in title (required, max 200 chars)
3. Fill in description (required, supports markdown)
4. Click **Submit**

### Admin Status Panel

When logged in as admin, request detail shows:
- Status dropdown to change status
- Add note text field
- Submit button for changes

---

## Database Schema

Feature requests are stored in three tables:

```sql
-- Main requests table
feature_requests (
  id, title, description, status,
  created_by_user_id, created_at, updated_at
)

-- Vote tracking
feature_request_votes (
  id, request_id, user_id, created_at
)

-- Admin/user notes
feature_request_notes (
  id, request_id, user_id, note_text, created_at
)
```

See [mysql-schema.md](../entities/mysql-schema.md#feature-request-tables) for full schema.

---

## See Also

- [API Reference](../pages/api-reference.md#feature-requests) - Full API documentation
- [Admin Guide](../pages/admin-guide.md) - Administrative workflows
