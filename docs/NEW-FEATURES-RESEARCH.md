# New Features Research & Plan

**Date**: 2026-01-17  
**Requested by**: Charles  
**Session**: Post v1.0.4 Release

---

## Feature 1: Restore Profile Summary in Execution Log Header

### Current State
- **Performance Profile Card** exists at lines 149-177 of [details.html](../pulldb/web/templates/features/jobs/details.html#L149-L177)
- Shows: Total Duration, Total Size, and per-phase breakdown (duration + MB/s)
- Located as a **separate card** below the Job Details card
- Progress bars are in a sticky `.logs-progress-sticky` div (lines 207-306) containing Download/Extraction/Restore/Atomic Rename bars

### Proposed Enhancement
Add a **compact performance summary** row to the sticky progress area that appears **after job completion**.

#### Mockup (ASCII)
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Execution Log                                                   [⏸ Pause]  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Download     [███████████████████████████████████████] 100%  ✓ 125 MB @ 8.2 MB/s │
│ Extraction   [███████████████████████████████████████] 100%  ✓ 125 MB (42 files)  │  
│ Restore      [███████████████████████████████████████] 100%  ✓ 245,000 rows       │
├─────────────────────────────────────────────────────────────────────────────┤
│ ✓ Complete: 45.2s total • 125 MB • 2.77 MB/s avg                            │  ← NEW ROW
└─────────────────────────────────────────────────────────────────────────────┘
│ [Scrollable log lines]                                                      │
```

### Implementation Plan

#### Files to Modify
1. **[details.html](../pulldb/web/templates/features/jobs/details.html)** - Add profile summary row after progress bars

#### Code Changes
```html
{# Add after the existing progress bars, inside .logs-progress-sticky #}
{% if profile and job.status.value in ['deployed', 'complete', 'superseded'] %}
<div class="log-progress-summary">
    <span class="log-progress-summary-icon">✓</span>
    <span class="log-progress-summary-text">
        Complete: {{ "%.1f"|format(profile.total_duration_seconds) }}s total • 
        {{ "%.1f"|format(profile.total_bytes / 1024 / 1024) }} MB • 
        {{ "%.2f"|format((profile.total_bytes / 1024 / 1024) / profile.total_duration_seconds) if profile.total_duration_seconds > 0 else '—' }} MB/s avg
    </span>
</div>
{% endif %}
```

2. **[job-details.css](../pulldb/web/static/css/pages/job-details.css)** - Add styling

```css
.log-progress-summary {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: var(--bg-success-subtle, rgba(34, 197, 94, 0.1));
    border-top: 1px solid var(--border-success, rgba(34, 197, 94, 0.3));
    font-size: 0.8125rem;
    color: var(--text-success, #22c55e);
}

.log-progress-summary-icon {
    font-size: 1rem;
}

.log-progress-summary-text {
    font-weight: 500;
}
```

### Effort Estimate
- **Complexity**: Low (1-2 hours)
- **Risk**: Minimal - additive change
- **Dependencies**: None (profile data already available)

---

## Feature 2: Browser Timezone for Date/Time Display

### Current State

#### Server-Side Rendering (Problem)
Templates use Python's `strftime()` which renders UTC times:
```html
{{ job.submitted_at.strftime('%Y-%m-%d %H:%M:%S') }}
```

Found in:
- [details.html](../pulldb/web/templates/features/jobs/details.html) - Submitted, Expires dates
- Multiple admin templates
- Audit logs

#### Client-Side Rendering (Already Working ✓)
The **jobs table** (lazy_table) already uses browser timezone correctly:
```javascript
// jobs.html line 343-346
date: (val) => {
    if (!val) return '-';
    const d = new Date(val);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
```

`new Date(val)` automatically converts UTC ISO strings to local timezone.

### Approach Options

#### Option A: JavaScript Post-Processing (Recommended)
Add `data-utc` attributes to server-rendered timestamps, convert on page load.

```html
<!-- Server renders -->
<span class="local-datetime" data-utc="{{ job.submitted_at.isoformat() }}Z">
    {{ job.submitted_at.strftime('%Y-%m-%d %H:%M:%S') }} UTC
</span>
```

```javascript
// Convert on page load
document.querySelectorAll('.local-datetime').forEach(el => {
    const utc = el.dataset.utc;
    if (utc) {
        const d = new Date(utc);
        el.textContent = d.toLocaleString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    }
});
```

**Pros**: 
- Progressive enhancement (shows UTC if JS fails)
- No Jinja filter changes needed
- Works with HTMX updates

**Cons**: 
- Flash of UTC before conversion

#### Option B: Jinja Filter with JS Timezone
Pass timezone from client, render server-side.

**Pros**: No flash
**Cons**: Complex, cookie/session overhead, doesn't work on first load

#### Option C: All Client-Side (like lazy_table)
Send ISO timestamps, render entirely in JS.

**Pros**: Consistent with lazy_table
**Cons**: Major template rewrites, breaks non-JS fallback

### Recommended Implementation (Option A)

#### Files to Modify

1. **Create utility JS** - `/static/js/utils/local-datetime.js`
```javascript
function convertToLocalTime() {
    document.querySelectorAll('[data-utc]').forEach(el => {
        const utc = el.dataset.utc;
        if (!utc) return;
        const d = new Date(utc);
        if (isNaN(d)) return;
        
        const format = el.dataset.format || 'datetime';
        let formatted;
        
        if (format === 'date') {
            formatted = d.toLocaleDateString('en-US', { 
                month: 'short', day: 'numeric', year: 'numeric' 
            });
        } else if (format === 'time') {
            formatted = d.toLocaleTimeString('en-US', { 
                hour: '2-digit', minute: '2-digit' 
            });
        } else {
            formatted = d.toLocaleString('en-US', { 
                month: 'short', day: 'numeric', year: 'numeric',
                hour: '2-digit', minute: '2-digit'
            });
        }
        
        el.textContent = formatted;
        el.title = d.toISOString(); // Show full UTC on hover
    });
}

// Run on load and after HTMX swaps
document.addEventListener('DOMContentLoaded', convertToLocalTime);
document.body.addEventListener('htmx:afterSwap', convertToLocalTime);
```

2. **Update base.html** - Include utility script

3. **Update templates** - Replace strftime with data-utc pattern:
```html
<!-- Before -->
{{ job.submitted_at.strftime('%Y-%m-%d %H:%M:%S') }}

<!-- After -->
<span data-utc="{{ job.submitted_at.isoformat() }}Z">{{ job.submitted_at.strftime('%Y-%m-%d %H:%M:%S') }} UTC</span>
```

### Effort Estimate
- **Complexity**: Medium (4-6 hours)
- **Risk**: Low - progressive enhancement
- **Scope**: ~20 template locations need updating

---

## Feature 3: Feature Requests Page with Voting

### Requirements
1. Users can submit feature requests
2. All users can vote (up/down) - **1 vote per user per request**
3. Display using lazy_table
4. Admin can mark features as "complete"

### Database Schema

#### New Migration: `00920_feature_requests.sql`

```sql
-- 00920_feature_requests.sql
-- Feature requests with user voting

CREATE TABLE feature_requests (
    request_id CHAR(36) PRIMARY KEY,
    
    -- Submitter
    submitted_by_user_id CHAR(36) NOT NULL,
    
    -- Content
    title VARCHAR(200) NOT NULL,
    description TEXT NULL,
    
    -- Status: 'open', 'in_progress', 'complete', 'declined'
    status ENUM('open', 'in_progress', 'complete', 'declined') NOT NULL DEFAULT 'open',
    
    -- Vote aggregates (denormalized for performance)
    vote_score INT NOT NULL DEFAULT 0,  -- upvotes - downvotes
    upvote_count INT NOT NULL DEFAULT 0,
    downvote_count INT NOT NULL DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    
    -- Admin notes
    admin_response TEXT NULL,
    
    -- Indexes
    INDEX idx_feature_requests_status (status),
    INDEX idx_feature_requests_score (vote_score DESC),
    INDEX idx_feature_requests_created (created_at DESC),
    
    FOREIGN KEY (submitted_by_user_id) REFERENCES auth_users(user_id)
);

CREATE TABLE feature_request_votes (
    vote_id CHAR(36) PRIMARY KEY,
    request_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    
    -- Vote type: 1 = upvote, -1 = downvote
    vote_value TINYINT NOT NULL,
    
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    
    -- Ensure one vote per user per request
    UNIQUE KEY uk_user_request (user_id, request_id),
    
    FOREIGN KEY (request_id) REFERENCES feature_requests(request_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES auth_users(user_id)
);
```

### Page Layout Mockup

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Feature Requests                                            [+ New Request] │
├─────────────────────────────────────────────────────────────────────────────┤
│ Stats: 12 Open • 3 In Progress • 8 Complete                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ ┌─────┬──────────────────────────────────────┬────────┬───────┬──────────┐ │
│ │Score│ Request                              │ Status │ By    │ Date     │ │
│ ├─────┼──────────────────────────────────────┼────────┼───────┼──────────┤ │
│ │ ▲   │ Support PostgreSQL targets           │ 🟢 Open│userax │ Jan 15   │ │
│ │ 15  │                                      │        │       │          │ │
│ │ ▼   │                                      │        │       │          │ │
│ ├─────┼──────────────────────────────────────┼────────┼───────┼──────────┤ │
│ │ ▲   │ Dark mode toggle                     │ 🔵 WIP │userbx │ Jan 10   │ │
│ │  8  │                                      │        │       │          │ │
│ │ ▼   │                                      │        │       │          │ │
│ ├─────┼──────────────────────────────────────┼────────┼───────┼──────────┤ │
│ │ ▲   │ Scheduled restores                   │ 🟢 Open│usercx │ Jan 8    │ │
│ │  5  │                                      │        │       │          │ │
│ │ ▼   │                                      │        │       │          │ │
│ └─────┴──────────────────────────────────────┴────────┴───────┴──────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation Files

#### HCA Layer Mapping
| File | HCA Layer | Purpose |
|------|-----------|---------|
| `schema/.../00920_feature_requests.sql` | shared/infra | Database schema |
| `pulldb/domain/feature_request.py` | entities | Pydantic models |
| `pulldb/worker/feature_request_service.py` | features | Business logic |
| `pulldb/api/routes/feature_requests.py` | pages/API | REST endpoints |
| `pulldb/web/routes/feature_requests.py` | pages/web | Web routes |
| `pulldb/web/templates/features/requests/` | pages/web | Templates |

#### API Endpoints

```python
# GET  /api/feature-requests       - List all (lazy_table)
# POST /api/feature-requests       - Submit new
# GET  /api/feature-requests/{id}  - Get one
# POST /api/feature-requests/{id}/vote  - Cast vote (+1 or -1)
# PATCH /api/feature-requests/{id}/status  - Admin: update status
```

#### Lazy Table Columns

```javascript
const COLUMNS = [
    { 
        key: 'vote_score', 
        label: 'Score', 
        sortable: true, 
        width: '80px',
        render: (val, row) => `
            <div class="vote-controls">
                <button class="vote-btn vote-up ${row.user_vote === 1 ? 'voted' : ''}" 
                        onclick="vote('${row.request_id}', 1)">▲</button>
                <span class="vote-score">${val}</span>
                <button class="vote-btn vote-down ${row.user_vote === -1 ? 'voted' : ''}"
                        onclick="vote('${row.request_id}', -1)">▼</button>
            </div>`
    },
    { key: 'title', label: 'Request', sortable: true, filterable: true },
    { key: 'status', label: 'Status', sortable: true, filterable: true, width: '100px', render: Renderers.status },
    { key: 'submitted_by_user_code', label: 'By', sortable: true, width: '80px' },
    { key: 'created_at', label: 'Date', sortable: true, width: '100px', render: Renderers.date }
];
```

### Vote Logic

```python
async def cast_vote(request_id: str, user_id: str, vote_value: int) -> dict:
    """
    Cast or change vote. vote_value: 1 (up), -1 (down), 0 (remove)
    """
    async with get_connection() as conn:
        # Check existing vote
        existing = await conn.fetchone(
            "SELECT vote_value FROM feature_request_votes WHERE request_id = %s AND user_id = %s",
            (request_id, user_id)
        )
        
        if existing:
            old_vote = existing['vote_value']
            if vote_value == 0:
                # Remove vote
                await conn.execute("DELETE FROM feature_request_votes WHERE request_id = %s AND user_id = %s", ...)
                delta = -old_vote
            elif vote_value != old_vote:
                # Change vote
                await conn.execute("UPDATE feature_request_votes SET vote_value = %s WHERE ...", ...)
                delta = vote_value - old_vote
            else:
                return  # No change
        else:
            if vote_value == 0:
                return  # Nothing to remove
            # New vote
            await conn.execute("INSERT INTO feature_request_votes ...", ...)
            delta = vote_value
        
        # Update aggregate
        await conn.execute("""
            UPDATE feature_requests SET 
                vote_score = vote_score + %s,
                upvote_count = upvote_count + %s,
                downvote_count = downvote_count + %s
            WHERE request_id = %s
        """, (delta, 1 if delta > 0 else -1 if delta < 0 else 0, ...))
```

### Effort Estimate
- **Complexity**: High (12-16 hours)
- **Risk**: Medium - new feature area
- **Dependencies**: None

---

## Summary & Priority Recommendation

| Feature | Effort | Value | Priority |
|---------|--------|-------|----------|
| 1. Profile Summary in Log Header | Low (1-2h) | Medium | **P1** - Quick win |
| 2. Browser Timezone | Medium (4-6h) | High | **P2** - User-facing improvement |
| 3. Feature Requests Page | High (12-16h) | Medium | **P3** - Nice to have |

### Suggested Implementation Order
1. **Feature 1** - Can be done in a single session, low risk
2. **Feature 2** - User-visible improvement, affects multiple pages
3. **Feature 3** - Larger undertaking, can be done as a separate sprint

---

## Questions for Review

1. **Feature 1**: Should we keep the Performance card below as-is, or remove it in favor of the summary row?
2. **Feature 2**: Should we show timezone indicator (e.g., "PST") next to converted times?
3. **Feature 3**: 
   - Should admins be the only ones who can submit requests, or all users?
   - Should there be a character limit on descriptions?
   - Should completed features link to release notes?

---

*Document generated by GitHub Copilot - Ready for review*
