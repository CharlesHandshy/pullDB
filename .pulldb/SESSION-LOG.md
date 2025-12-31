# pullDB Development Session Log

> **Purpose**: Automatic audit trail of development conversations, decisions, and rationale.  
> **Format**: Reverse chronological (newest first)  
> **Maintained by**: AI assistant (automatic, ongoing)

---

## DEPLOYMENT PROTOCOL (CRITICAL)

**ALWAYS use Debian packages for deployment. NEVER use pip install directly.**

```bash
# Build wheel first
python3 -m build

# Build .deb package
./scripts/build_deb.sh

# Deploy via .deb (this handles venv, schema, services)
sudo dpkg -i pulldb_X.X.X_amd64.deb

# Restart web service
sudo systemctl restart pulldb-web
```

**Rationale**: The .deb package handles all deployment concerns (venv setup, schema migrations, systemd units, permissions) in a reproducible way. Direct pip install bypasses these safeguards.

---

## 2025-01-28 | Theme Management Page Overhaul (Phases 1-3)

### Context
User requested: "A complete page to recolor the theme styles sitewide for Light and Dark mode. Reorder and update this page so that we can retheme with color and sliders, make it easier to use."

### What Was Done

1. **Restructured `_appearance.html`**: Reorganized from 6 flat color panels to 4 collapsible accordion groups:
   - **Foundation**: Surfaces + Backgrounds (6 tokens)
   - **Typography**: Text + Links + Code (9 tokens)
   - **UI Controls**: Interactive + Inputs + Borders + Table + Scrollbar (17 tokens)
   - **Feedback**: Status Colors (4 tokens)

2. **Added 18 new color controls** for previously unexposed tokens:
   - Links: default, hover, visited
   - Code: background, text, border
   - Inputs: background, border, focus, placeholder
   - Table: header background, row hover
   - Scrollbar: track, thumb, thumb hover

3. **Added HSL sliders** to all 37 color tokens:
   - Click '+' button to expand H/S/L sliders for any color
   - Bidirectional sync: sliders ↔ hex picker ↔ text input
   - Dynamic gradient tracks show color space visually
   - Enables harmonious color variations (same H, vary S/L)

4. **Fixed hardcoded hex colors** in appearance.html:
   - Toast notifications → `var(--color-success/error/info)`
   - Demo gallery fallbacks → `var(--gray-50/900)`
   - Badge backgrounds → `var(--color-*-bg)` tokens

### Commits
- `0f89a16`: Phase 1 - THEME-CONFORMITY-INDEX.md + audit script
- `ec679e1`: Phase 2 - Accordion restructure + new color controls
- `f0f95bb`: Phase 3 - HSL sliders for all 37 tokens

### PAUSED - Remaining Tasks
- **Remediate hardcoded colors sitewide**: profile.css L772/L906, other files per THEME-CONFORMITY-INDEX.md
- **Add theme export/import**: Download/upload JSON theme files

### Deployment Note
2025-12-30: Deploying to production for evaluation before continuing with remaining tasks.

---

## 2025-01-28 | Theme Conformity Index & Audit Script (Phase 1)

### Context
Pre-work for theme management overhaul. Created documentation and tooling to ensure theme consistency across codebase.

### What Was Done
1. **Created `docs/THEME-CONFORMITY-INDEX.md`**: Complete index of all 68 CSS theme tokens, compliance status per file, and remediation queue
2. **Created `scripts/audit_theme_conformity.py`**: Pre-commit script that detects hardcoded hex colors, `[data-theme]` overrides, and inline styles without `var()`

### Rationale
- **Continuous Learning**: Index serves as single source of truth for theme architecture
- **Pre-commit Enforcement**: Prevents regression of hardcoded colors

---

## 2025-01-28 | KISS S3 Configuration Cleanup

### Context
Deep audit revealed 9 S3-related config variables but only 2 were functional. The rest were dead code from earlier development phases creating confusion and maintenance burden. User decided: "Let's solidify what works and clean up the rest."

### What Was Done

1. **`packaging/env.example`**: Removed staging location from `PULLDB_S3_BACKUP_LOCATIONS` JSON array - now production only

2. **`pulldb/domain/settings.py`**: Removed 4 dead settings:
   - `s3_bucket_stg` (PULLDB_S3_BUCKET_STG)
   - `s3_bucket_prod` (PULLDB_S3_BUCKET_PROD)
   - `s3_aws_profile_stg` (PULLDB_S3_AWS_PROFILE_STG)
   - `s3_aws_profile_prod` (PULLDB_S3_AWS_PROFILE_PROD)

3. **`pulldb/domain/services/discovery.py`**: Replaced hardcoded fallback locations with FAIL HARD error message when `PULLDB_S3_BACKUP_LOCATIONS` not configured

4. **`pulldb/domain/config.py`**: Removed fallback to `s3_bucket_stg`/`s3_bucket_prod` settings

5. **`pulldb/web/templates/features/restore/restore.html`**: Removed environment selector UI (Production/Staging/All) - replaced with hidden input defaulting to production

6. **`docs/hca/shared/configuration.md`**: Updated documentation to reflect only working config vars

7. **`docs/KNOWLEDGE-POOL.json`**: Removed staging S3 bucket references, added note about single config var

8. **`pulldb/tests/test_config.py`**: Updated test fixtures to use `s3_bucket_path` instead of staging vars, removed tests for removed fallback behavior

9. **`pulldb/tests/conftest.py`**: Updated test fixtures and documentation to reference production S3 bucket

### Rationale
- **KISS principle**: Ship what works, save complexity for later
- **FAIL HARD protocol**: No silent fallbacks - if config is missing, fail with clear error
- **Dead code elimination**: 4+ unused settings removed reduces maintenance burden
- **Single source of truth**: `PULLDB_S3_BACKUP_LOCATIONS` is the only active S3 config

### Files Modified
- `packaging/env.example`
- `pulldb/domain/settings.py`
- `pulldb/domain/services/discovery.py`
- `pulldb/domain/config.py`
- `pulldb/web/templates/features/restore/restore.html`
- `docs/hca/shared/configuration.md`
- `docs/KNOWLEDGE-POOL.json`
- `pulldb/tests/test_config.py`
- `pulldb/tests/conftest.py`

---

## 2025-12-29 | Hard Delete Functionality for Soft-Deleted Jobs

### Context
User requested ability to perform a "hard delete" (remove job record from database) for jobs that have already been soft-deleted (status=deleted). The delete button was being hidden for jobs in deleted status.

### What Was Done
1. **Frontend: Modified `jobIdHistory` renderer** in [jobs.html](pulldb/web/templates/features/jobs/jobs.html):
   - Removed `deleted` from status exclusion list for delete button
   - Added detection of `isHardDelete` when `row.status === 'deleted'`
   - Added `hard-delete` CSS class for differentiation
   - Updated button title to "Hard Delete (remove job record)" for deleted jobs

2. **Frontend: Modified `singleDelete.open()`** in [jobs.html](pulldb/web/templates/features/jobs/jobs.html):
   - Accepts `isHardDelete` parameter
   - Shows different modal title: "🗑️ Hard Delete Job Record"
   - Shows different description: "This job's databases have already been deleted. This will permanently remove the job record."
   - Auto-checks and hides hard_delete checkbox for already-deleted jobs

3. **Frontend: Modified click handler** to pass `isHardDelete` flag to modal

4. **Frontend: Modified `singleDelete.execute()`** to always send `hard_delete=true` when `isHardDeleteOnly`

5. **Backend: Modified `can_delete` logic** in [routes.py](pulldb/web/features/jobs/routes.py#L587):
   - Changed exclusion from `JobStatus.DELETED` to `JobStatus.DELETING`
   - Now allows `can_delete=True` for deleted jobs (enabling hard delete)

6. **Database: Updated schema** in [300_mysql_users.sql](schema/pulldb_service/300_mysql_users.sql):
   - Added DELETE permission to `pulldb_api` user for `jobs` and `job_events` tables
   - Required for `hard_delete_job()` to delete job records

7. **Database: Granted permissions** (one-time fix for existing installations):
   ```sql
   GRANT DELETE ON pulldb_service.job_events TO 'pulldb_api'@'localhost';
   GRANT DELETE ON pulldb_service.jobs TO 'pulldb_api'@'localhost';
   ```

### Rationale
- **Two-stage delete workflow**: Soft delete removes databases, hard delete removes job record
- **Backend logic exists**: `force_hard_delete = job.status == JobStatus.DELETED` already in delete endpoint
- **Least privilege principle**: Only grant DELETE when needed (hard delete feature)
- **Progressive disclosure**: Modal title/description adapts to context so users understand the action

### Testing
- Verified delete button appears for deleted jobs with "Hard Delete" title
- Verified modal shows correct hard delete messaging
- Verified hard delete successfully removes job from database
- Job count decreased from 11 to 10 after hard delete

---

## 2025-12-27 | Job Delete Services Fix & Status Lifecycle

### Context
Job delete services (single and bulk) were broken. Single delete had a function signature mismatch; bulk delete had result structure mismatch between worker and status polling endpoint.

### What Was Done
1. **Fixed single delete route signature** in [routes.py](pulldb/web/features/jobs/routes.py#L436):
   - Changed from `(job_id, target_name, user_code, connection_config)` 
   - To `(job_id, staging_name, target_name, owner_user_code, dbhost, host_repo)`

2. **Fixed bulk delete result structure** in [admin_tasks.py](pulldb/worker/admin_tasks.py):
   - Worker now uses `progress` dict with counts (`processed`, `soft_deleted`, `hard_deleted`, `errors`)
   - Matches what status endpoint expects: `result.get("progress", {}).get("processed", 0)`

3. **Added `DELETING` intermediate status** in [models.py](pulldb/domain/models.py):
   - New status for visibility during async bulk delete operations
   - Called via `mark_job_deleting()` before database drops

4. **Added schema migration** [080_job_delete_support.sql](schema/pulldb_service/080_job_delete_support.sql):
   - Updated ENUM to include `deleting` status

5. **Added badge styling** in [admin.css](pulldb/web/static/css/pages/admin.css):
   - `.badge-pulse` animation for visual feedback during deletion

6. **Added unit tests** [test_job_delete.py](tests/unit/test_job_delete.py):
   - 13 tests covering `JobDeleteResult`, `is_valid_staging_name`, and `delete_job_databases`

7. **Removed orphaned file**: `jobs_old.html` (0 references found)

### Rationale
- **FAIL HARD principle**: Single delete was silently failing due to wrong parameters
- **Status lifecycle**: Jobs need visibility during async operations (deleting → deleted)
- **Result structure alignment**: Worker and polling endpoint must agree on data shape

### Files Modified
- `pulldb/web/features/jobs/routes.py` (signature fix, job_infos collection)
- `pulldb/worker/admin_tasks.py` (result structure, mark_job_deleting call)
- `pulldb/domain/models.py` (DELETING enum value)
- `pulldb/infra/mysql.py` (mark_job_deleting method)
- `pulldb/web/templates/features/jobs/jobs.html` (badge class, can_delete check)
- `pulldb/web/static/css/pages/admin.css` (.badge-pulse animation)
- `schema/pulldb_service/080_job_delete_support.sql` (deleting in ENUM)
- `tests/unit/test_job_delete.py` (new - 13 tests)
- `CHANGELOG.md` (documented changes)
- Deleted: `pulldb/web/templates/features/jobs/jobs_old.html`

---

## 2025-12-27 | Fix theme.css AttributeError (v0.1.2)

### Context
Dark mode was broken - theme.css endpoint returning 500 Internal Server Error.

### What Was Done
- **Root cause**: `settings_repo.get()` should be `settings_repo.get_setting()` per `SettingsRepository` protocol
- Fixed in [routes.py](pulldb/web/features/admin/routes.py#L4094-L4105) and [theme_generator.py](pulldb/web/features/admin/theme_generator.py#L152-L163)
- Rebuilt and deployed v0.1.2 via Debian package

### Rationale
The `SettingsRepository` protocol defines `get_setting(key)`, not `get(key)`. Code was written against wrong interface.

---

## 2025-12-27 | Force Delete User Feature Implementation

### Context
User requested async force-delete user feature with database drops, job cleanup, and user record deletion via background admin task queue.

### What Was Done

1. **Created admin_tasks queue schema** (`schema/pulldb_service/077_admin_tasks.sql`):
   - task_id UUID primary key, task_type ENUM, status ENUM
   - `running_task_type` generated column with unique index for max 1 concurrent task
   - Foreign keys to auth_users for requested_by and target_user_id
   - Supports orphan recovery via 10-minute stale timeout

2. **Added domain models** (`pulldb/domain/models.py`):
   - AdminTaskType enum: FORCE_DELETE_USER
   - AdminTaskStatus enum: PENDING, RUNNING, COMPLETE, FAILED
   - AdminTask dataclass with all task fields

3. **Created AdminTaskRepository** (`pulldb/infra/mysql.py`):
   - create_task(), claim_next_task() with orphan recovery
   - complete_task(), fail_task(), get_task()
   - Added count_jobs_by_user(), get_user_target_databases() to JobRepository

4. **Created AdminTaskExecutor** (`pulldb/worker/admin_tasks.py`):
   - execute_task() dispatcher
   - _execute_force_delete_user() with full audit logging
   - _drop_target_database() using pulldb_loader credentials per host
   - PROTECTED_DATABASES frozenset prevents system DB drops

5. **Extended worker service** (`pulldb/worker/loop.py`, `service.py`):
   - Admin task polling (lower priority than restore jobs)
   - Passes all required repositories to executor

6. **Added API endpoints** (`pulldb/web/features/admin/routes.py`):
   - GET /users/{id}/force-delete-preview - preview databases and job count
   - POST /users/{id}/force-delete - create admin task
   - GET /admin-tasks/{id} - status page with HTMX polling
   - GET /admin-tasks/{id}/json - JSON status for API

7. **Updated UI** (`users.html`, `admin.css`, `admin_task_status.html`):
   - Force delete modal with username confirmation
   - Skip all drops checkbox, individual database checkboxes
   - Dark mode styles for modal
   - Status page with progress stats and database drop results

8. **Updated MySQL grants** (`300_mysql_users.sql`):
   - pulldb_api: SELECT,INSERT on admin_tasks
   - pulldb_worker: Full access for execution

### Rationale
- **HCA Compliance**: All files placed in correct layers (domain/models, infra/mysql, worker/, web/)
- **Audit Compliance**: All actions logged to audit_logs with task_id correlation
- **Concurrency Control**: Generated column trick for MySQL partial index simulation
- **FAIL HARD**: Protected databases frozenset, explicit error handling

### Files Created/Modified
- `schema/pulldb_service/077_admin_tasks.sql` (NEW)
- `pulldb/domain/models.py` (MODIFIED - added enums and dataclass)
- `pulldb/infra/mysql.py` (MODIFIED - AdminTaskRepository, job count methods)
- `pulldb/worker/admin_tasks.py` (NEW)
- `pulldb/worker/loop.py` (MODIFIED - admin task polling)
- `pulldb/worker/service.py` (MODIFIED - executor initialization)
- `pulldb/web/features/admin/routes.py` (MODIFIED - 4 new endpoints)
- `pulldb/web/templates/features/admin/users.html` (MODIFIED - modal + JS)
- `pulldb/web/templates/features/admin/admin_task_status.html` (NEW)
- `pulldb/web/static/css/pages/admin.css` (MODIFIED - modal styles)
- `schema/pulldb_service/300_mysql_users.sql` (MODIFIED - grants)

---

## 2025-12-22 | Visual Testing & Page-Level CSS Fixes

### Context
Continuing CSS/HTML audit Phase 3 (visual testing) to validate HCA CSS migration before marking complete.

### What Was Done

1. **Visual testing via Playwright browser automation**:
   - ✅ Login page - forms, buttons, dark mode toggle
   - ✅ Dashboard - stats cards, tables, badges (both light/dark)
   - ✅ Restore page - forms, tabs, alerts, buttons
   - ✅ Jobs page - headers OK (virtual table data issue is JS, not CSS)
   - ✅ Users Admin - stats pills, table headers
   - ✅ Hosts Admin - table, Enabled/Disabled badges
   - ✅ Profile page - fixed, now renders correctly
   - ✅ Job Details - fixed, now renders correctly
   - ✅ Settings - accordions, badges, forms, sliders
   - ✅ 404 Error page - rendering correctly

2. **Fixed missing page-level CSS includes**:
   - Added `{% block extra_css %}` to `profile.html` for `profile.css`
   - Added `{% block extra_css %}` to `details.html` for `job-details.css`

3. **Updated audit document** with visual testing results and Phase 2 completion status

### Rationale
- **HCA Design**: Page-level CSS is loaded via `extra_css` block, not globally
- **Testing First**: Visual testing required before declaring legacy CSS removal complete
- **FAIL HARD**: Identified and fixed missing CSS includes immediately

### Files Modified
- `pulldb/web/templates/features/auth/profile.html` (added extra_css block)
- `pulldb/web/templates/features/jobs/details.html` (added extra_css block)
- `docs/CSS-HTML-AUDIT-2025-01-27.md` (visual testing results)

---

## 2025-12-16 | Legacy CSS Removal & Archive

### Context
Following successful migration of all 188 legacy-only CSS classes to HCA files, visual verification confirmed all pages render correctly without legacy CSS.

### What Was Done

1. **Removed legacy CSS imports** from `app_layout.html`:
   - Removed: `design-system.css`, `dark-mode.css`, `layout.css`, `components.css`
   - Kept: `theme.css` (dynamic), `sidebar.css` (pending migration)

2. **Archived legacy CSS files** to `pulldb/web/_archived/css/legacy/`:
   - `components.css` (6,083 lines)
   - `dark-mode.css` (1,065 lines)
   - `design-system.css` (483 lines)
   - `layout.css` (~150 lines)

3. **Visual verification** via Playwright:
   - Login page ✅
   - Dashboard (light & dark mode) ✅
   - Restore page ✅
   - Jobs page ✅
   - Admin page ✅
   - Profile page ✅

### Rationale
- **CSS Size Reduction**: ~7,800 lines of legacy CSS no longer loaded
- **No Duplicate Definitions**: Eliminates specificity conflicts
- **Clean Architecture**: HCA CSS only, organized by layer

### Files Archived
- `pulldb/web/_archived/css/legacy/` with README.md

---

## 2025-01-27 | Complete CSS Migration: 188 Legacy Classes → HCA

### Context
Following the comprehensive CSS/HTML audit that identified 683 unique classes across templates (53 HCA-only, 188 LEGACY-only, 290 both, 152 not-found), this session migrated all 188 legacy-only classes to HCA-compliant CSS files.

### What Was Done

1. **Migrated classes to HCA files** (categorized by target):
   - `pages/admin.css`: 46 classes (action-*, quick-*, setting-*, audit-*, host-*, etc.)
   - `pages/restore.css`: 32 classes (backup-*, customer-*, target-*, overwrite-*, qa-*, etc.)
   - `features/forms.css`: 23 classes (searchable-dropdown-*, tabs, required-mark)
   - `pages/job-details.css`: 14 classes (event-*, job-detail-*, detail-cell)
   - `shared/utilities.css`: 12 classes (capacity-*, link-primary, is-*, separator)
   - `pages/profile.css`: 11 classes (profile-*, password-*)
   - `features/dashboard.css`: 11 classes (manager-*)
   - `features/alerts.css`: 9 classes (error-container, error-card, etc.)
   - `features/search.css`: 10 classes (filter-*, clear-filters-btn, advanced-filter-bar)
   - `features/buttons.css`: 2 classes (btn-queue, btn-cancel-all)
   - `shared/layout.css`: 5 classes (page-header-row, section-header, etc.)
   - `entities/card.css`: 4 classes (info, info-label, info-value, stat-row)

2. **Verified CSS syntax** - All HCA CSS files have balanced braces

3. **Updated `app_layout.html`**:
   - Reordered CSS imports (theme.css and sidebar.css kept)
   - Added deprecation comments for legacy CSS files
   - Legacy files still included until full verification complete

### Rationale
- **HCA Compliance**: Each class placed in correct layer (shared→entities→features→pages)
- **Dark Mode**: All migrated classes include `[data-theme="dark"]` variants
- **No Breaking Changes**: Legacy CSS still loaded as fallback during transition

### Migration Summary
```
Total Classes: 188 legacy-only → 188 in HCA (100%)
Files Modified: 12 HCA CSS files
Status: ✅ Complete - verified via grep & HTTP
```

### Next Steps
1. Visual verification of all pages in browser
2. Remove legacy CSS imports after verification
3. Delete unused legacy CSS files (components.css, dark-mode.css, design-system.css, layout.css)

---

## 2025-01-27 | HCA Template Migration (base.html → app_layout.html)

### Context
Continuation of CSS standardization work. Prior session completed Phases 4-7 and fixed a layout regression. This session migrates the template hierarchy to HCA compliance.

### What Was Done

1. **Created `shared/layouts/base.html`** - New HCA Layer 0 document base
   - Extends `_skeleton.html`
   - Provides block mappings: `layout_class`, `layout_styles`, `layout_scripts`, `layout_content`, `layout_body_scripts`
   - Handles dark mode script injection

2. **Updated `shared/layouts/app_layout.html`** - HCA Layer 1 app layout
   - Extended to use `shared/layouts/base.html`
   - Migrated to same structure as working `templates/base.html`
   - Uses consistent class names: `.app-header`, `.app-sidebar`, `.app-main`, `.app-footer`
   - Full HCA CSS import hierarchy (shared → entities → features)

3. **Converted `templates/base.html`** - Thin wrapper
   - Now just extends `shared/layouts/app_layout.html`
   - Maps `body_class` → `layout_class` for backward compatibility
   - All 19 feature templates inherit HCA structure without modification

4. **Fixed template loader order** in `dependencies.py`
   - `templates/` now searched before `shared/layouts/`
   - Ensures `{% extends "base.html" %}` resolves to `templates/base.html`

### Rationale
- **HCA Compliance**: Proper layer separation (_skeleton → base → app_layout → pages)
- **Zero Feature Changes**: Feature templates still use `{% extends "base.html" %}` unchanged
- **Loader Order**: Critical fix—ChoiceLoader was resolving `base.html` to wrong file

### Template Hierarchy (Final)
```
_skeleton.html (HTML5 document)
    └── shared/layouts/base.html (dark mode, block mappings)
        └── shared/layouts/app_layout.html (app shell)
            └── templates/base.html (thin wrapper)
                └── features/*/templates/*.html (pages)
```

### Files Created
- `pulldb/web/shared/layouts/base.html`

### Files Modified
- `pulldb/web/shared/layouts/app_layout.html`
- `pulldb/web/templates/base.html`
- `pulldb/web/dependencies.py`

### Branch
`feature/migrate-base-to-app-layout` - Commit `7106770`

---

## 2025-12-15 | PR 15: Audit Feature Implementation

### Context
PR 15 from GUI migration Phase 5 - implementing full audit log browsing functionality. Leverages existing `AuditRepository` and `audit_logs` table infrastructure.

### What Was Done

1. **Created audit feature module** at `pulldb/web/features/audit/`
   - `__init__.py` - Module exports router
   - `routes.py` - Two endpoints:
     - `GET /web/admin/audit` - HTML page with LazyTable
     - `GET /web/admin/audit/api/logs` - JSON API for pagination

2. **Created audit template** at `pulldb/web/templates/features/audit/index.html`
   - LazyTable with columns: Time, Actor, Action, Target, Detail
   - Filter dropdowns: Actor, Target, Action type
   - URL-based filtering (`?actor_id=...`, `?target_id=...`)
   - Action badges with semantic colors (create=green, delete=red, etc.)
   - Clickable usernames link to pre-filtered views

3. **Added sidebar link** in `widgets/sidebar/sidebar.html`
   - Admin-only visibility (same block as Admin link)
   - Uses `file-text` icon for permanency/record semantics
   - `active_nav == 'audit'` highlighting

4. **Registered router** in `router_registry.py`
   - Import `audit_router` from features/audit
   - Include after admin_router

### Rationale
- **LazyTable with URL params**: Single template approach vs. separate `by_user.html`/`by_resource.html` — simpler, bookmarkable URLs
- **`file-text` icon**: User chose permanency semantics over `clipboard` (ephemeral action log)
- **Admin-only**: Audit logs contain sensitive action history

### Files Created
- `pulldb/web/features/audit/__init__.py`
- `pulldb/web/features/audit/routes.py`
- `pulldb/web/templates/features/audit/index.html`

### Files Modified
- `pulldb/web/templates/widgets/sidebar/sidebar.html` (sidebar link)
- `pulldb/web/router_registry.py` (router registration)

---

## 2025-12-15 | PR 14: Accessibility & Icon Completion

### Context
Post-migration audit revealed accessibility gaps and remaining inline SVGs. PR 14 addresses skip links, icon-only button aria-labels, and inline SVG conversion to macros.

### What Was Done

1. **Added skip link to base.html**
   - Inserted `<a href="#main-content" class="skip-link">Skip to main content</a>` before `<header>`
   - Added `id="main-content"` to `<main>` element
   - CSS already exists in design-system.css (sr-only until focused)

2. **Converted base.html inline SVGs to icon macros**
   - Added `{% from "partials/icons/_index.html" import icon %}`
   - Sidebar toggle: menu icon
   - Logo: layers icon (24px)
   - Theme toggle: sun/moon icons with `.theme-icon-light`/`.theme-icon-dark` spans

3. **Updated theme-toggle.js**
   - Changed from direct SVG selectors to span wrapper queries
   - Uses `.theme-icon-light` and `.theme-icon-dark` class selectors
   - Display toggled via `flex`/`none` instead of `block`/`none`

4. **Converted searchable_dropdown.html inline SVGs**
   - Added icon import macro
   - Converted 5 SVGs: search, spinner, x, chevron-down (2 instances)

5. **Converted active_jobs.html inline SVGs**
   - Added icon import macro
   - Converted 3 SVGs: eye (view), x (cancel), refresh-cw (retry)
   - Added aria-labels to all action buttons

6. **Added aria-labels to icon-only buttons**
   - hosts.html: "Add New Host" button
   - users.html: 4 JS render functions (hosts modal, password reset variations)
   - jobs.html: Cancel job button

7. **Updated gui-migration documentation**
   - README.md: Status now "Phase 1-4 Complete, Phase 5 In Progress"
   - Added Phase 5 overview with PRs 14-20 descriptions
   - 03-PR-BREAKDOWN.md: Added complete Phase 5 section with dependency graph

### Rationale
- **Skip link**: WCAG 2.4.1 requirement for keyboard users to bypass navigation
- **aria-labels**: WCAG 4.1.2 requires accessible names for interactive elements
- **Icon macros**: Maintainability - central icon system enables consistent updates
- **Theme toggle spans**: More robust selector than direct SVG query

### Files Modified
- `pulldb/web/templates/base.html` (skip link, 4 icon conversions)
- `pulldb/web/static/js/theme-toggle.js` (span-based selectors)
- `pulldb/web/templates/partials/searchable_dropdown.html` (5 icon conversions)
- `pulldb/web/templates/partials/active_jobs.html` (3 icons + aria-labels)
- `pulldb/web/templates/features/admin/hosts.html` (aria-label)
- `pulldb/web/templates/features/admin/users.html` (4 aria-labels)
- `pulldb/web/templates/features/jobs.html` (aria-label)
- `.pulldb/gui-migration/README.md` (Phase 5 status)
- `.pulldb/gui-migration/03-PR-BREAKDOWN.md` (Phase 5 PRs)

---

## 2025-12-15 | PR 13: STYLE-GUIDE Sync

### Context
PR 13 from GUI migration plan - synchronizing documentation with actual CSS implementations after GUI migration work.

### What Was Done

1. **Updated header metadata** in [STYLE-GUIDE.md](docs/STYLE-GUIDE.md)
   - Version: 1.0.0 → 1.1.0
   - Date: December 4 → December 15, 2025
   - Status: "Draft - Pending Review" → "Stable"

2. **Fixed Info color documentation**
   - Was incorrectly documented as "alias of primary" (blue)
   - Corrected to show actual Cyan values: `#ecfeff`, `#cffafe`, `#06b6d4`, `#0891b2`

3. **Fixed role badge class names**
   - Changed `.developer` to `.user` (matches actual CSS)
   - Updated manager badge color from `--primary-*` to `--info-*`
   - Updated color variables from `-600` to `-700` (matches actual CSS)

4. **Added new component sections**
   - Toast notifications (container, variants, animation)
   - Modal dialog (backdrop, content sizes, header/body/footer)
   - Breadcrumb navigation (list, items, links, separator)

5. **Added Icon System section**
   - Macro usage examples with parameters
   - Available icons organized by HCA layer (shared, entities, features, widgets, pages)
   - Fallback behavior documentation

6. **Added Dark Mode section**
   - Activation priority: localStorage > admin default > system preference
   - Theme toggle pattern
   - Key CSS variable overrides
   - Component support notes

7. **Updated Table of Contents**
   - Added Icon System (§7) and Dark Mode (§8) entries
   - Renumbered Accessibility (§9) and Implementation Status (§10)

8. **Updated Implementation Status**
   - Moved completed items: Toast, Modal, Breadcrumb, Icon system, Dark mode, Theme toggle, Admin inline CSS extraction
   - Removed "Create separate component CSS files" (already done in PR 8)
   - Updated planned items

### Rationale
- **Single source of truth**: Style guide must reflect actual implementation
- **Discoverability**: New developers need accurate component reference
- **Versioned changelog**: Track documentation evolution alongside code changes

### Files Modified
- [docs/STYLE-GUIDE.md](docs/STYLE-GUIDE.md) - Major documentation sync

---

## 2025-12-15 | PR 12: Dark Mode Polish

### Context
PR 12 from GUI migration plan - enabling functional dark mode by replacing hardcoded `white` values with CSS variables and connecting admin settings to client-side theme toggle.

### What Was Done

1. **Replaced hardcoded `white` in [layout.css](pulldb/web/static/css/layout.css)**
   - `.app-header` and `.app-footer` now use `var(--color-surface, white)`
   - Border colors now use `var(--color-border, var(--gray-200))`

2. **Replaced hardcoded `white` in [components.css](pulldb/web/static/css/components.css)** (13 occurrences)
   - `.card`, `.stat-card`, `.stat-card-compact`, `.dashboard-stat-card` → `var(--color-surface, white)`
   - `.form-input`, `.search-input`, `.role-select` → `var(--color-input-bg, white)`
   - `.btn-secondary`, `.toast`, `.modal-content`, `.stat-pill` → `var(--color-surface, white)`
   - Also updated border colors and text colors to use variables with fallbacks

3. **Extended [dark-mode.css](pulldb/web/static/css/dark-mode.css)** (+70 lines)
   - Form focus states with adjusted ring colors for dark backgrounds
   - Card/stat-card hover states
   - Text color adjustments for stat components
   - Dropdown menu styling
   - Toast variant border colors
   - Sidebar footer border
   - Virtual table / LazyTable row styling

4. **Updated [theme-toggle.js](pulldb/web/static/js/theme-toggle.js)** to support admin default
   - Added `getAdminDefault()` function to read `data-admin-theme-default` attribute
   - Priority order: localStorage (user override) > admin default > system preference > light fallback

5. **Added `admin_dark_mode()` global to Jinja2 environment**
   - Created `_get_admin_dark_mode()` in [dependencies.py](pulldb/web/dependencies.py)
   - Reads `dark_mode_enabled` setting from settings_repo
   - Added to `templates.env.globals`

6. **Updated [base.html](pulldb/web/templates/base.html)** to emit admin default attribute
   - Conditionally adds `data-admin-theme-default="dark"` when admin setting is enabled

### Rationale
- **CSS variables with fallbacks**: `var(--color-surface, white)` ensures graceful degradation if variables aren't defined
- **Split responsibility**: dark-mode.css handles component overrides, theme.css handles dynamic colors
- **localStorage override**: Users can override admin default for personal preference
- **Jinja2 global**: Avoids modifying every route handler to pass the setting

### Files Modified
- `pulldb/web/static/css/layout.css` (2 white → variable)
- `pulldb/web/static/css/components.css` (13 white → variable, plus border/text color updates)
- `pulldb/web/static/css/dark-mode.css` (+70 lines of component overrides)
- `pulldb/web/static/js/theme-toggle.js` (admin default support)
- `pulldb/web/dependencies.py` (+_get_admin_dark_mode function, +global)
- `pulldb/web/templates/base.html` (data-admin-theme-default attribute)

---

## 2025-12-15 | PR 11: Navigation Polish

### Context
PR 11 from GUI migration plan - updating sidebar to use the centralized icon macro system and standardizing `active_nav` detection across all routes.

### What Was Done

1. **Refactored [sidebar.html](pulldb/web/templates/widgets/sidebar/sidebar.html) to use icon macros**
   - Added `{% from 'partials/icons/_index.html' import icon %}` import
   - Replaced 7 inline SVG blocks (~75 lines) with `{{ icon('name', size='20', stroke_width='2') }}` calls
   - Icons used: dashboard, document, refresh, users-group, edit-pen, logout, login
   - Reduced template from ~95 lines to ~68 lines

2. **Standardized active nav detection**
   - Changed Admin from `request.url.path.startswith('/web/admin')` to `active_nav == 'admin'`
   - Changed Login from `request.url.path.startswith('/web/auth/login')` to `active_nav == 'login'`
   - All 7 nav items now use consistent `active_nav == 'x'` pattern

3. **Added `active_nav: "manager"` to manager routes**
   - Updated [manager/routes.py](pulldb/web/features/manager/routes.py) (1 TemplateResponse)

4. **Added `active_nav: "admin"` to admin routes**
   - Updated [admin/routes.py](pulldb/web/features/admin/routes.py) (8 TemplateResponses)
   - Covers: admin.html, users.html, hosts.html, host_detail.html, settings.html, prune_preview.html, cleanup_preview.html, orphan_preview.html

5. **Extracted inline style to CSS class**
   - Removed `style="margin-top: auto; border-top: 1px solid var(--gray-200); padding-top: 0.5rem;"` from logout container
   - Added `.sidebar-footer` class to [layout.css](pulldb/web/static/css/layout.css)

### Rationale
- **Icon macros**: Single source of truth for SVG icons, easier to update, HCA-compliant
- **Consistent active_nav**: Path-based detection was brittle and inconsistent with other nav items
- **CSS extraction**: Inline styles violate design system principles

### Files Modified
- `pulldb/web/templates/widgets/sidebar/sidebar.html` (icon macros, active_nav standardization)
- `pulldb/web/static/css/layout.css` (+5 lines for .sidebar-footer)
- `pulldb/web/features/manager/routes.py` (+active_nav)
- `pulldb/web/features/admin/routes.py` (+active_nav to 8 routes)

---

## 2025-12-15 | PR 8: Admin Theme GUI + CSS Extraction

### Context
Major PR implementing admin-configurable theming via HSL color sliders stored in MySQL settings, plus CSS extraction from admin templates.

### What Was Done

1. **Extracted ~380 lines of CSS to [components.css](pulldb/web/static/css/components.css)**
   - Modal system: `.modal`, `.modal-backdrop`, `.modal-content`, `.modal-header/body/footer`, `.modal-close`, `.modal-hidden`, `.modal-content-wide/lg`
   - Warning box: `.warning-box`, `.warning-box-title`, `.warning-box-text`
   - Exclude button: `.exclude-btn`, `.exclude-btn.excluded`, `.excluded-row`, `.reset-exclusions-btn`
   - User components: `.user-avatar`, `.role-badge` (admin/manager/user variants), `.stats-row`, `.stat-pill`, `.action-btn` (with danger/success/warning variants), `.manager-select`, `.role-select`
   - Page header: `.page-header-row`, `.page-header-left`, `.back-btn`
   - Utilities: `.d-inline`, `.d-none`, `.hidden`

2. **Refactored 3 preview templates to use component classes**
   - [cleanup_preview.html](pulldb/web/templates/features/admin/cleanup_preview.html): Removed ~70 lines of `<style>` block
   - [prune_preview.html](pulldb/web/templates/features/admin/prune_preview.html): Removed ~65 lines of `<style>` block
   - [orphan_preview.html](pulldb/web/templates/features/admin/orphan_preview.html): Removed ~70 lines of `<style>` block

3. **Refactored [users.html](pulldb/web/templates/features/admin/users.html)**
   - Reduced `<style>` block from ~500 lines to ~160 lines
   - Extracted modal, badge, stats, action button styles to components.css
   - Kept page-specific layout styles inline

4. **Added APPEARANCE settings category**
   - Extended `SettingCategory` enum in [settings.py](pulldb/domain/settings.py)
   - Added 3 new settings to `SETTING_REGISTRY`:
     - `primary_color_hue` (default: 217 - blue)
     - `accent_color_hue` (default: 142 - green)
     - `dark_mode_enabled` (default: false)
   - Updated category_order in [routes.py](pulldb/web/features/admin/routes.py)

5. **Created `/web/admin/api/theme.css` endpoint**
   - Generates dynamic CSS custom properties from MySQL settings
   - Returns HSL color variables for primary (50-900 shades) and accent colors
   - Includes dark mode overrides when enabled
   - 60-second cache header for performance

6. **Built appearance UI partial**
   - Created [_appearance.html](pulldb/web/templates/features/admin/partials/_appearance.html)
   - HSL hue sliders (0-360) with live swatch preview
   - Preset color buttons for quick selection
   - Dark mode toggle switch
   - Save/Reset buttons with async API calls

7. **Integrated theme.css into [base.html](pulldb/web/templates/base.html)**
   - Added `<link>` after design-system.css to override color tokens
   - Allows admin to customize brand colors globally

### Rationale
- **HSL over RGB**: Hue-only customization keeps saturation/lightness consistent with design system
- **MySQL storage**: Leverages existing settings infrastructure, persists across sessions
- **Dynamic CSS endpoint**: Avoids template complexity, enables caching
- **Preview swatches**: Users see color palette before saving

### Results
- components.css: 947 → 1326 lines (+379 lines of reusable components)
- Remaining inline `style=` in admin templates: ~57 total (down from ~150+)
- Templates still have `<style>` blocks for page-specific layout not suitable for extraction

### Files Modified
- `pulldb/web/static/css/components.css` (+379 lines)
- `pulldb/domain/settings.py` (APPEARANCE category + 3 settings)
- `pulldb/web/features/admin/routes.py` (+theme.css endpoint, category_order)
- `pulldb/web/templates/base.html` (theme.css link)
- `pulldb/web/templates/features/admin/settings.html` (Appearance icon + include)
- `pulldb/web/templates/features/admin/cleanup_preview.html` (refactored)
- `pulldb/web/templates/features/admin/prune_preview.html` (refactored)
- `pulldb/web/templates/features/admin/orphan_preview.html` (refactored)
- `pulldb/web/templates/features/admin/users.html` (refactored)

### Files Created
- `pulldb/web/templates/features/admin/partials/_appearance.html`

---

## 2025-12-15 | PR 3: Dashboard Inline CSS Cleanup

### Context
Continuing GUI migration per `.pulldb/gui-migration/README.md`. PR 3 targeted dashboard templates which had ~163 inline styles across 4 files.

### What Was Done

1. **Audited actual dashboard structure**
   - Found 4 files (not `partials/` as earlier audit suggested):
     - `dashboard.html` - Main wrapper with role-based includes
     - `_admin_dashboard.html` - Admin role (215 lines, 84 inline styles)
     - `_manager_dashboard.html` - Manager role (176 lines, 56 inline styles)
     - `_user_dashboard.html` - User role (84 lines, 22 inline styles)

2. **Added dashboard CSS classes to [components.css](pulldb/web/static/css/components.css)**
   - Added ~150 lines of reusable dashboard styles:
     - `.dashboard-stats-row`, `.dashboard-stat-card`, `.dashboard-stat-label/value/suffix`
     - `.section-header`, `.section-title`
     - `.dashboard-grid-2`, `.dashboard-table`
     - `.quick-actions` button group
     - `.job-detail-row` with `.detail-label/value`
     - `.capacity-indicator` with `.capacity-bar/fill`
     - Text color utilities: `.text-primary-600`, `.text-muted`, `.text-success`, `.text-warning`, `.text-danger`

3. **Refactored all role-specific dashboards**
   - Replaced inline styles with CSS classes
   - Maintained all HTMX refresh functionality
   - Preserved responsive design

### Rationale
- **HCA**: All dashboard templates remain in `features/dashboard/`
- **DRY**: Reusable CSS classes reduce template complexity
- **Maintainability**: Centralized styling in components.css

### Results
- Inline styles reduced from 163 to 45 (72% reduction)
- Remaining 45 are contextual layout overrides (margins, flex alignments) not suitable for component extraction

### Files Modified
- `pulldb/web/static/css/components.css` (~150 lines added)
- `pulldb/web/templates/features/dashboard/_admin_dashboard.html` (full refactor)
- `pulldb/web/templates/features/dashboard/_manager_dashboard.html` (full refactor)
- `pulldb/web/templates/features/dashboard/_user_dashboard.html` (full refactor)
- `pulldb/web/templates/features/dashboard/dashboard.html` (1 inline style → class)

---

## 2025-12-15 | PR 7-9: Admin Template Migration + Type Fixes

### Context
Continuing GUI migration per `.pulldb/gui-migration/README.md`. Admin templates needed migration to `features/admin/` and routes.py had ~50 type errors. User requested CSS extraction to components.css and type fixes.

### What Was Done

1. **Admin template migration**
   - Copied `hosts.html`, `host_detail.html`, `settings.html` to `features/admin/`
   - Updated 3 TemplateResponse paths in [routes.py](pulldb/web/features/admin/routes.py):
     - L671: `admin/hosts.html` → `features/admin/hosts.html`
     - L848: `admin/host_detail.html` → `features/admin/host_detail.html`
     - L1666: `admin/settings.html` → `features/admin/settings.html`
   - Deleted legacy `admin/` directory (11 files total)

2. **CSS extraction to [components.css](pulldb/web/static/css/components.css)**
   - Added reusable components (~200 lines):
     - `.alert`, `.alert-success/warning/danger/info` variants
     - `.status-badge`, `.status-badge-success/neutral/danger/warning`
     - `.status-bar`, `.status-item`, `.status-count`, `.status-divider` (host list summary)
     - `.info-grid`, `.info-item` (detail page layouts)
     - `.info-banner`, `.info-icon`, `.info-content`
     - `.search-bar`, `.search-wrapper`, `.search-icon`, `.search-input`
     - `.form-grid`, `.form-hint`, `.form-label.required`

3. **Type error fixes in routes.py** (all 50+ errors resolved):
   - Fixed `test_host_connection`: Extracted `checks` dict with explicit typing
   - Fixed `check_host_alias`: Added `dict[str, Any]` annotations, safe string coercion
   - Fixed `provision_host_wizard`: Created typed helper functions (`get_form_str`, `get_form_int`), typed `steps` list
   - Fixed `prov_result.data` access: Added null-safe `.get()` pattern
   - Removed duplicate try/except block (unreachable code at L1009)
   - Fixed orphan candidate functions: Renamed loop vars to avoid type inference confusion, added explicit `list[dict[str, Any]]` annotations

### Rationale
- **HCA compliance**: All templates now under `features/{feature}/` hierarchy
- **FAIL HARD**: Type annotations prevent silent runtime failures
- **DRY**: Common CSS components extracted for reuse across admin pages
- **Clean codebase**: No legacy `admin/` folder remaining

### Files Modified
- `pulldb/web/features/admin/routes.py` (type fixes + path updates)
- `pulldb/web/static/css/components.css` (~200 lines added)

### Files Created
- `pulldb/web/templates/features/admin/hosts.html` (from legacy)
- `pulldb/web/templates/features/admin/host_detail.html` (from legacy)
- `pulldb/web/templates/features/admin/settings.html` (from legacy)

### Files Deleted
- `pulldb/web/templates/admin/` (entire directory, 11 files)

---

## 2025-12-15 | PR 1 + Legacy Template Cleanup (GUI Migration)

### Context
Continuing GUI migration. PR 1 stat-card CSS was incomplete, and PRs 4/6/10 (Jobs/Manager/Audit) were identified for migration but upon inspection, the `features/` templates were already in use — the legacy folders contained orphaned templates.

### What Was Done

1. **PR 1: stat-card CSS completion**
   - Added to [components.css](pulldb/web/static/css/components.css):
     - `.stats-grid` layout class
     - `.stat-card` full-size base class
     - `.stat-icon` base + variants (`-primary`, `-success`, `-warning`, `-danger`, `-info`)
     - `.stat-content`, `.stat-value`, `.stat-label` classes
   - Now matches STYLE-GUIDE.md canonical definitions

2. **PR 4/6/10: Audit revealed templates already migrated**
   - Routes already use `features/jobs/`, `features/manager/`, etc.
   - Legacy root-level templates were orphaned (no routes pointing to them)

3. **Legacy template cleanup** — Deleted orphaned files:
   - `my_jobs.html`, `job_profile.html` (jobs legacy)
   - `manager/` folder (5 templates)
   - `audit/` folder (3 templates)
   - Root-level: `dashboard.html`, `history.html`, `job_detail.html`, `job_search.html`, `restore.html`, `search.html`

### Rationale
- **HCA compliance**: Legacy templates outside `features/` violate HCA; deleting removes tech debt
- **No functional impact**: All deleted templates had no routes — verified via grep before deletion
- **Cleaner codebase**: Reduced template count by ~15 files, all orphaned

### Files Deleted
- `pulldb/web/templates/my_jobs.html`
- `pulldb/web/templates/job_profile.html`
- `pulldb/web/templates/manager/` (entire folder)
- `pulldb/web/templates/audit/` (entire folder)
- `pulldb/web/templates/dashboard.html`
- `pulldb/web/templates/history.html`
- `pulldb/web/templates/job_detail.html`
- `pulldb/web/templates/job_search.html`
- `pulldb/web/templates/restore.html`
- `pulldb/web/templates/search.html`

### Files Modified
- [pulldb/web/static/css/components.css](pulldb/web/static/css/components.css) — Added stat-card CSS (~50 lines)

### Remaining Work
- PR 3: Dashboard inline CSS cleanup (deferred — larger scope)
- PR 7-9: Admin template migration (`admin/` folder still has mixed `features/admin/` and `admin/` usage)

---

## 2025-12-15 | PR 5 QA Template Implementation (GUI Migration)

### Context
GUI migration audit identified that [features/restore/restore.html](pulldb/web/templates/features/restore/restore.html) was **completely missing** the QA Template tab functionality that existed in the legacy template. This was marked as a **CRITICAL GAP** — users could not create QA databases.

### What Was Done

1. **Added tab CSS** to `{% block extra_css %}`:
   - `.form-tabs` container with pill-style layout
   - `.form-tab` buttons with hover/active states
   - `.tab-content` show/hide mechanism
   - `.qa-template-info` info banner styling
   - `.qa-config-row` responsive grid for extension + environment inputs

2. **Added tab HTML structure**:
   - Tab buttons: "Customer Database" (users icon) | "QA Template" (database icon)
   - Hidden input `name="qatemplate"` to track mode
   - Wrapped existing customer search in `#tab-customer`
   - New `#tab-qatemplate` with info banner, extension input, S3 env selector, and backup list

3. **Added JavaScript tab switching**:
   - Tab click handlers that update active states
   - `updateQaTargetPreview()` for target name preview
   - `loadQaTemplateBackups()` HTMX loader
   - `selectQaBackup()` / `clearQaBackupSelection()` functions
   - Updated `updateSummary()` for QA mode messaging
   - Updated form validation for QA vs Customer mode

4. **Updated backend route**:
   - Added `qatemplate: str | None = Form(None)` parameter
   - When `qatemplate == 'true'`, override `customer = 'qatemplate'`

5. **Updated backup_results partial**:
   - Detect if in `#qa-backup-list` container
   - Call `selectQaBackup` vs `selectBackup` accordingly

### Rationale
- **Feature parity**: Legacy restore page had QA Template tab; new page must too
- **FAIL HARD principle**: Don't silently remove features during migration
- **HCA compliance**: QA Template is part of restore feature, stays in features/restore/

### Files Modified
- [pulldb/web/templates/features/restore/restore.html](pulldb/web/templates/features/restore/restore.html) — Added ~165 lines (CSS + HTML + JS)
- [pulldb/web/features/restore/routes.py](pulldb/web/features/restore/routes.py) — Added qatemplate parameter handling
- [pulldb/web/templates/features/restore/partials/backup_results.html](pulldb/web/templates/features/restore/partials/backup_results.html) — QA backup selection support

---

## 2025-12-15 | Unified GUI Design System Planning

### Context
User requested comprehensive web GUI audit and unified design plan. Goals:
- Unified styling across all pages (day/night modes)
- Status bars vs pills standardization
- Clean styling with minimal clutter
- No duplicated functions per page
- Unified breadcrumb system
- HCA-compliant template organization

### What Was Done

1. **Comprehensive GUI audit** via subagent research:
   - Cataloged all 40+ templates across root, admin/, manager/, audit/, features/
   - Identified ~600 lines inline CSS across major templates
   - Found Bootstrap 5 dependency in login.html (external CSS)
   - Documented 45 unique SVG icons used inline throughout

2. **Architecture decisions made**:
   - **Icons**: HCA layer organization (shared/entities/features/widgets/pages)
   - **Theme storage**: Global admin settings (not per-user)
   - **CSS injection**: Generated `/web/theme.css` endpoint (cacheable, scalable)

3. **Created migration plan document**: `.pulldb/standards/gui-design-system.md`
   - 12-PR phased approach with dependency graph
   - Complete template migration mapping (source → target)
   - Dark mode color mapping (inverted gray scale)
   - Icon inventory by HCA category
   - Settings schema additions for APPEARANCE category
   - Acceptance criteria per PR

### Rationale
- **HCA compliance**: All templates must move to `features/{feature}/` structure
- **Generated CSS endpoint over inline styles**: Browser caching, ETag invalidation, CDN-ready
- **Global theme settings**: Single source of truth for organizational branding
- **Icon macros**: Eliminate ~45 duplicate inline SVG definitions, enable consistent sizing

### Files Created
- `.pulldb/standards/gui-design-system.md` — Master planning document (900+ lines)

### Estimated Effort
14-15 days across 12 PRs, with critical path: PR1 → PR7 → PR8 → PR12

---

## 2025-01-XX | Site-Wide Authentication Standardization

### Context
User reported "Failed to load data" on /web/manager page. Root cause: `/api/manager/team` endpoint only checked headers for auth tokens, not cookies. Web UI uses httponly cookies for session auth.

Full site audit revealed inconsistent authentication patterns across endpoints:
- Some endpoints check headers only (CLI-focused)
- Some check both headers and cookies (web-compatible)
- Admin endpoints had NO authentication at all (security critical)

### What Was Done

1. **Created unified auth dependencies in `pulldb/api/auth.py`**:
   - `get_authenticated_user()` - Requires login, checks headers AND cookies
   - `get_admin_user()` - Requires admin role
   - `get_manager_user()` - Requires manager or admin role
   - `get_optional_user()` - Optional auth (for backwards compatibility)
   - `validate_job_submission_user()` - Validates job submitter authorization
   - Type aliases: `AuthUser`, `AdminUser`, `ManagerUser`, `OptionalUser`

2. **Secured admin endpoints (previously NO auth)**:
   - `/api/admin/prune-logs` - Now requires AdminUser
   - `/api/admin/cleanup-staging` - Now requires AdminUser
   - `/api/admin/orphan-databases` - Now requires AdminUser
   - `/api/admin/delete-orphans` - Now requires AdminUser
   - `/api/admin/jobs/bulk-cancel` - Now requires AdminUser

3. **Fixed manager endpoints (cookie support)**:
   - `/api/manager/team` - Now uses ManagerUser (supports cookies)
   - `/api/manager/team/distinct` - Now uses ManagerUser (supports cookies)

4. **Fixed cancel endpoint**:
   - `/api/jobs/{job_id}/cancel` - Now uses AuthUser (supports cookies)

5. **Added auth to job submission**:
   - `/api/jobs` POST - Uses OptionalUser for backwards compatibility
   - Validates user can only submit jobs for themselves (admins exempt)

### Rationale
- **FAIL HARD**: Admin endpoints without auth = security vulnerability
- **Consistency**: All endpoints now use unified auth pattern
- **UX**: Web UI using httponly cookies must work everywhere
- **Backwards Compatibility**: CLI in trusted mode still works without headers

### Files Modified
- `pulldb/api/auth.py` - Added unified auth dependencies
- `pulldb/api/main.py` - Updated all endpoint signatures

### Tests
- All API tests passing (11 passed)
- Dev smoke test passing

---

## 2025-01-XX | Minimal Seeding for Simulation Mode

### Context
User requested reducing simulation initial mock data to only include required data (users, hosts, settings) - not jobs, history, logs, or staged databases.

### What Was Done
1. Changed default scenario from "dev_mocks" to "minimal" in:
   - `pulldb/simulation/core/seeding.py` - `seed_dev_scenario()` and `reset_and_seed()`
   - `scripts/dev_server.py` - command-line default

2. Verified minimal scenario only seeds:
   - Admin user (pulldb_admin)
   - Manager user (alice)
   - Regular users (bob, carol)
   - Host configurations
   - Settings

### Files Modified
- `pulldb/simulation/core/seeding.py`
- `scripts/dev_server.py`

---

## 2025-12-11 | Phase 2: E2E Tests Migration to Simulation Infrastructure

### Context
Continuation of mock infrastructure unification. Phase 1 completed dev_server.py migration.
Phase 2 migrates e2e tests (Playwright) to use the same unified simulation infrastructure.

### What Was Done
1. **Refactored `tests/e2e/conftest.py`** - Replaced 447 lines of duplicate mock code with `E2EAPIState`
2. **Created `E2EAPIState` class** - Mirrors `DevAPIState`, uses `_initialize_simulation_state()`
3. **Preserved test data compatibility** - Seeded users, hosts, jobs matching original e2e expectations
4. **Maintained auth compatibility** - Same "testpass123" password hash for e2e login tests

### Key Changes
- Removed: `MockUserRepo`, `MockAuthRepo`, `MockJobRepo`, `MockHostRepo`, `create_mock_*` helpers
- Added: `E2EAPIState` class using simulation infrastructure
- Added: `_seed_e2e_data()` and `_seed_auth_credentials()` methods
- File reduced from 447 to ~440 lines (much cleaner, less duplication)

### Rationale
- **Single Source of Truth**: All three mock systems (dev, e2e, simulation) now share one implementation
- **Prevents Drift**: Future changes to simulation automatically apply to e2e tests
- **Easier Maintenance**: One place to update mock behavior

### Files Modified
- `tests/e2e/conftest.py` (major refactor)

---

## 2025-12-XX | Mock Infrastructure Unification & Cleanup-Staging Bug Fix

### Context
User reported bug: `Cleanup failed: 'MockJobRepo' object has no attribute 'find_job_by_staging_prefix'` on the cleanup-staging page in dev server mode.

### Root Cause
The dev server (`scripts/dev_server.py`) used custom `MockJobRepo` but did NOT set `PULLDB_MODE=SIMULATION`. This meant cleanup code took the "real" path expecting full `JobRepository` interface, but got incomplete mock.

Additionally, discovered THREE separate mock implementations causing drift:
1. `pulldb/simulation/` - Production simulation mode (most complete)
2. `scripts/dev_server.py` - Dev server custom mocks (incomplete)
3. `tests/e2e/conftest.py` - Playwright e2e test mocks (incomplete)

### What Was Done
1. **Created `pulldb/simulation/core/seeding.py`** - Data seeding functions for dev scenarios
2. **Enhanced `SimulatedJobRepository`** - Added compatibility properties (`active_jobs`, `history_jobs`, `_cancel_requested`)
3. **Set `PULLDB_MODE=SIMULATION`** at top of dev_server.py
4. **Created `DevAPIState` class** - Replaces `MockAPIState`, uses unified simulation infrastructure
5. **Deleted ~1100 lines of duplicate mock code** from dev_server.py
6. **Fixed `prune_job_events` signature** - Added default value to match production
7. **Created `tests/simulation/test_protocol_parity.py`** - Catches future mock drift at CI time

### Rationale
- **FAIL HARD**: Three separate mocks inevitably drift, causing silent failures
- **Single Source of Truth**: Unified simulation prevents drift
- **Protocol Parity Tests**: CI catches missing methods BEFORE they cause bugs
- **HCA Compliance**: Seeding module in shared layer, DevAPIState in pages layer

### Key Decisions
| Decision | Why |
|----------|-----|
| Unify to simulation module | Single source prevents drift |
| Keep scenario switching | Dev workflow requires different states |
| Add parity tests | CI catches drift early |
| Leave e2e for phase 2 | Focus on immediate bug fix first |

### Files Modified
- `pulldb/simulation/core/seeding.py` (created)
- `pulldb/simulation/adapters/mock_mysql.py` (added properties, fixed signature)
- `scripts/dev_server.py` (refactored, deleted ~1100 lines)
- `tests/simulation/test_protocol_parity.py` (created)

### Test Results
- 42 tests pass (simulation + unit)
- Dev server starts correctly
- Protocol parity tests catch future drift

---

## 2025-12-04 | Automatic Session Logging Implementation

### Context
User requested automatic, ongoing session logging that captures what we discuss, what's being audited/fixed, and WHY - without needing reminders. Should be as natural as HCA enforcement.

### What Was Done
1. **Created `.pulldb/SESSION-LOG.md`** - Append-only audit trail
2. **Updated `.github/copilot-instructions.md`** - Added session logging as Critical Directive #5
3. **Updated `.pulldb/CONTEXT.md`** - Added to "Ongoing Behaviors (AUTOMATIC)" section
4. **Defined trigger points**: Session start, after significant work, before session end
5. **Established log format**: Date, Topic, Context, Actions, Rationale, Files

### Rationale
- **Institutional memory**: Captures WHY decisions were made for future reference
- **Accountability**: Creates audit trail of development activity
- **Onboarding**: New developers can read history to understand evolution
- **Pattern recognition**: Reviewing logs reveals recurring issues

### Design Decisions
| Decision | Why |
|----------|-----|
| Reverse chronological | Newest work most relevant |
| Mandatory like HCA | Must be automatic, not opt-in |
| Reference principles | Connect actions to standards (FAIL HARD, Laws of UX) |
| Concise format | Scannable, not verbose |

### Files Modified
- `.pulldb/SESSION-LOG.md` (created)
- `.github/copilot-instructions.md` (added session logging directive)
- `.pulldb/CONTEXT.md` (added ongoing behaviors section)

---

## 2025-12-04 | Web UI Style Guide & Visual Audit

### Context
User requested a comprehensive audit of the web UI with recommendations based on modern design principles and UX research.

### What Was Done
1. **Audited entire web UI** (~2,100 lines of CSS in base.html, 15+ templates)
2. **Researched UX principles** - Consulted Nielsen's 10 Heuristics, Laws of UX (lawsofux.com)
3. **Created comprehensive style guide** (`docs/STYLE-GUIDE.md`) documenting:
   - Design philosophy (internal tool priorities)
   - Color system with semantic mapping
   - Typography scale
   - Component patterns (buttons, cards, badges, tables, forms)
   - Accessibility requirements
4. **Added to knowledge base** (`docs/KNOWLEDGE-POOL.md`) for quick reference
5. **Built visual styleguide page** (`/web/admin/styleguide`) showing all components
6. **Captured screenshots** using Playwright MCP for visual review

### Key Findings
| Issue | Impact | Status |
|-------|--------|--------|
| CSS bloat (2,100+ lines inline) | Maintenance burden | Documented for refactor |
| Inconsistent component patterns | Cognitive load | Canonical patterns defined |
| Missing focus states | Accessibility | Added to checklist |
| No dark mode | User preference | Low priority, planned |

### Rationale
- Internal tools benefit from **consistency over creativity**
- Established design tokens enable team scalability
- Visual documentation reduces onboarding time
- Laws of UX provide evidence-based guidance

### Files Modified
- `docs/STYLE-GUIDE.md` (created)
- `docs/KNOWLEDGE-POOL.md` (updated)
- `pulldb/web/templates/admin/styleguide.html` (created)
- `pulldb/web/features/admin/routes.py` (added styleguide route)

---

## 2025-12-04 | Manager Templates Enhancement

### Context
Building out web pages for manager functions to match admin/dashboard quality standards.

### What Was Done
1. Enhanced `manager/index.html` with admin-style section cards
2. Enhanced `manager/my_team.html` with stats grid and improved tables
3. Enhanced `manager/user_detail.html` with profile card pattern
4. Enhanced `manager/create_user.html` with form card pattern
5. Enhanced `manager/submit_for_user.html` with sectioned form layout

### Rationale
- **Law of Similarity**: Consistent patterns help users recognize functionality
- **Aesthetic-Usability Effect**: Polished UI perceived as more usable
- Manager role is critical for team workflows - deserves first-class UI

---

## 2025-12-04 | RLock Refactoring (Simulation Mode)

### Context
User identified dangerous `_unlocked` pattern in mock_mysql.py where internal methods could be called without proper locking.

### What Was Done
1. Refactored `SimulatedUserRepository` to use `RLock` (reentrant lock)
2. Eliminated all `_unlocked` helper methods
3. Public methods now safely call other public methods (nested lock acquisition)
4. Verified with test script

### Rationale
- **FAIL HARD principle**: Unsafe patterns should be eliminated, not documented
- `RLock` allows same thread to re-acquire lock - perfect for nested calls
- Simpler code = fewer bugs

### Before/After
```python
# BEFORE (dangerous)
def get_or_create_user(self, username):
    with self._state.lock:
        user = self._get_user_by_username_unlocked(username)  # Could be called outside lock!
        
# AFTER (safe)
def get_or_create_user(self, username):
    with self._state.lock:  # RLock - reentrant
        user = self.get_user_by_username(username)  # Safe - same thread can re-acquire
```

---

## Session Log Guidelines

When appending to this log, include:

1. **Date & Topic** - `## YYYY-MM-DD | Brief Topic`
2. **Context** - What prompted this work
3. **What Was Done** - Concrete actions taken
4. **Key Findings** - Issues discovered (if audit)
5. **Rationale** - WHY decisions were made
6. **Files Modified** - For traceability

## 2025-12-06 | Refactor Backup Discovery Logic

### Context
Addressed "Code Duplication" gap from Web2 Audit Report. Logic for searching customers and backups in S3 was duplicated between API and Web2.

### What Was Done
- Created `pulldb/domain/services/discovery.py` with `DiscoveryService`.
- Refactored `pulldb/api/main.py` to use the shared service.
- Refactored `pulldb/web2/features/restore/routes.py` to use the shared service.
- Verified with unit tests in simulation mode.

### Rationale
- **DRY Principle**: Centralized S3 search logic to a single domain service.
- **HCA**: Moved business logic from API/Web layers to Domain layer.
- **Maintainability**: Changes to S3 structure or logic now only need to happen in one place.

### Files Modified
- `pulldb/domain/services/discovery.py` (new)
- `pulldb/api/main.py`
- `pulldb/web2/features/restore/routes.py`
