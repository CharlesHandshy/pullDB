# Button Audit Checklist

> Generated: 2025-12-27
> Purpose: Track visual verification of all buttons across light/dark modes

## Verification Key

- ✅ = Verified working (contrast, hover, active, disabled, focus)
- ⚠️ = Partial (some states broken)
- ❌ = Broken (visibility/contrast issues)
- 🔲 = Not tested yet

## Phase 1: Dark Mode Button Visibility

### Priority 1: Primary Action Buttons (Most Used)

| Page | Button | Class | Light | Dark | Notes |
|------|--------|-------|-------|------|-------|
| **All pages** | Sidebar toggle | `btn-icon` | 🔲 | 🔲 | |
| **All pages** | Theme toggle | `btn-icon` | 🔲 | 🔲 | |
| **Dashboard** | New Restore Job | `btn btn-primary` | 🔲 | 🔲 | |
| **Dashboard** | View buttons | `btn btn-secondary btn-sm` | 🔲 | 🔲 | |
| **Jobs List** | New Restore Job | `btn btn-primary` | 🔲 | 🔲 | |
| **Jobs List** | Cancel Job | `cancel-job-btn` | 🔲 | 🔲 | |
| **Jobs List** | Cancel All Jobs | `btn btn-cancel-all` | 🔲 | 🔲 | |
| **Jobs List** | Bulk Cancel | `btn btn-danger` | 🔲 | 🔲 | |
| **Job Details** | Cancel Job | `btn btn-danger` | 🔲 | 🔲 | |
| **Job Details** | Auto-refresh | `btn btn-secondary btn-sm` | 🔲 | 🔲 | |
| **Restore** | Submit Restore | `btn btn-primary btn-queue` | 🔲 | 🔲 | |
| **Restore** | Load More | `load-more-btn` | 🔲 | 🔲 | |
| **Restore** | Reset Date | `btn btn-secondary btn-sm` | 🔲 | 🔲 | |

### Priority 2: Auth Pages

| Page | Button | Class | Light | Dark | Notes |
|------|--------|-------|-------|------|-------|
| **Login** | Submit | `auth-submit` | 🔲 | 🔲 | Legacy class |
| **Login** | Theme toggle | `btn-icon` | 🔲 | 🔲 | |
| **Profile** | Save | `btn btn-primary` | 🔲 | 🔲 | |
| **Profile** | Password toggle | `password-toggle` | 🔲 | 🔲 | |
| **Change Password** | Submit | `btn btn-primary` | 🔲 | 🔲 | |
| **Change Password** | Cancel | `btn btn-secondary` | 🔲 | 🔲 | |

### Priority 3: Admin Pages

| Page | Button | Class | Light | Dark | Notes |
|------|--------|-------|-------|------|-------|
| **Admin - Hosts** | Add New Host | `btn-icon btn-icon-primary` | 🔲 | 🔲 | |
| **Admin - Hosts** | Modal Cancel | `btn btn-ghost` | 🔲 | 🔲 | |
| **Admin - Hosts** | Provision | `btn btn-primary` | 🔲 | 🔲 | |
| **Admin - Host Detail** | Save Changes | `btn btn-primary btn-sm` | 🔲 | 🔲 | |
| **Admin - Host Detail** | Disable/Enable | `btn btn-warning btn-sm` | 🔲 | 🔲 | |
| **Admin - Host Detail** | View in AWS | `btn btn-xs btn-ghost` | 🔲 | 🔲 | |
| **Admin - Users** | Add New User | `btn-icon btn-icon-primary` | 🔲 | 🔲 | |
| **Admin - Users** | Manage Hosts | `action-btn action-btn-primary` | 🔲 | 🔲 | |
| **Admin - Users** | Clear Password | `action-btn action-btn-danger` | 🔲 | 🔲 | |
| **Admin - Users** | Delete User | `action-btn action-btn-danger-muted` | 🔲 | 🔲 | |
| **Admin - Users** | Disabled action | `action-btn action-btn-disabled` | 🔲 | 🔲 | |
| **Admin - Settings** | Export | `btn btn-secondary btn-sm` | 🔲 | 🔲 | |
| **Admin - Settings** | Edit | `btn btn-secondary btn-xs edit-btn` | 🔲 | 🔲 | |
| **Admin - Settings** | Save | `btn btn-primary btn-xs` | 🔲 | 🔲 | |
| **Admin - Settings** | Reset | `btn btn-secondary btn-xs reset-btn` | 🔲 | 🔲 | |
| **Admin - Prune** | Refresh Preview | `btn btn-secondary` | 🔲 | 🔲 | |
| **Admin - Prune** | Exclude/Include | `exclude-btn` | 🔲 | 🔲 | |
| **Admin - Prune** | Reset Exclusions | `reset-exclusions-btn` | 🔲 | 🔲 | |
| **Admin - Prune** | Cancel | `btn btn-secondary` | 🔲 | 🔲 | |
| **Admin - Prune** | Delete Jobs Events | `btn btn-danger` | 🔲 | 🔲 | **REPORTED ISSUE** |
| **Admin - Cleanup** | Execute | `btn btn-danger` | 🔲 | 🔲 | |
| **Admin - Orphans** | Delete orphan | `btn btn-sm btn-danger` | 🔲 | 🔲 | |
| **Admin - Appearance** | Reset | `btn btn-secondary` | 🔲 | 🔲 | |
| **Admin - Appearance** | Save | `btn btn-primary` | 🔲 | 🔲 | |

### Priority 4: Error Pages

| Page | Button | Class | Light | Dark | Notes |
|------|--------|-------|-------|------|-------|
| **404** | Go to Dashboard | `btn btn-primary` | 🔲 | 🔲 | |
| **404** | Go Back | `btn btn-secondary` | 🔲 | 🔲 | |
| **Error** | Go to Dashboard | `btn btn-primary` | 🔲 | 🔲 | |
| **Error** | Go Back | `btn btn-secondary` | 🔲 | 🔲 | |

### Priority 5: Audit Page

| Page | Button | Class | Light | Dark | Notes |
|------|--------|-------|-------|------|-------|
| **Audit** | Back to Admin | `back-btn` | 🔲 | 🔲 | |
| **Audit** | Clear Filters | `clear-filters-btn` | 🔲 | 🔲 | |

---

## Phase 2: Button States Verification

### Hover States

| Variant | Light Hover | Dark Hover | Notes |
|---------|-------------|------------|-------|
| `btn-primary` | 🔲 | 🔲 | |
| `btn-secondary` | 🔲 | 🔲 | |
| `btn-danger` | 🔲 | 🔲 | |
| `btn-success` | 🔲 | 🔲 | |
| `btn-warning` | 🔲 | 🔲 | |
| `btn-ghost` | 🔲 | 🔲 | |
| `btn-outline` | 🔲 | 🔲 | |
| `btn-icon` | 🔲 | 🔲 | |
| `action-btn` variants | 🔲 | 🔲 | |

### Active/Pressed States

| Variant | Light Active | Dark Active | Notes |
|---------|--------------|-------------|-------|
| `btn-primary` | 🔲 | 🔲 | Currently only one with :active |
| `btn-secondary` | 🔲 | 🔲 | MISSING |
| `btn-danger` | 🔲 | 🔲 | MISSING |
| `btn-success` | 🔲 | 🔲 | MISSING |
| `btn-warning` | 🔲 | 🔲 | MISSING |
| `btn-ghost` | 🔲 | 🔲 | MISSING |
| `btn-outline` | 🔲 | 🔲 | MISSING |

### Disabled States

| Variant | Light Disabled | Dark Disabled | Notes |
|---------|----------------|---------------|-------|
| `btn-primary` | 🔲 | 🔲 | |
| `btn-secondary` | 🔲 | 🔲 | |
| `btn-danger` | 🔲 | 🔲 | |
| `btn-queue` | 🔲 | 🔲 | Has disabled state |
| `btn-cancel-all` | 🔲 | 🔲 | Has disabled state |
| `action-btn-disabled` | 🔲 | 🔲 | |

### Focus States (Keyboard Navigation)

| Variant | Light Focus | Dark Focus | Notes |
|---------|-------------|------------|-------|
| `btn` (base) | 🔲 | 🔲 | Has :focus-visible |
| `action-btn` | 🔲 | 🔲 | MISSING |
| `btn-icon` | 🔲 | 🔲 | Has :focus-visible |

---

## Phase 3: Consolidation Verification

### Duplicate Definitions to Merge

| Class | Source Files | Merged To | Verified |
|-------|--------------|-----------|----------|
| `.btn-icon` | buttons.css (36px), admin.css (32px) | buttons.css | 🔲 |
| `.btn-danger` | buttons.css, admin.css | buttons.css | 🔲 |
| `.btn.loading` | buttons.css, restore.css | buttons.css | 🔲 |

---

## Phase 4: Legacy Migration Verification

| Old Class | New Class | Files to Update | Verified |
|-----------|-----------|-----------------|----------|
| `auth-submit` | `btn btn-primary` | login.html | 🔲 |
| `backup-search-again-btn` | TBD | restore.html | 🔲 |
| `password-toggle` | TBD | profile.html, change_password.html | 🔲 |
| `clear-filters-btn` | TBD | audit/index.html | 🔲 |
| `select-btn` | TBD | cleanup_preview.html | 🔲 |

---

## Playwright Test URLs

```
# Base URL (assuming local dev)
BASE=http://localhost:8000

# Auth Pages
$BASE/auth/login
$BASE/auth/profile
$BASE/auth/change-password

# Dashboard (role-dependent)
$BASE/dashboard

# Jobs
$BASE/jobs
$BASE/jobs/{job_id}

# Restore
$BASE/restore

# Admin (admin only)
$BASE/admin
$BASE/admin/hosts
$BASE/admin/hosts/{host_id}
$BASE/admin/users
$BASE/admin/settings
$BASE/admin/prune
$BASE/admin/cleanup
$BASE/admin/orphans
$BASE/admin/user-orphans
$BASE/admin/audit

# Error pages
$BASE/nonexistent  # 404
```

---

## Sign-off

| Phase | Completed | Verified By | Date |
|-------|-----------|-------------|------|
| Phase 1: Dark Mode | 🔲 | | |
| Phase 2: States | 🔲 | | |
| Phase 3: Consolidate | 🔲 | | |
| Phase 4: Legacy | 🔲 | | |
| Final Deploy | 🔲 | | |
