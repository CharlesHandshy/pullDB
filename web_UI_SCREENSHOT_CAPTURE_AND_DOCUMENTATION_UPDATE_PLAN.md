# Web UI Screenshot Capture & Documentation Update Plan

> **Status**: PLANNING (FINAL - AUDIT COMPLETE)  
> **Created**: 2026-01-06  
> **Last Updated**: 2026-01-06 (Final Audit Complete)  
> **Total Screenshots**: 130 (65 light + 65 dark)  
> **Total Sub-agents**: 18

---

## Audit Summary

| Metric | Original Plan | First Audit | Deep Audit | Final Audit |
|--------|---------------|-------------|------------|-------------|
| Routes Covered | ~26 | 54 | 54 | **54** |
| Screenshots | 66 | 108 | 128 | **130** |
| Help Pages | 6 | 7 | 7 | **7** |
| Sub-agents | 16 | 18 | 18 | **18** |
| Modals Documented | ~4 | ~6 | 14 | **17** |
| State Variations | ~3 | ~8 | 12 | **17** |
| Error Pages | 2 | 2 | 3 | **3** (404, 500, 403) |

### Audit Passes Completed
1. ✅ **Initial Plan** - Core routes and pages (66 screenshots)
2. ✅ **First Audit** - Missing routes, Manager page, error pages (+42 screenshots)
3. ✅ **Deep Audit** - Modal dialogs, confirmation flows, empty/error states (+20 screenshots)
4. ✅ **Final Audit** - Table UI patterns, job phase details, verification (+2 screenshots)
5. ✅ **Documentation Validation** - Animated panels, S3 config, terminal examples (all accurate)

### Audit Verification Checklist
- [x] All Flask routes with UI templates identified
- [x] All modal dialogs catalogued
- [x] All job states (QUEUED, RUNNING, DOWNLOADING, RESTORING, COMPLETE, FAILED, CANCELING) covered
- [x] All error pages (403, 404, 500) included
- [x] Empty states documented
- [x] Table UI patterns (filter, sort) included
- [x] All 3 user roles (USER, MANAGER, ADMIN) have dedicated views
- [x] New Manager help page planned

---

## Executive Summary

Capture Playwright screenshots (light + dark mode) of all pullDB web UI screens, apply automated annotations, and integrate into the **7 Web UI help pages** (including newly identified Manager page).

### Deliverables

1. **138 annotated screenshots** in `pulldb/web/static/help/screenshots/`
2. **CSS component** `.screenshot` with theme-aware `<picture>` support
3. **Annotation system** with numbered callouts and legends
4. **Updated help templates** (7 files) with embedded screenshots
5. **New help template** `help/web-ui/manager.html` for Manager role documentation
6. **Updated documentation index** with screenshot inventory

---

## Phase 0: Infrastructure Setup

**Sub-agent**: 1  
**Dependencies**: None

### Tasks

| # | Task | Output File | Description |
|---|------|-------------|-------------|
| 0.1 | Create directory structure | `pulldb/web/static/help/screenshots/` | Subfolders: `light/`, `dark/`, `annotated/light/`, `annotated/dark/` each containing `dashboard/`, `restore/`, `jobs/`, `profile/`, `admin/`, `common/` |
| 0.2 | Add CSS component | `pulldb/web/static/help/css/help.css` | `.screenshot` class with `<picture>` element support, figcaption styling, theme-aware borders |
| 0.3 | Create annotation config | `docs/help-screenshot-annotations.yaml` | YAML file defining position coordinates for callouts on each screenshot |
| 0.4 | Create annotator script | `scripts/annotate_screenshots.py` | Pillow-based script to draw numbered circles + legends |
| 0.5 | Create capture script | `scripts/capture_help_screenshots.py` | Playwright script extending `tests/visual/test_visual_regression.py` patterns |

### CSS Component Specification

```css
/* === Screenshot Component === */
.screenshot {
    margin: var(--space-6) 0;
    border-radius: var(--radius-lg);
    overflow: hidden;
    border: 1px solid var(--color-border);
    background: var(--color-bg-card);
    box-shadow: var(--shadow-md);
}

.screenshot img {
    display: block;
    width: 100%;
    height: auto;
}

.screenshot figcaption {
    padding: var(--space-3) var(--space-4);
    font-size: 0.875rem;
    color: var(--color-text-secondary);
    border-top: 1px solid var(--color-border);
    background: rgba(0, 0, 0, 0.02);
}

[data-theme="dark"] .screenshot figcaption {
    background: rgba(255, 255, 255, 0.02);
}
```

### HTML Pattern for Templates

```html
<figure class="screenshot">
    <picture>
        <source srcset="../../static/help/screenshots/annotated/dark/{category}/{name}.png" 
                media="(prefers-color-scheme: dark)">
        <img src="../../static/help/screenshots/annotated/light/{category}/{name}.png" 
             alt="{Descriptive alt text}"
             loading="lazy">
    </picture>
    <figcaption>1. Element — 2. Element — 3. Element</figcaption>
</figure>
```

---

## Phase 0.5: Simulation Data Enhancement

**Sub-agent**: 1  
**Dependencies**: None (can run parallel with Phase 0)

### Current Simulation Data

| Data Type | Count | Status |
|-----------|-------|--------|
| Users | 3 (USER, MANAGER, ADMIN) | ✅ Sufficient |
| Hosts | 5 (4 enabled, 1 disabled) | ✅ Sufficient |
| Jobs (dev_mocks) | 400 active + 400 history | ✅ Sufficient |
| Customers | 20 | ✅ Sufficient |
| Audit Logs | 150 entries | ✅ Sufficient |
| Orphan DBs | 7 | ✅ Sufficient |

### Gaps to Fill (Original)

| File | Addition | Purpose |
|------|----------|---------|
| `pulldb/simulation/fixtures.py` | Add `usr-004` (disabled USER) | Screenshot disabled user indicator in admin |
| `pulldb/simulation/fixtures.py` | Add `totp_secret` to devadmin | Screenshot MFA badge in profile |
| `pulldb/simulation/scenarios.py` | Add job at 67% progress with rich log | Screenshot job detail with progress |
| `pulldb/simulation/scenarios.py` | Add job in CANCELING state | Screenshot cancel-pending state |

### Gaps to Fill (Deep Audit Additions)

| File | Addition | Purpose |
|------|----------|---------|
| `pulldb/simulation/fixtures.py` | Add `usr-005` (user with `password_reset_at` set) | Screenshot password reset pending indicator |
| `pulldb/simulation/fixtures.py` | Add `usr-006` (locked/system user) | Screenshot locked user indicator |
| `pulldb/simulation/scenarios.py` | Add job in FAILED state with error message | Screenshot failed job with error details |
| `pulldb/simulation/scenarios.py` | Add job in DELETING state | Screenshot delete-in-progress state |
| `pulldb/simulation/scenarios.py` | Add job in QUEUED state | Screenshot queued job details |
| `pulldb/simulation/scenarios.py` | Add job in DOWNLOADING phase | Screenshot download progress |
| `pulldb/simulation/scenarios.py` | Add job in RESTORING phase with table progress | Screenshot restore progress |
| `pulldb/simulation/scenarios.py` | Add pending API key (approved_at=None) | Screenshot API key approval queue |
| `pulldb/simulation/fixtures.py` | Add host with credential error state | Screenshot host error indicator |
| `pulldb/simulation/fixtures.py` | Add disallowed usernames entries | Screenshot disallowed users admin page |

---

## Phase 1: Screenshot Capture

**Sub-agents**: 7 (parallel)  
**Dependencies**: Phase 0, Phase 0.5

### Capture Configuration

- **Viewport**: 1280 × 720
- **Themes**: Light + Dark (capture both per screenshot)
- **Format**: PNG
- **Dev Server**: `scripts/dev_server.py` with `dev_mocks` scenario

### Sub-agent Assignments (FINAL)

| Agent | Category | Screenshots | Routes | Roles Required |
|-------|----------|-------------|--------|----------------|
| 1A | Common/Overview | 18 (9×2) | `/web/auth/login`, `/web/dashboard`, error pages, table UI | None, USER, ADMIN |
| 1B | Dashboard | 10 (5×2) | `/web/dashboard` | USER, MANAGER, ADMIN |
| 1C | Restore Wizard | 12 (6×2) | `/web/restore` | USER, MANAGER |
| 1D | Jobs | 24 (12×2) | `/web/jobs`, `/web/jobs/<id>` | USER, ADMIN |
| 1E | Profile | 12 (6×2) | `/web/auth/profile`, `/web/auth/force-password-change` | USER |
| 1F | Admin | 46 (23×2) | `/web/admin/*`, `/web/audit` | ADMIN |
| **1G** | **Manager** | **8 (4×2)** | `/web/manager` | **MANAGER** |

### Capture Workflow (per sub-agent)

```python
async def capture_category(category: str, screenshots: list):
    # 1. Start dev server with dev_mocks scenario
    # 2. For each screenshot spec:
    #    a. Login as required role
    #    b. Navigate to route
    #    c. Set up any required state (open modals, select items, etc.)
    #    d. Set theme to light: page.evaluate("document.body.dataset.theme = 'light'")
    #    e. Capture → save to light/{category}/{name}.png
    #    f. Set theme to dark: page.evaluate("document.body.dataset.theme = 'dark'")
    #    g. Capture → save to dark/{category}/{name}.png
```

---

## Phase 1.5: Annotation Pass

**Sub-agent**: 1  
**Dependencies**: Phase 1 (all capture complete)

### Annotation Script Usage

```bash
python scripts/annotate_screenshots.py \
  --config docs/help-screenshot-annotations.yaml \
  --input pulldb/web/static/help/screenshots/ \
  --output pulldb/web/static/help/screenshots/annotated/
```

### Annotation Config Format

```yaml
# docs/help-screenshot-annotations.yaml
viewport: [1280, 720]
circle_radius: 16
circle_color: "#E53935"
text_color: "#FFFFFF"

screenshots:
  common/login.png:
    annotations:
      - position: [640, 280]
        number: 1
        label: "Username Field"
      - position: [640, 340]
        number: 2
        label: "Password Field"
      - position: [640, 420]
        number: 3
        label: "Login Button"
```

### Output Structure

```
screenshots/
├── light/                          # Raw captures
│   ├── common/
│   ├── dashboard/
│   ├── restore/
│   ├── jobs/
│   ├── profile/
│   ├── admin/
│   └── manager/                    # NEW
├── dark/                           # Raw captures
│   └── (same structure)
├── annotated/
│   ├── light/                      # With callouts
│   │   └── (same structure)
│   └── dark/                       # With callouts
│       └── (same structure)
```

---

## Phase 2: Help Template Updates

**Sub-agents**: 7 (parallel)  
**Dependencies**: Phase 1.5

### Sub-agent Assignments (UPDATED)

| Agent | Template | Screenshots to Insert |
|-------|----------|----------------------|
| 2A | `pulldb/web/templates/help/web-ui/index.html` | 9 |
| 2B | `pulldb/web/templates/help/web-ui/dashboard.html` | 5 |
| 2C | `pulldb/web/templates/help/web-ui/restore.html` | 6 |
| 2D | `pulldb/web/templates/help/web-ui/jobs.html` | 12 |
| 2E | `pulldb/web/templates/help/web-ui/profile.html` | 6 |
| 2F | `pulldb/web/templates/help/web-ui/admin.html` | 23 |
| **2G** | **`pulldb/web/templates/help/web-ui/manager.html`** | **4** (NEW FILE) |

### Insertion Points per Template

#### 2A: web-ui/index.html (9 screenshots) — FINAL
| After Section | Screenshot | Alt Text |
|---------------|------------|----------|
| "Accessing the Web Interface" | `common/login.png` | "pullDB login page with username and password fields" |
| "Accessing the Web Interface" | `common/login-error.png` | "Login page showing authentication error message" |
| "Navigation" | `common/sidebar-expanded.png` | "Sidebar navigation showing all menu items" |
| "Navigation" | `common/sidebar-collapsed.png` | "Collapsed sidebar with icon-only navigation" |
| "Role-Based Access" | `dashboard/admin-view.png` | "Admin dashboard showing role-specific features" |
| "Error Handling" | `common/404.png` | "404 Not Found error page" |
| "Error Handling" | `common/403.png` | "403 Forbidden access error page" |
| "Table Components" (NEW) | `common/table-filter-dropdown.png` | "LazyTable filter dropdown with search and checkboxes" |
| "Table Components" (NEW) | `common/table-sorted.png` | "Table column with sort indicator" |

#### 2B: web-ui/dashboard.html (5 screenshots)
| After Section | Screenshot | Alt Text |
|---------------|------------|----------|
| "For Users (USER Role)" | `dashboard/user-view.png` | "User dashboard with recent jobs and quick actions" |
| "For Managers (MANAGER Role)" | `dashboard/manager-view.png` | "Manager dashboard showing team activity" |
| "For Administrators (ADMIN Role)" | `dashboard/admin-view.png` | "Admin dashboard with system health overview" |
| "Stats Cards" | `dashboard/stats-cards.png` | "Dashboard stats showing active, queued, and completed jobs" |
| "Recent Jobs" | `dashboard/recent-jobs.png` | "Recent jobs table with status and actions" |

#### 2C: web-ui/restore.html (6 screenshots)
| After Section | Screenshot | Alt Text |
|---------------|------------|----------|
| "Step 1: Select Customer" | `restore/step1-customer.png` | "Customer search with autocomplete results" |
| "Step 1: Select Customer" | `restore/step1-no-results.png` | "Customer search showing no results state" |
| "Step 2: Choose Backup" | `restore/step2-backups.png` | "Backup list showing available restore points" |
| "Step 3: Configure Options" | `restore/step3-options.png` | "Restore options including target host and retention" |
| "Step 4: Confirm & Submit" | `restore/step4-confirm.png` | "Restore confirmation summary" |
| "After Submission" | `restore/success-toast.png` | "Success notification with link to new job" |

#### 2D: web-ui/jobs.html (12 screenshots) — FINAL
| After Section | Screenshot | Alt Text |
|---------------|------------|----------|
| "Active Jobs Tab" | `jobs/list-active.png` | "Active jobs table with status indicators" |
| "Active Jobs Tab" | `jobs/list-empty.png` | "Empty active jobs state" |
| "Job History Tab" | `jobs/list-history.png` | "Completed jobs history with pagination" |
| "Filtering Jobs" | `jobs/filters-open.png` | "Filter panel with status, host, and date options" |
| "Job Details - Queued" (NEW) | `jobs/detail-queued.png` | "Queued job showing queue position" |
| "Job Details - Running" | `jobs/detail-running.png` | "Running job detail with progress and logs" |
| "Job Details - Download Phase" (NEW) | `jobs/detail-download-progress.png` | "Job downloading backup with progress bar" |
| "Job Details - Restore Phase" (NEW) | `jobs/detail-restore-progress.png` | "Job restoring tables with progress indicator" |
| "Job Details - Complete" | `jobs/detail-complete.png` | "Completed job with connection info" |
| "Job Details - Failed" | `jobs/detail-failed.png` | "Failed job showing error details" |
| "Job Details - Canceling" | `jobs/detail-canceling.png` | "Job in canceling state" |
| "Bulk Actions" | `jobs/bulk-actions.png` | "Multiple jobs selected with bulk action buttons" |

#### 2E: web-ui/profile.html (6 screenshots)
| After Section | Screenshot | Alt Text |
|---------------|------------|----------|
| "Profile Overview" | `profile/overview.png` | "User profile showing account details and role" |
| "Forced Password Change" | `profile/force-password-change.png` | "Forced password change page for account security" |
| "Changing Your Password" | `profile/password-form.png` | "Password change form with validation" |
| "API Keys" | `profile/api-keys.png` | "API key list with creation dates and revoke options" |
| "Creating an API Key" | `profile/create-key-modal.png` | "API key creation modal with name and expiry fields" |
| "Database Maintenance" (NEW) | `profile/maintenance-modal.png` | "Database maintenance acknowledgment modal" |

#### 2F: web-ui/admin.html (26 screenshots) — FINAL
| After Section | Screenshot | Alt Text |
|---------------|------------|----------|
| "Admin Dashboard Overview" | `admin/overview.png` | "Admin dashboard with quick stats and health checks" |
| "User Management" | `admin/users-list.png` | "User list with roles, status, and actions" |
| "Editing a User" | `admin/user-edit.png` | "User edit form with role and host assignments" |
| "Adding a User" | `admin/user-add.png` | "New user creation form" |
| "User Created Password" (DEEP) | `admin/user-created-password.png` | "Generated password display after user creation" |
| "User Host Assignment" (DEEP) | `admin/user-hosts-modal.png` | "Host checkbox assignment modal" |
| "User API Keys" (DEEP) | `admin/user-api-keys-modal.png` | "User's API keys with status badges" |
| "Force Delete User" (DEEP) | `admin/user-force-delete.png` | "Force delete with database selection" |
| "Host Management" | `admin/hosts-list.png` | "Database hosts with capacity and status indicators" |
| "Host Details" | `admin/host-detail.png` | "Host detail page with configuration" |
| "Adding a Host" | `admin/host-add.png` | "New host configuration form" |
| "Host Deletion" (DEEP) | `admin/host-delete-modal.png` | "Host deletion confirmation with affected items" |
| "API Key Management" | `admin/api-keys.png` | "System-wide API key overview" |
| "API Key Approval" | `admin/api-key-approval.png` | "Pending API key approval queue" |
| "System Settings" | `admin/settings.png` | "Configurable system settings" |
| "Settings Danger Confirm" (DEEP) | `admin/settings-danger-confirm.png` | "Dangerous setting change warning" |
| "Maintenance Tools" | `admin/maintenance.png` | "Database cleanup and maintenance options" |
| "Prune Logs Preview" | `admin/prune-logs.png` | "Log pruning preview with selectable entries" |
| "Cleanup Staging" | `admin/cleanup-staging.png` | "Staging cleanup preview" |
| "Orphan Databases" | `admin/orphans.png` | "Orphan database management" |
| "Audit Log" | `admin/audit-log.png` | "Audit log browser with filters" |
| "Locked Databases" | `admin/locked-dbs.png` | "Locked database management" |
| "Disallowed Users" | `admin/disallowed-users.png` | "Disallowed usernames management" |

#### 2G: web-ui/manager.html (4 screenshots) — NEW FILE
| After Section | Screenshot | Alt Text |
|---------------|------------|----------|
| "Manager Dashboard Overview" | `manager/overview.png` | "Manager dashboard with team statistics" |
| "Team Members" | `manager/team-list.png` | "Team member list with status indicators" |
| "Reset Team Member Password" | `manager/reset-password.png` | "Password reset confirmation dialog" |
| "Assign Temporary Password" | `manager/temp-password-modal.png` | "Temporary password assignment modal" |

---

## Phase 3: Validation & Finalization

**Sub-agent**: 1  
**Dependencies**: Phase 2

### Tasks

| # | Task | Description |
|---|------|-------------|
| 3.1 | Visual validation | Load each help page in browser, verify screenshots render in both themes |
| 3.2 | Accessibility check | Ensure all `<img>` have meaningful alt text |
| 3.3 | Link validation | Verify all image paths resolve correctly |
| 3.4 | File size optimization | Run `pngquant` on all screenshots (~28MB → ~10MB) |
| 3.5 | Update HELP-PAGE-INDEX.md | Add screenshot inventory section |
| 3.6 | Update WORKSPACE-INDEX.md | Add new files to index |
| 3.7 | Create manager.html help page | NEW: Create `help/web-ui/manager.html` template |

---

## Complete Screenshot Manifest (FINAL - 69 unique screenshots × 2 themes = 138 total)

### Common (18 screenshots: 9 light + 9 dark) — FINAL

| Name | Route | State | Annotations |
|------|-------|-------|-------------|
| `login.png` | `/web/auth/login` | Empty form | 1. Username — 2. Password — 3. Remember Me — 4. Login Button |
| `login-error.png` | `/web/auth/login` | Error state | 1. Error Message — 2. Form Fields |
| `sidebar-collapsed.png` | `/web/dashboard` | Sidebar collapsed | 1. Collapse Toggle — 2. Nav Icons — 3. Theme Toggle |
| `sidebar-expanded.png` | `/web/dashboard` | Sidebar expanded | 1. Logo — 2. Menu Items — 3. User Menu — 4. Theme Toggle |
| `404.png` | `/web/invalid` | Not found | 1. Error Code — 2. Message — 3. Home Link |
| `500.png` | N/A (triggered) | Server error | 1. Error Code — 2. Message — 3. Retry |
| `403.png` | N/A (triggered) | Forbidden | 1. Error Code — 2. Access Denied Message — 3. Back Link |
| `table-filter-dropdown.png` | `/web/admin/users` | Filter open | 1. Filter Button — 2. Search Box — 3. Checkbox Options — 4. Apply |
| `table-sorted.png` | `/web/jobs` | Sorted column | 1. Sort Arrow — 2. Column Header — 3. Sorted Data |

### Dashboard (10 screenshots: 5 light + 5 dark)

| Name | Route | Role | Annotations |
|------|-------|------|-------------|
| `user-view.png` | `/web/dashboard` | USER | 1. Stats Cards — 2. Recent Jobs — 3. Quick Restore |
| `manager-view.png` | `/web/dashboard` | MANAGER | 1. Team Stats — 2. Team Members — 3. Activity Feed |
| `admin-view.png` | `/web/dashboard` | ADMIN | 1. System Health — 2. Queue Status — 3. Admin Links |
| `stats-cards.png` | `/web/dashboard` | Any | 1. Active — 2. Queued — 3. Completed — 4. Failed |
| `recent-jobs.png` | `/web/dashboard` | USER | 1. Status Badge — 2. Customer — 3. Host — 4. Actions |

### Restore (12 screenshots: 6 light + 6 dark)

| Name | Route | State | Annotations |
|------|-------|-------|-------------|
| `step1-customer.png` | `/web/restore` | Step 1 active | 1. Search Input — 2. Customer List — 3. Selection Indicator |
| `step1-no-results.png` | `/web/restore` | Empty search | 1. Search Input — 2. No Results Message |
| `step2-backups.png` | `/web/restore` | Customer selected | 1. Backup Table — 2. Date Column — 3. Size — 4. Select Button |
| `step3-options.png` | `/web/restore` | Backup selected | 1. Target Host — 2. Retention Days — 3. Advanced Options |
| `step4-confirm.png` | `/web/restore` | Options set | 1. Summary Card — 2. Customer — 3. Backup — 4. Confirm Button |
| `success-toast.png` | `/web/restore` | After submit | 1. Success Message — 2. Job ID Link |

### Jobs (24 screenshots: 12 light + 12 dark) — FINAL

| Name | Route | State | Annotations |
|------|-------|-------|-------------|
| `list-active.png` | `/web/jobs` | Active tab | 1. Tab Selection — 2. Jobs Table — 3. Status Badge — 4. Actions |
| `list-empty.png` | `/web/jobs` | No jobs | 1. Empty State — 2. Create Job Link |
| `list-history.png` | `/web/jobs` | History tab | 1. Tab Selection — 2. Completed Jobs — 3. Pagination Controls |
| `filters-open.png` | `/web/jobs` | Filter panel open | 1. Status Filter — 2. Host Filter — 3. Date Range — 4. Apply Button |
| `detail-queued.png` | `/web/jobs/<id>` | Job queued | 1. Queued Badge — 2. Queue Position — 3. Cancel Option |
| `detail-running.png` | `/web/jobs/<id>` | Job running | 1. Progress Bar — 2. Live Logs — 3. Cancel Button — 4. Refresh |
| `detail-download-progress.png` | `/web/jobs/<id>` | Download phase | 1. Download Progress — 2. Bytes Downloaded — 3. Speed |
| `detail-restore-progress.png` | `/web/jobs/<id>` | Restore phase | 1. Restore Progress — 2. Tables Loaded — 3. Current Table |
| `detail-complete.png` | `/web/jobs/<id>` | Job complete | 1. Connection Info — 2. Copy Button — 3. Extend Retention — 4. Delete |
| `detail-failed.png` | `/web/jobs/<id>` | Job failed | 1. Error Message — 2. Stack Trace — 3. Retry Options |
| `detail-canceling.png` | `/web/jobs/<id>` | Canceling | 1. Cancel Status — 2. Progress Halted |
| `bulk-actions.png` | `/web/jobs` | Items selected | 1. Checkboxes — 2. Selection Count — 3. Bulk Delete — 4. Clear Selection |

### Profile (12 screenshots: 6 light + 6 dark)

| Name | Route | State | Annotations |
|------|-------|-------|-------------|
| `overview.png` | `/web/auth/profile` | Default | 1. Username — 2. Role Badge — 3. Allowed Hosts — 4. Preferences |
| `force-password-change.png` | `/web/auth/force-password-change` | Forced reset | 1. Security Notice — 2. New Password — 3. Confirm — 4. Submit |
| `password-form.png` | `/web/auth/profile` | Password section | 1. Current Password — 2. New Password — 3. Confirm — 4. Submit |
| `api-keys.png` | `/web/auth/profile` | API keys section | 1. Key Name — 2. Created Date — 3. Last Used — 4. Revoke Button |
| `create-key-modal.png` | `/web/auth/profile` | Modal open | 1. Name Field — 2. Expiry Dropdown — 3. Generate Button — 4. Cancel |
| `maintenance-modal.png` | `/web/auth/profile/maintenance` | Maint. modal | 1. Warning Message — 2. Acknowledge — 3. Continue |

### Manager (8 screenshots: 4 light + 4 dark) — NEW

| Name | Route | State | Annotations |
|------|-------|-------|-------------|
| `overview.png` | `/web/manager` | Default | 1. Team Stats — 2. Member Count — 3. Activity Summary |
| `team-list.png` | `/web/manager` | Team section | 1. Member Row — 2. Status — 3. Last Active — 4. Actions |
| `reset-password.png` | `/web/manager` | Modal | 1. Confirmation — 2. User Info — 3. Reset Button |
| `temp-password-modal.png` | `/web/manager` | Modal | 1. Generated Password — 2. Copy Button — 3. Done |

### Admin (46 screenshots: 23 light + 23 dark) — FINAL

| Name | Route | State | Annotations |
|------|-------|-------|-------------|
| `overview.png` | `/web/admin` | Default tab | 1. Quick Stats — 2. Health Indicators — 3. Navigation Tabs |
| `users-list.png` | `/web/admin/users` | User table | 1. User Row — 2. Role Column — 3. Status — 4. Edit/Disable Actions |
| `user-edit.png` | `/web/admin/users` | Edit modal | 1. Username — 2. Role Dropdown — 3. Host Assignments — 4. Save Button |
| `user-add.png` | `/web/admin/users` | Add form | 1. Username — 2. Password — 3. Role — 4. Create Button |
| `user-created-password.png` | `/web/admin/users` | Password modal | 1. Generated Password — 2. Copy Button — 3. Done |
| `user-hosts-modal.png` | `/web/admin/users` | Hosts modal | 1. Host Checkboxes — 2. Default Radio — 3. Save Button |
| `user-api-keys-modal.png` | `/web/admin/users` | API keys modal | 1. Key List — 2. Status Badge — 3. Revoke Action |
| `user-force-delete.png` | `/web/admin/users` | Force delete | 1. Warning — 2. Database Checkboxes — 3. Confirm Delete |
| `hosts-list.png` | `/web/admin/hosts` | Hosts view | 1. Host Card — 2. Capacity Bar — 3. Running Jobs — 4. Enable/Disable |
| `host-detail.png` | `/web/admin/hosts/<id>` | Detail page | 1. Configuration — 2. Credentials — 3. Active Jobs — 4. Edit |
| `host-add.png` | `/web/admin/hosts` | Add form | 1. Hostname — 2. Alias — 3. Max Concurrent — 4. Add Button |
| `host-delete-modal.png` | `/web/admin/hosts/<id>` | Delete modal | 1. Warning — 2. Affected Users — 3. Type to Confirm — 4. Delete |
| `api-keys.png` | `/web/admin/api-keys` | Keys list | 1. Key Table — 2. Owner Column — 3. Scope — 4. Revoke All |
| `api-key-approval.png` | `/web/admin/api-keys` | Pending | 1. Pending Queue — 2. Requester — 3. Approve/Deny |
| `settings.png` | `/web/admin/settings` | Settings page | 1. Setting Name — 2. Current Value — 3. Edit Button — 4. Description |
| `settings-danger-confirm.png` | `/web/admin/settings` | Danger modal | 1. Warning Icon — 2. Setting Name — 3. Confirm Button |
| `maintenance.png` | `/web/admin/maintenance` | Maintenance tab | 1. Cleanup Preview — 2. Prune Logs — 3. Execute Button |
| `prune-logs.png` | `/web/admin/prune-logs` | Preview | 1. Log Entries — 2. Date Range — 3. Size — 4. Prune Button |
| `cleanup-staging.png` | `/web/admin/cleanup-staging` | Preview | 1. Staging DBs — 2. Age — 3. Owner — 4. Cleanup Button |
| `orphans.png` | `/web/admin/orphans` | Orphan list | 1. Database Row — 2. Size — 3. Last Modified — 4. Actions |
| `audit-log.png` | `/web/audit` | Audit browser | 1. Filter Bar — 2. Log Entry — 3. Timestamp — 4. Details Expand |
| `locked-dbs.png` | `/web/admin/locked-databases` | Locked list | 1. Database Name — 2. Owner — 3. Lock Date — 4. Unlock Button |
| `disallowed-users.png` | `/web/admin/disallowed-users` | User list | 1. Username — 2. Reason — 3. Added Date — 4. Remove |

### Manager (8 screenshots: 4 light + 4 dark)

| Name | Route | State | Annotations |
|------|-------|-------|-------------|
| `overview.png` | `/web/manager` | Default | 1. Team Stats — 2. Member Count — 3. Activity Summary |
| `team-list.png` | `/web/manager` | Team section | 1. Member Row — 2. Status — 3. Last Active — 4. Actions |
| `reset-password.png` | `/web/manager` | Modal | 1. Confirmation — 2. User Info — 3. Reset Button |
| `temp-password-modal.png` | `/web/manager` | Modal | 1. Generated Password — 2. Copy Button — 3. Done |

---

## Screenshot Count Summary (FINAL)

| Category | Light | Dark | Total |
|----------|-------|------|-------|
| Common | 9 | 9 | 18 |
| Dashboard | 5 | 5 | 10 |
| Restore | 6 | 6 | 12 |
| Jobs | 12 | 12 | 24 |
| Profile | 6 | 6 | 12 |
| Admin | 23 | 23 | 46 |
| Manager | 4 | 4 | 8 |
| **TOTAL** | **65** | **65** | **130** |

---

## Execution Timeline

```
Phase 0   ─────────────────────────────────────────────▶ Infrastructure (1 agent)
Phase 0.5 ─────────────────────────────────────────────▶ Simulation Data (1 agent)
                          │
                          ▼
Phase 1   ┬─ 1A: Common ──┬─ 1B: Dashboard ──┬─ 1C: Restore ──┐
          ├─ 1D: Jobs ────┼─ 1E: Profile ────┼─ 1F: Admin ────┤ (7 parallel)
          └─ 1G: Manager ─┴──────────────────┴────────────────┘
                          │
                          ▼
Phase 1.5 ─────────────────────────────────────────────▶ Annotation (1 agent)
                          │
                          ▼
Phase 2   ┬─ 2A: index ───┬─ 2B: dashboard ──┬─ 2C: restore ──┐
          ├─ 2D: jobs ────┼─ 2E: profile ────┼─ 2F: admin ────┤ (7 parallel)
          └─ 2G: manager ─┴──────────────────┴────────────────┘
                          │
                          ▼
Phase 3   ─────────────────────────────────────────────▶ Validation (1 agent)
```

**Total Phases**: 6  
**Total Sub-agents**: 18  
**Parallelization**: Phase 1 (7 parallel), Phase 2 (7 parallel)

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Annotation coordinates misaligned | Callouts point to wrong elements | Capture raw first, manually verify 3-4 screenshots, then annotate |
| Dev server instability | Screenshots fail mid-capture | Add retry logic, checkpoint progress per screenshot |
| Theme toggle not working | Dark screenshots identical to light | Verify theme CSS variables applied before capture |
| Large file sizes slow help pages | Poor UX | Run `pngquant --quality=80-90` on all PNGs |
| Missing routes discovered | Plan incomplete | ✅ Audit completed - all routes now covered |

---

## Audit Checklist (POST-AUDIT: ALL COVERED)

### Routes Covered

- [x] `/web/auth/login` — Common
- [x] `/web/auth/logout` — N/A (redirect only)
- [x] `/web/auth/force-password-change` — Profile ✅ ADDED
- [x] `/web/auth/profile` — Profile
- [x] `/web/auth/profile/maintenance` — Profile ✅ ADDED
- [x] `/web/dashboard` — Dashboard
- [x] `/web/restore` — Restore
- [x] `/web/jobs` — Jobs
- [x] `/web/jobs/<id>` — Jobs
- [x] `/web/manager` — Manager ✅ ADDED (new help page)
- [x] `/web/admin` — Admin
- [x] `/web/admin/users` — Admin
- [x] `/web/admin/hosts` — Admin
- [x] `/web/admin/hosts/<id>` — Admin ✅ ADDED
- [x] `/web/admin/settings` — Admin
- [x] `/web/admin/api-keys` — Admin
- [x] `/web/admin/prune-logs` — Admin ✅ ADDED
- [x] `/web/admin/cleanup-staging` — Admin ✅ ADDED
- [x] `/web/admin/orphans` — Admin ✅ ADDED
- [ ] `/web/admin/orphans/<id>` — Deferred (detail view, low priority)
- [ ] `/web/admin/user-orphans` — Deferred (edge case, low priority)
- [x] `/web/admin/disallowed-users` — Admin ✅ ADDED
- [x] `/web/admin/locked-databases` — Admin
- [ ] `/web/admin/task-status` — Deferred (internal tooling, low priority)
- [ ] `/web/admin/styleguide` — Deferred (dev reference, low priority)
- [x] `/web/audit` — Admin
- [x] Error pages (404, 500) — Common ✅ ADDED

### Help Pages Covered

- [ ] `help/index.html` — Not in scope (overview only)
- [ ] `help/getting-started.html` — Not in scope (text-focused)
- [ ] `help/api.html` — Not in scope (reference)
- [ ] `help/cli.html` — Not in scope (reference)
- [ ] `help/job-lifecycle.html` — Not in scope (concepts)
- [ ] `help/troubleshooting.html` — Not in scope (support)
- [x] `help/web-ui/index.html` — In scope (6 screenshots)
- [x] `help/web-ui/dashboard.html` — In scope (5 screenshots)
- [x] `help/web-ui/restore.html` — In scope (6 screenshots)
- [x] `help/web-ui/jobs.html` — In scope (9 screenshots)
- [x] `help/web-ui/profile.html` — In scope (6 screenshots)
- [x] `help/web-ui/admin.html` — In scope (18 screenshots)
- [x] **`help/web-ui/manager.html`** — ✅ ADDED (4 screenshots) — NEW FILE

---

## Appendix A: Complete Route Inventory

### Auth Routes (11 total, 4 with UI pages)

| Route | Method | Has UI | In Plan |
|-------|--------|--------|---------|
| `/web/auth/login` | GET/POST | ✅ | ✅ |
| `/web/auth/logout` | GET | ❌ (redirect) | N/A |
| `/web/auth/force-password-change` | GET/POST | ✅ | ✅ |
| `/web/auth/profile` | GET | ✅ | ✅ |
| `/web/auth/profile` | POST (password) | ❌ | N/A |
| `/web/auth/profile` | POST (api-key) | ❌ | N/A |
| `/web/auth/profile` | POST (revoke-key) | ❌ | N/A |
| `/web/auth/profile` | POST (default-host) | ❌ | N/A |
| `/web/auth/profile/maintenance` | GET/POST | ✅ | ✅ |

### Dashboard Routes (1 total)

| Route | Method | Has UI | In Plan |
|-------|--------|--------|---------|
| `/web/dashboard` | GET | ✅ | ✅ |

### Restore Routes (4 total, 1 UI page)

| Route | Method | Has UI | In Plan |
|-------|--------|--------|---------|
| `/web/restore` | GET | ✅ | ✅ |
| `/web/restore` | POST | ❌ | N/A |
| `/web/restore/search-customers` | GET | ❌ (AJAX) | N/A |
| `/web/restore/search-backups` | GET | ❌ (HTMX) | N/A |

### Jobs Routes (10 total, 2 UI pages)

| Route | Method | Has UI | In Plan |
|-------|--------|--------|---------|
| `/web/jobs` | GET | ✅ | ✅ |
| `/web/jobs/<id>` | GET | ✅ | ✅ |
| `/web/jobs/<id>/cancel` | POST | ❌ | N/A |
| `/web/jobs/<id>/delete` | POST | ❌ | N/A |
| `/web/jobs/<id>/extend` | POST | ❌ | N/A |
| `/web/jobs/<id>/lock` | POST | ❌ | N/A |
| `/web/jobs/<id>/unlock` | POST | ❌ | N/A |
| `/web/jobs/<id>/complete` | POST | ❌ | N/A |
| `/web/jobs/bulk-delete` | POST | ❌ | N/A |
| `/web/jobs/api/jobs` | GET | ❌ (API) | N/A |

### Manager Routes (6 total, 1 UI page)

| Route | Method | Has UI | In Plan |
|-------|--------|--------|---------|
| `/web/manager` | GET | ✅ | ✅ |
| `/web/manager/team-members` | GET | ❌ (API) | N/A |
| `/web/manager/reset-password` | POST | ❌ | N/A |
| `/web/manager/clear-password-reset` | POST | ❌ | N/A |
| `/web/manager/enable-user` | POST | ❌ | N/A |
| `/web/manager/disable-user` | POST | ❌ | N/A |

### Admin Routes (30+ total, 15+ UI pages)

| Route | Method | Has UI | In Plan |
|-------|--------|--------|---------|
| `/web/admin` | GET | ✅ | ✅ |
| `/web/admin/users` | GET | ✅ | ✅ |
| `/web/admin/hosts` | GET | ✅ | ✅ |
| `/web/admin/hosts/<id>` | GET | ✅ | ✅ |
| `/web/admin/settings` | GET | ✅ | ✅ |
| `/web/admin/api-keys` | GET | ✅ | ✅ |
| `/web/admin/prune-logs` | GET | ✅ | ✅ |
| `/web/admin/cleanup-staging` | GET | ✅ | ✅ |
| `/web/admin/orphans` | GET | ✅ | ✅ |
| `/web/admin/disallowed-users` | GET | ✅ | ✅ |
| `/web/admin/locked-databases` | GET | ✅ | ✅ |
| `/web/audit` | GET | ✅ | ✅ |

### Error Routes

| Route | Template | In Plan |
|-------|----------|---------|
| Any invalid URL | `404.html` | ✅ |
| Server error | `500.html` | ✅ |
| Forbidden access | `403.html` | ✅ |

---

## Appendix B: Annotation Coordinates

*To be populated during Phase 1.5*

---

## Appendix C: Deferred Items (Low Priority)

These items were identified during audit but deferred due to low user impact:

| Item | Reason Deferred |
|------|-----------------|
| `/web/admin/orphans/<id>` | Detail view rarely accessed |
| `/web/admin/user-orphans` | Edge case for deleted users |
| `/web/admin/task-status` | Internal tooling page |
| `/web/admin/styleguide` | Developer reference only |
| Bulk cancel/delete progress modals | Transient states, hard to capture reliably |
| Toast messages | Transient, auto-dismiss quickly |
| Copy "Copied!" feedback state | Micro-interaction, too brief |

---

## Appendix D: Items Confirmed NOT Needed

| Item | Reason Not Needed |
|------|-------------------|
| Breadcrumbs | Only in help pages, not main app |
| Date picker UI | Uses native browser picker |
| Mobile nav drawer | Same sidebar, just narrower |
| Pagination controls | Built into LazyTable, visible in existing screenshots |
| Tooltips | Standard HTML title attributes, no custom popover |
| Multi-step host provisioning | Single modal form, not a wizard |

---

## Pre-Execution: Documentation Validation (2026-01-06)

### Animated Panel Validation

| Location | Content | vs. Actual CLI | Status |
|----------|---------|----------------|--------|
| `help/index.html` (Hero Terminal) | `pulldb restore acme` output | Matches `cli/main.py:784-791` | ✅ VALID |
| `help/index.html` (Status Demo) | `pulldb status` output with field alignment | Matches `cli/main.py:930-966` | ✅ VALID |
| `help/index.html` (Cancel Demo) | `pulldb cancel` output | Matches `cli/main.py:1550-1557` | ✅ VALID |
| `help/js/terminal.js` | Animation sequence output format | Matches actual CLI | ✅ VALID |

**Verification Details:**
- Restore output: `Job queued successfully!` + 7 indented fields ✓
- Status output: Dynamic field width using `max_label = max(len(f[0]) for f in fields)` ✓
- Cancel output: `✓ Job {id}... canceled successfully.` + message ✓

### S3 Configuration Validation

| Claim | Verified Status |
|-------|-----------------|
| "pullDB supports only single S3 endpoint" | ❌ **INCORRECT** |
| **Actual**: pullDB supports **multiple S3 backup locations** | ✅ |

**Evidence:**
- `config.py:157` - `s3_backup_locations: tuple[S3BackupLocationConfig, ...]`
- `packaging/env.example:78` - `PULLDB_S3_BACKUP_LOCATIONS='[...]'` JSON array
- `docs/KNOWLEDGE-POOL.json:54` - "PULLDB_S3_BACKUP_LOCATIONS is the only active config var"

**Documentation Status:**
- ✅ Help pages do NOT incorrectly claim single endpoint (all S3 refs are generic)
- ✅ `packaging/env.example` shows proper JSON array format
- ✅ `docs/hca/shared/configuration.md` marks `PULLDB_S3_BACKUP_LOCATIONS` as **required**
- ⚠️ Legacy `s3_bucket_path` field still supported as fallback (deprecated)
- ℹ️ `docs/archived/README-old.md:309` mentions "single backup source initially" but is in archived folder (acceptable)

### Validation Summary

| Category | Items Checked | Issues Found | Status |
|----------|---------------|--------------|--------|
| Animated Panels | 4 | 0 | ✅ All match current CLI output |
| S3 Configuration | Help pages, config docs | 0 | ✅ Multiple endpoints supported, docs accurate |
| Terminal Examples | 10+ static terminals | 0 | ✅ All match current CLI format |

**Result: All documentation is current and accurate. No updates required.**

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-01-06 | Initial plan created | Copilot |
| 2026-01-06 | First audit: Added 28 missing routes, manager.html help page | Copilot |
| 2026-01-06 | Deep audit: Added 17 modal dialogs, 5 empty/error states, 403 page | Copilot |
| 2026-01-06 | Final audit: Added table UI patterns, job phase details, 3 job states | Copilot |
| 2026-01-06 | **FINAL**: 130 total screenshots (65 light + 65 dark), 7 help pages | Copilot |
| 2026-01-06 | Documentation validation: Animated panels ✅, S3 multi-endpoint ✅ | Copilot |
