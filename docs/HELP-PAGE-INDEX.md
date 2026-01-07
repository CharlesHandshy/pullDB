# Help Page Index

> **Generated:** 2026-01-06  
> **Total Pages:** 13 (including manager.html)  
> **Base URL:** http://localhost:8000/web/help/

## Page Inventory

| # | Path | Title | Category | File Size |
|---|------|-------|----------|-----------|
| 1 | `/web/help/index.html` | pullDB Help Center | Root | - |
| 2 | `/web/help/pages/getting-started.html` | Getting Started | Guide | - |
| 3 | `/web/help/pages/api/index.html` | API Reference | Reference | - |
| 4 | `/web/help/pages/cli/index.html` | CLI Reference | Reference | - |
| 5 | `/web/help/pages/concepts/job-lifecycle.html` | Job Lifecycle | Concepts | - |
| 6 | `/web/help/pages/troubleshooting/index.html` | Troubleshooting | Support | - |
| 7 | `/web/help/pages/web-ui/index.html` | Web UI Overview | Web UI | - |
| 8 | `/web/help/pages/web-ui/dashboard.html` | Dashboard Guide | Web UI | - |
| 9 | `/web/help/pages/web-ui/restore.html` | Restore Wizard | Web UI | - |
| 10 | `/web/help/pages/web-ui/jobs.html` | Jobs & History | Web UI | - |
| 11 | `/web/help/pages/web-ui/profile.html` | Profile & Settings | Web UI | - |
| 12 | `/web/help/pages/web-ui/admin.html` | Administration | Web UI | - |
| 13 | `/web/help/pages/web-ui/manager.html` | Team Management | Web UI | NEW |

## Endpoints by Category

### Root
- `GET /web/help/` → Help Center landing page

### Guides
- `GET /web/help/pages/getting-started.html` → Quick start guide

### Reference Documentation
- `GET /web/help/pages/api/index.html` → REST API reference
- `GET /web/help/pages/cli/index.html` → CLI command reference

### Concepts
- `GET /web/help/pages/concepts/job-lifecycle.html` → Job states and phases

### Web UI Documentation (NEW)
- `GET /web/help/pages/web-ui/index.html` → Overview, access, navigation
- `GET /web/help/pages/web-ui/dashboard.html` → Dashboard views by role
- `GET /web/help/pages/web-ui/restore.html` → 4-step restore wizard
- `GET /web/help/pages/web-ui/jobs.html` → Job list, filtering, details
- `GET /web/help/pages/web-ui/profile.html` → Account settings, API keys
- `GET /web/help/pages/web-ui/admin.html` → User/host/key management
- `GET /web/help/pages/web-ui/manager.html` → Team management (managers only)

### Troubleshooting
- `GET /web/help/pages/troubleshooting/index.html` → Common issues, FAQ

## Static Assets
- `GET /web/help/css/help.css` → Main stylesheet
- `GET /web/help/search-index.json` → Search index (13 pages indexed)

---

## Screenshot Inventory (2026-01-06)

> **Location:** `pulldb/web/static/help/screenshots/`  
> **Total Files:** 254 PNG files  
> **Total Size:** 6.7 MB (after pngquant optimization from 19 MB)

### Directory Structure

| Directory | Count | Description |
|-----------|-------|-------------|
| `light/` | 65 | Raw light theme screenshots |
| `dark/` | 65 | Raw dark theme screenshots |
| `annotated/light/` | 62 | Annotated light screenshots |
| `annotated/dark/` | 62 | Annotated dark screenshots |

### Screenshots by Category (65 unique)

#### Common (9 screenshots)
| File | Description |
|------|-------------|
| `403.png` | Forbidden error page |
| `404.png` | Not found error page |
| `500.png` | Server error page |
| `login.png` | Login form |
| `login-error.png` | Login with error message |
| `sidebar-collapsed.png` | Collapsed sidebar navigation |
| `sidebar-expanded.png` | Expanded sidebar navigation |
| `table-filter-dropdown.png` | Table filter dropdown open |
| `table-sorted.png` | Table with sort indicator |

#### Dashboard (5 screenshots)
| File | Description |
|------|-------------|
| `admin-view.png` | Admin dashboard view |
| `manager-view.png` | Manager dashboard view |
| `user-view.png` | Regular user dashboard view |
| `stats-cards.png` | Statistics cards section |
| `recent-jobs.png` | Recent jobs widget |

#### Restore (6 screenshots)
| File | Description |
|------|-------------|
| `step1-customer.png` | Step 1 - Customer search |
| `step1-no-results.png` | Step 1 - No results found |
| `step2-backups.png` | Step 2 - Backup selection |
| `step3-options.png` | Step 3 - Restore options |
| `step4-confirm.png` | Step 4 - Confirmation |
| `success-toast.png` | Success notification |

#### Jobs (12 screenshots)
| File | Description |
|------|-------------|
| `list-active.png` | Active jobs list |
| `list-history.png` | Job history list |
| `list-empty.png` | Empty job list state |
| `filters-open.png` | Filters panel expanded |
| `bulk-actions.png` | Bulk actions dropdown |
| `detail-queued.png` | Job detail - queued state |
| `detail-running.png` | Job detail - running state |
| `detail-download-progress.png` | Job detail - download phase |
| `detail-restore-progress.png` | Job detail - restore phase |
| `detail-complete.png` | Job detail - completed |
| `detail-failed.png` | Job detail - failed |
| `detail-canceling.png` | Job detail - canceling |

#### Profile (6 screenshots)
| File | Description |
|------|-------------|
| `overview.png` | Profile overview tab |
| `password-form.png` | Change password form |
| `force-password-change.png` | Force password change prompt |
| `api-keys.png` | API keys tab |
| `create-key-modal.png` | Create API key modal |
| `maintenance-modal.png` | Maintenance mode modal |

#### Admin (23 screenshots)
| File | Description |
|------|-------------|
| `overview.png` | Admin dashboard overview |
| `users-list.png` | Users table |
| `user-add.png` | Add user form |
| `user-edit.png` | Edit user form |
| `user-created-password.png` | User created with temp password |
| `user-force-delete.png` | Force delete confirmation |
| `user-api-keys-modal.png` | User API keys modal |
| `user-hosts-modal.png` | User allowed hosts modal |
| `hosts-list.png` | Database hosts table |
| `host-add.png` | Add host form |
| `host-detail.png` | Host detail view |
| `host-delete-modal.png` | Delete host confirmation |
| `api-keys.png` | API keys management |
| `api-key-approval.png` | Approve API key modal |
| `disallowed-users.png` | Disallowed users list |
| `locked-dbs.png` | Locked databases view |
| `orphans.png` | Orphan databases view |
| `cleanup-staging.png` | Cleanup staging databases |
| `settings.png` | System settings |
| `settings-danger-confirm.png` | Danger zone confirmation |
| `maintenance.png` | Maintenance mode toggle |
| `audit-log.png` | Audit log viewer |
| `prune-logs.png` | Prune logs action |

#### Manager (4 screenshots)
| File | Description |
|------|-------------|
| `overview.png` | Manager overview |
| `team-list.png` | Team members list |
| `reset-password.png` | Reset password button |
| `temp-password-modal.png` | Temporary password modal |

---

## Visual Audit

### Screenshots Captured (2026-01-05)

| Page | Top Screenshot | Bottom Screenshot | Issues Found |
|------|----------------|-------------------|--------------|
| help/index.html | ✅ Captured | ✅ Captured | ✅ Fixed |
| getting-started.html | ✅ Captured | ✅ Captured | ✅ Fixed - added Web UI nav |
| api/index.html | ✅ Captured | ✅ Fixed | ✅ Fixed - added Web UI nav |
| cli/index.html | ✅ Captured | ✅ Fixed | ✅ Fixed - added Web UI nav |
| concepts/job-lifecycle.html | ✅ Captured | ✅ Partial | ✅ Fixed - added Web UI nav |
| troubleshooting/index.html | ✅ Captured | ✅ Captured | ✅ Fixed - added Web UI nav |
| web-ui/index.html | ✅ Captured | ✅ Fixed | ✅ Arrow SVG fixed |
| web-ui/dashboard.html | ✅ Captured | ✅ Fixed | ✅ Arrow SVG fixed |
| web-ui/restore.html | ✅ | ✅ | ✅ Fixed |
| web-ui/jobs.html | ✅ | ✅ | ✅ Fixed |
| web-ui/profile.html | ✅ | ✅ | ✅ Fixed |
| web-ui/admin.html | ✅ | ✅ | ✅ Fixed |

## Issues Summary (Post-Fix Status)

### ✅ RESOLVED Issues

1. **~~BLANK BOTTOM PAGES~~** (cli/index.html, api/index.html)
   - **Fixed:** Updated `.page-layout` min-height calculation in help.css
   - Content now displays properly with correct footer positioning

2. **~~OVERSIZED ARROW SVG~~** (web-ui/*.html, index.html)
   - **Fixed:** Added CSS constraints for `.category-arrow` (20x20px max)
   - Arrow icons now display at correct size within category cards

3. **~~404 CONSOLE ERRORS~~** (all pages)
   - **Fixed:** Added favicon `<link>` tags to all 12 HTML files
   - Remaining 404 is `search-index.json` (search feature not yet implemented)

4. **~~Missing "Web UI" Nav Link~~** (5 pages)
   - **Fixed:** Added "Web UI" nav link to:
     - troubleshooting/index.html
     - getting-started.html  
     - cli/index.html
     - api/index.html
     - concepts/job-lifecycle.html

### Remaining Minor Issues

5. **Footer Inconsistency**
   - Some pages have full footer (index.html)
   - Other pages have minimal footer (web-ui pages)
   - Consider standardizing in future update

6. **Search Feature**
   - `search-index.json` returns 404
   - Search functionality not yet implemented

---

## Fixes Applied (2026-01-05)

### CSS Changes (`pulldb/web/help/css/help.css`)
- Added `.category-cards` grid layout styles
- Added `.category-icon` styling (60x60px)
- Added `.category-content` flex container
- Added `.category-arrow` constraints (20x20px max-width/height)
- Fixed `.page-layout` min-height calculation
- Added `.page-content-full` for full-width layouts
- Added `.help-footer` styling

### HTML Changes (12 files)
- All pages: Added `<link rel="icon" href="...favicon.svg">`
- 5 pages: Added "Web UI" navigation link
- Consistent navigation across all help pages

---
*Audit completed: 2026-01-05*  
*Fixes verified: 2026-01-05*  
*This document is auto-updated during help page audits.*
