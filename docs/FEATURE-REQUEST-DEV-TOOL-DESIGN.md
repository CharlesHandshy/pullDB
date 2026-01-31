# Feature Request Developer Tool - Design Document

> **Status**: Research Complete | **Date**: 2026-01-31  
> **Author**: AI Research Agent  
> **Scope**: Development tool for accessing and managing production feature requests

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Schema Analysis](#schema-analysis)
3. [Existing Infrastructure](#existing-infrastructure)
4. [Security Analysis](#security-analysis)
5. [Design Options](#design-options)
6. [Recommended Approach](#recommended-approach)
7. [Technical Architecture](#technical-architecture)
8. [Implementation Roadmap](#implementation-roadmap)
9. [Risk Assessment](#risk-assessment)

---

## Executive Summary

pullDB has a fully-implemented Feature Requests system with:
- 3 database tables (`feature_requests`, `feature_request_votes`, `feature_request_notes`)
- Complete service layer (`FeatureRequestService` - 748 lines)
- REST API endpoints (7 endpoints for CRUD + voting)
- Web UI pages for user submission and browsing

**The dev tool goal**: Enable developers to review production feature requests without accessing the production web UI, add technical notes/guidance, and optionally update status.

---

## Schema Analysis

### Tables

#### `feature_requests` (Primary)
```sql
CREATE TABLE feature_requests (
    request_id CHAR(36) PRIMARY KEY,
    submitted_by_user_id CHAR(36) NOT NULL,  -- FK to auth_users
    title VARCHAR(200) NOT NULL,
    description TEXT NULL,
    status ENUM('open', 'in_progress', 'complete', 'declined') DEFAULT 'open',
    vote_score INT DEFAULT 0,          -- upvotes - downvotes
    upvote_count INT UNSIGNED DEFAULT 0,
    downvote_count INT UNSIGNED DEFAULT 0,
    created_at TIMESTAMP(6),
    updated_at TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    admin_response TEXT NULL,           -- Shown when complete/declined
    
    -- Indexes for common queries
    INDEX idx_status (status),
    INDEX idx_score (vote_score DESC),
    INDEX idx_created (created_at DESC)
);
```

#### `feature_request_votes`
```sql
CREATE TABLE feature_request_votes (
    vote_id CHAR(36) PRIMARY KEY,
    request_id CHAR(36) NOT NULL,       -- FK to feature_requests
    user_id CHAR(36) NOT NULL,          -- FK to auth_users
    vote_value TINYINT NOT NULL,        -- 1 = upvote, -1 = downvote
    created_at TIMESTAMP(6),
    
    UNIQUE KEY uk_user_request (user_id, request_id)  -- One vote per user per request
);
```

#### `feature_request_notes`
```sql
CREATE TABLE feature_request_notes (
    note_id CHAR(36) PRIMARY KEY,
    request_id CHAR(36) NOT NULL,       -- FK to feature_requests
    user_id CHAR(36) NOT NULL,          -- FK to auth_users
    note_text TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_request (request_id),
    INDEX idx_created (created_at)
);
```

### Domain Models

Located in [pulldb/domain/feature_request.py](../pulldb/domain/feature_request.py):

| Model | Purpose |
|-------|---------|
| `FeatureRequestStatus` | Enum: `open`, `in_progress`, `complete`, `declined` |
| `FeatureRequest` | Full request with joined user info + current user's vote |
| `FeatureRequestCreate` | Input for creating requests |
| `FeatureRequestUpdate` | Admin input for status/response updates |
| `FeatureRequestVote` | Vote record |
| `FeatureRequestNote` | Note with joined user info |
| `FeatureRequestStats` | Aggregate counts by status |

### Key Business Rules

1. **Single-vote constraint**: Users can only vote for ONE request at a time (moving vote removes from previous)
2. **Vote clearing on completion**: When status → `complete` or `declined`, all votes are cleared
3. **Primary admin restriction**: Only user `00000000-0000-0000-0000-000000000002` can change status
4. **Notes are user-owned**: Users can only delete their own notes (unless admin)

---

## Existing Infrastructure

### Service Layer

**File**: [pulldb/worker/feature_request_service.py](../pulldb/worker/feature_request_service.py) (748 lines)

| Method | Description |
|--------|-------------|
| `get_stats()` | Aggregate counts by status |
| `list_requests()` | Paginated list with filtering (status, user, title) |
| `get_request()` | Single request with user's vote |
| `create_request()` | Submit new request |
| `update_request()` | Admin: change status/response |
| `vote()` | Cast or move vote |
| `delete_request()` | Admin: remove request |
| `list_notes()` | Notes for a request |
| `add_note()` | Add discussion note |
| `delete_note()` | Remove own/any note |

### REST API Endpoints

**File**: [pulldb/api/main.py](../pulldb/api/main.py) (lines 4060-4350)

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/api/feature-requests/stats` | Any user | Statistics |
| GET | `/api/feature-requests` | Any user | List with filters |
| GET | `/api/feature-requests/{id}` | Any user | Single request |
| POST | `/api/feature-requests` | Any user | Create request |
| PATCH | `/api/feature-requests/{id}` | **Admin only** | Update status/response |
| POST | `/api/feature-requests/{id}/vote` | Any user | Cast vote |
| DELETE | `/api/feature-requests/{id}` | Admin only | Delete request |

### Web UI Routes

**File**: [pulldb/web/features/requests/routes.py](../pulldb/web/features/requests/routes.py)

Full HTMX-powered UI with LazyTable pagination, voting buttons, note threads.

---

## Security Analysis

### MySQL User Separation

From [.pulldb/extensions/mysql-user-separation.md](../.pulldb/extensions/mysql-user-separation.md):

| User | Purpose | Feature Request Access |
|------|---------|----------------------|
| `pulldb_api` | API Service | Full CRUD (same as current) |
| `pulldb_worker` | Worker Service | Read-only (not granted INSERT/UPDATE on feature_requests) |
| `pulldb_loader` | myloader | None (target databases only) |

### Current Grants for `pulldb_api`

```sql
-- Feature requests (inferred from API service capabilities)
GRANT SELECT, INSERT, UPDATE, DELETE ON pulldb_service.feature_requests TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, DELETE ON pulldb_service.feature_request_votes TO 'pulldb_api'@'localhost';
GRANT SELECT, INSERT, DELETE ON pulldb_service.feature_request_notes TO 'pulldb_api'@'localhost';
```

### Credential Resolution

**Pattern from existing tools** (see [scripts/monitor_jobs.py](../scripts/monitor_jobs.py)):

```python
from pulldb.domain.config import Config
from pulldb.infra.secrets import CredentialResolver

config = Config.minimal_from_env()
resolver = CredentialResolver(config.aws_profile)
creds = resolver.resolve(os.getenv("PULLDB_COORDINATION_SECRET"))
```

**Secret paths** (from KNOWLEDGE-POOL.json):

| Secret | Path |
|--------|------|
| Coordination DB | `/pulldb/mysql/coordination-db` |
| API user | `/pulldb/mysql/api` |
| Worker user | `/pulldb/mysql/worker` |

### Recommended MySQL User for Dev Tool

**Option A: Use existing `pulldb_api` user**
- ✅ Already has correct grants
- ✅ Existing secret infrastructure
- ⚠️ Same permissions as production API

**Option B: Create dedicated `pulldb_devtools` user (RECOMMENDED)**
- ✅ Least privilege (read-only + notes write)
- ✅ Audit trail distinguishes dev tool access
- ⚠️ Requires new secret + grants setup

**Proposed grants for `pulldb_devtools`**:
```sql
-- Read all feature request data
GRANT SELECT ON pulldb_service.feature_requests TO 'pulldb_devtools'@'%';
GRANT SELECT ON pulldb_service.feature_request_votes TO 'pulldb_devtools'@'%';
GRANT SELECT ON pulldb_service.feature_request_notes TO 'pulldb_devtools'@'%';
GRANT SELECT ON pulldb_service.auth_users TO 'pulldb_devtools'@'%';

-- Write notes only (for dev guidance)
GRANT INSERT ON pulldb_service.feature_request_notes TO 'pulldb_devtools'@'%';

-- Optional: Update status (if trusted)
-- GRANT UPDATE ON pulldb_service.feature_requests TO 'pulldb_devtools'@'%';
```

---

## Design Options

### Option A: CLI Tool (`pulldb-admin feature-requests`)

**Approach**: Extend existing `pulldb-admin` with new command group.

```bash
pulldb-admin feature-requests list [--status open,in_progress] [--sort votes|age]
pulldb-admin feature-requests show <request_id>
pulldb-admin feature-requests note <request_id> "Technical note from dev team"
pulldb-admin feature-requests update <request_id> --status in_progress --response "Working on it"
pulldb-admin feature-requests export --format json|markdown
```

**Pros**:
- Integrates with existing admin tooling
- Inherits auth/config infrastructure
- Terminal-native workflow (SSH-friendly)
- Scriptable for automation

**Cons**:
- Limited visual presentation
- Multiple commands for review workflow
- No persistent session state

**Effort**: ~3 days

---

### Option B: Standalone Script

**Approach**: New script in `scripts/feature_request_review.py`

```bash
python scripts/feature_request_review.py --mode interactive
python scripts/feature_request_review.py --export markdown --output review.md
```

**Pros**:
- Self-contained, easy to share
- Can generate rich markdown reports
- No package dependency changes

**Cons**:
- Duplicates credential resolution code
- Not integrated with main tooling
- Harder to maintain

**Effort**: ~2 days

---

### Option C: Web Admin Interface

**Approach**: Add `/web/admin/feature-requests` page to existing web UI.

**Pros**:
- Rich visual interface
- Easy to browse and respond
- Consistent with existing admin pages

**Cons**:
- Requires web UI access to production
- Security: exposes admin functions over HTTP
- More frontend work

**Effort**: ~5 days

---

### Option D: Agent/Bot (AI-Assisted)

**Approach**: Automated analysis + categorization + suggested priorities.

```bash
pulldb-agent feature-requests analyze
# Output: Categorized requests, suggested priorities, similar groupings
```

**Pros**:
- Can identify patterns/duplicates
- Suggest priorities based on votes + age + keywords
- Could auto-draft responses

**Cons**:
- Complex to implement well
- Requires AI/ML infrastructure
- May produce unhelpful suggestions

**Effort**: ~10+ days

---

## Recommended Approach

### **Primary: Option A (CLI Tool) + Option B (Export Script)**

**Rationale**:

1. **CLI fits developer workflow**: Developers already use `pulldb-admin` for system tasks
2. **SSH-friendly**: Can review requests on production servers without web UI
3. **Scriptable**: Can integrate with issue trackers, CI/CD, Slack bots
4. **Low risk**: Uses existing infrastructure, minimal new code
5. **Export capability**: Generate markdown reports for meetings/planning

### Implementation Phases

**Phase 1**: Read-only CLI commands
**Phase 2**: Add notes/respond capability  
**Phase 3**: Export/reporting features
**Phase 4**: (Future) AI categorization agent

---

## Technical Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Developer Workstation                     │
├─────────────────────────────────────────────────────────────┤
│  pulldb-admin feature-requests list                         │
│       │                                                      │
│       ▼                                                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ CLI Layer (pulldb/cli/feature_requests.py)            │  │
│  │   - Argument parsing                                   │  │
│  │   - Output formatting (table, JSON, markdown)          │  │
│  └───────────────────────────────────────────────────────┘  │
│       │                                                      │
│       ▼                                                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Service Layer (pulldb/worker/feature_request_service) │  │
│  │   - Business logic (existing, reused)                  │  │
│  └───────────────────────────────────────────────────────┘  │
│       │                                                      │
│       ▼                                                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Infrastructure Layer (pulldb/infra/)                   │  │
│  │   - CredentialResolver → AWS Secrets Manager           │  │
│  │   - MySQLPool → Production Database                    │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │
         │ HTTPS (AWS Secrets Manager)
         │ MySQL (3306)
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Production Environment                    │
├─────────────────────────────────────────────────────────────┤
│  AWS Secrets Manager                                         │
│    /pulldb/mysql/coordination-db                             │
│                                                              │
│  MySQL (pulldb_service database)                             │
│    - feature_requests                                        │
│    - feature_request_votes                                   │
│    - feature_request_notes                                   │
│    - auth_users                                              │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
1. Developer runs: pulldb-admin feature-requests list --status open

2. CLI authenticates:
   - Checks system user has admin role (existing _check_admin_authorization)
   - Loads .env for AWS profile

3. Credential resolution:
   - CredentialResolver.resolve("aws-secretsmanager:/pulldb/mysql/coordination-db")
   - Returns MySQLCredentials(host, password)
   - Username from PULLDB_API_MYSQL_USER env var

4. Database query:
   - FeatureRequestService.list_requests(status_filter=['open'])
   - Returns list of FeatureRequest objects with user info

5. Output formatting:
   - Table view (default): rich/tabulate formatted table
   - JSON (--json): raw JSON for scripting
   - Markdown (--markdown): formatted for sharing
```

### Proposed CLI Commands

```python
# pulldb/cli/feature_requests.py

@click.group(name="feature-requests", help="Manage feature requests")
def feature_requests_group():
    pass

@feature_requests_group.command("list")
@click.option("--status", help="Filter by status (comma-separated)")
@click.option("--sort", type=click.Choice(["votes", "age", "status"]), default="votes")
@click.option("--limit", default=50)
@click.option("--json", "output_json", is_flag=True)
@click.option("--markdown", is_flag=True)
def list_requests(status, sort, limit, output_json, markdown):
    """List feature requests from production."""
    
@feature_requests_group.command("show")
@click.argument("request_id")
@click.option("--include-notes", is_flag=True)
def show_request(request_id, include_notes):
    """Show details of a specific feature request."""

@feature_requests_group.command("note")
@click.argument("request_id")
@click.argument("note_text")
def add_note(request_id, note_text):
    """Add a developer note to a feature request."""

@feature_requests_group.command("update")
@click.argument("request_id")
@click.option("--status", type=click.Choice(["open", "in_progress", "complete", "declined"]))
@click.option("--response", help="Admin response text")
def update_request(request_id, status, response):
    """Update feature request status (admin only)."""

@feature_requests_group.command("export")
@click.option("--format", type=click.Choice(["json", "markdown", "csv"]), default="markdown")
@click.option("--output", "-o", type=click.Path())
@click.option("--status", help="Filter by status")
def export_requests(format, output, status):
    """Export feature requests for review/planning."""

@feature_requests_group.command("stats")
def show_stats():
    """Show feature request statistics."""
```

### HCA Layer Placement

Following [.pulldb/standards/hca.md](../.pulldb/standards/hca.md):

| File | Layer | Justification |
|------|-------|---------------|
| `pulldb/cli/feature_requests.py` | pages | CLI entry point |
| `pulldb/worker/feature_request_service.py` | features | Business logic (existing) |
| `pulldb/domain/feature_request.py` | entities | Domain models (existing) |
| `pulldb/infra/mysql.py` | shared | Database access (existing) |

---

## Implementation Roadmap

### Phase 1: Read-Only CLI (2 days)

**Tasks**:
1. Create `pulldb/cli/feature_requests.py` with `list`, `show`, `stats` commands
2. Add to `pulldb/cli/admin.py` command group
3. Implement output formatters (table, JSON, markdown)
4. Write unit tests for CLI layer
5. Update CLI documentation

**Deliverables**:
- `pulldb-admin feature-requests list`
- `pulldb-admin feature-requests show <id>`
- `pulldb-admin feature-requests stats`

### Phase 2: Write Capability (1 day)

**Tasks**:
1. Add `note` command using existing `FeatureRequestService.add_note()`
2. Add `update` command using existing `FeatureRequestService.update_request()`
3. Add confirmation prompts for mutations
4. Add audit logging for dev tool actions

**Deliverables**:
- `pulldb-admin feature-requests note <id> "text"`
- `pulldb-admin feature-requests update <id> --status X`

### Phase 3: Export & Reports (1 day)

**Tasks**:
1. Add `export` command with JSON/markdown/CSV formats
2. Create markdown template for planning meetings
3. Add date range filtering
4. Add priority scoring (votes × age factor)

**Deliverables**:
- `pulldb-admin feature-requests export --format markdown -o report.md`

### Phase 4: Security Hardening (0.5 days)

**Tasks**:
1. Create `pulldb_devtools` MySQL user (if not using `pulldb_api`)
2. Add secret to AWS Secrets Manager
3. Document credential setup in SERVICE-README.md
4. Add rate limiting for mutations

### Phase 5: Documentation (0.5 days)

**Tasks**:
1. Add CLI reference to `docs/hca/pages/cli-reference.md`
2. Update `docs/KNOWLEDGE-POOL.md` with new commands
3. Create `docs/FEATURE-REQUEST-REVIEW-WORKFLOW.md`

---

## Risk Assessment

### Risk 1: Production Database Access

**Risk**: Dev tool has direct access to production data.

**Mitigations**:
- Use read-heavy, write-light privilege model
- Audit logging for all mutations
- Separate MySQL user with minimal grants
- Require admin role verification (existing infra)

**Residual Risk**: LOW

### Risk 2: Credential Exposure

**Risk**: AWS credentials needed for Secrets Manager access.

**Mitigations**:
- Use AWS profile (`pr-dev`) with cross-account assume-role
- Never log or display credentials
- Credentials never stored locally

**Residual Risk**: LOW (existing pattern)

### Risk 3: Unintended Status Changes

**Risk**: Developer accidentally marks request complete/declined.

**Mitigations**:
- Require `--confirm` flag for status changes
- Show current state before update
- Audit log with username/timestamp

**Residual Risk**: LOW

### Risk 4: Note Spam/Abuse

**Risk**: Excessive notes added to requests.

**Mitigations**:
- Notes tied to authenticated user (audit trail)
- Rate limiting (optional)
- Admin can delete any note

**Residual Risk**: VERY LOW

---

## Appendix A: Existing Code References

| Component | File | Lines |
|-----------|------|-------|
| Schema | `schema/pulldb_service/00_tables/060_feature_requests.sql` | 1-67 |
| Domain Models | `pulldb/domain/feature_request.py` | 1-100 |
| Service Layer | `pulldb/worker/feature_request_service.py` | 1-748 |
| REST API | `pulldb/api/main.py` | 4060-4350 |
| Web Routes | `pulldb/web/features/requests/routes.py` | all |
| Credential Resolver | `pulldb/infra/secrets.py` | 1-300 |
| Admin CLI Entry | `pulldb/cli/admin.py` | 1-226 |
| MySQL User Docs | `.pulldb/extensions/mysql-user-separation.md` | all |

## Appendix B: Example Output Formats

### Table Format (default)
```
┌────────────┬─────────────────────────────────┬────────┬───────┬────────────┐
│ ID         │ Title                           │ Status │ Votes │ Created    │
├────────────┼─────────────────────────────────┼────────┼───────┼────────────┤
│ abc-123... │ Add bulk restore capability     │ open   │ 12    │ 2026-01-15 │
│ def-456... │ Support MySQL 8.4 features      │ open   │ 8     │ 2026-01-20 │
│ ghi-789... │ Custom naming for staging DBs   │ open   │ 5     │ 2026-01-28 │
└────────────┴─────────────────────────────────┴────────┴───────┴────────────┘
Total: 15 open requests | Avg votes: 6.2
```

### Markdown Export
```markdown
# Feature Requests Review - 2026-01-31

## Summary
- Open: 15
- In Progress: 3
- Complete: 27
- Declined: 4

## Top Voted (Open)

### 1. Add bulk restore capability (12 votes)
- **ID**: abc-123-456-789
- **Submitted by**: jsmith (2026-01-15)
- **Description**: Allow restoring multiple customers at once...

**Developer Notes**:
- [2026-01-30 devops] Would require queue batching changes
- [2026-01-31 admin] Prioritizing for Q2

---
```

### JSON Export
```json
{
  "exported_at": "2026-01-31T14:30:00Z",
  "stats": {"open": 15, "in_progress": 3, "complete": 27, "declined": 4},
  "requests": [
    {
      "request_id": "abc-123-456-789",
      "title": "Add bulk restore capability",
      "status": "open",
      "vote_score": 12,
      "created_at": "2026-01-15T10:00:00Z",
      "submitted_by": {"username": "jsmith", "user_code": "JS001"},
      "notes": [...]
    }
  ]
}
```

---

## Conclusion

The recommended approach is to extend `pulldb-admin` with a `feature-requests` command group, leveraging existing service infrastructure. This provides:

1. **Security**: Uses existing admin auth + MySQL privilege model
2. **Consistency**: Follows established CLI patterns
3. **Low effort**: ~5 days total implementation
4. **Extensibility**: Easy to add AI categorization later

**Next Steps**:
1. Review and approve design
2. Create `pulldb_devtools` MySQL user (or decide to use `pulldb_api`)
3. Begin Phase 1 implementation
