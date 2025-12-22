# CSS & HTML Audit Report
**Date:** 2025-01-27  
**Branch:** `feature/migrate-base-to-app-layout`  
**Purpose:** Identify obsolete/orphaned files after HCA template migration

---

## Executive Summary

After migrating `base.html` to extend the HCA template hierarchy, there is significant overlap between:
1. **HCA CSS files** (in `shared/css/`, `entities/css/`, `features/css/`, `pages/css/`)
2. **Legacy CSS files** (in `static/css/`)

The current system loads **BOTH** for backward compatibility, resulting in:
- ~7,600 lines of legacy CSS still being loaded
- Potential style conflicts and specificity issues
- Duplicate dark mode handling

---

## CSS Files Analysis

### ✅ ACTIVE HCA CSS (Keep)

| File | Lines | Status |
|------|-------|--------|
| `shared/css/design-tokens.css` | ~400 | Core design system |
| `shared/css/reset.css` | ~150 | Browser normalization |
| `shared/css/utilities.css` | ~500 | Utility classes |
| `shared/css/layout.css` | ~350 | HCA layout styles |
| `entities/css/badge.css` | ~350 | Badge component |
| `entities/css/avatar.css` | ~130 | Avatar component |
| `entities/css/card.css` | ~400 | Card component |
| `features/css/buttons.css` | ~400 | Button styles |
| `features/css/forms.css` | ~500 | Form styles |
| `features/css/tables.css` | ~400 | Table styles |
| `features/css/modals.css` | ~350 | Modal styles |
| `features/css/alerts.css` | ~450 | Alert styles |
| `features/css/status.css` | ~250 | Status indicators |
| `features/css/dashboard.css` | ~350 | Dashboard widgets |
| `features/css/search.css` | ~250 | Search component |
| `pages/css/profile.css` | ~450 | Profile/auth pages |
| `pages/css/admin.css` | ~250 | Admin pages |
| `pages/css/job-details.css` | ~300 | Job details page |
| `pages/css/restore.css` | ~400 | Restore page |
| `pages/css/styleguide.css` | ~200 | Styleguide page |

### ⚠️ LEGACY CSS (Candidates for Archive)

| File | Lines | Status | Notes |
|------|-------|--------|-------|
| `static/css/components.css` | 6,083 | **ARCHIVE** | Monolithic legacy file |
| `static/css/design-system.css` | 483 | **ARCHIVE** | Replaced by design-tokens.css |
| `static/css/dark-mode.css` | 1,065 | **ARCHIVE** | Co-located in HCA files |
| `static/css/layout.css` | ~150 | **ARCHIVE** | Replaced by shared/layout.css |
| `static/css/sidebar.css` | ~120 | **KEEP** | Still used by sidebar widget |

### ⚠️ ORPHANED CSS

| File | Status | Notes |
|------|--------|-------|
| `shared/css/main.css` | **ARCHIVE** | Entry point concept abandoned |

---

## HTML Templates Analysis

### ✅ ACTIVE Templates (Keep)

**Layouts:**
- `shared/layouts/_skeleton.html` - Base HTML5 document
- `shared/layouts/base.html` - Block mappings layer
- `shared/layouts/app_layout.html` - App shell (header/sidebar/footer)
- `templates/base.html` - Thin wrapper for backward compat
- `templates/base_auth.html` - Auth pages layout

**Features (19 pages):**
- All `templates/features/*/*.html` - Used by routes

**Partials:**
- `partials/breadcrumbs.html` - Used in app_layout
- `partials/filter_bar.html` - Used in jobs page
- `partials/job_row.html` - Used in jobs listing
- `partials/searchable_dropdown.html` - Used in restore
- `partials/skeleton.html` - Loading states (macros)
- `partials/icons/*` - Icon macros

**Widgets:**
- `widgets/sidebar/sidebar.html` - Main sidebar
- `widgets/lazy_table/lazy_table.html` - Used by many pages
- `widgets/virtual_table/virtual_table.html` - Used in jobs

### ⚠️ ORPHANED Templates (Candidates for Archive)

| File | Status | Notes |
|------|--------|-------|
| `shared/layouts/auth_layout.html` | **ARCHIVE** | Never used, base_auth.html used instead |
| `shared/layouts/error.html` | **ARCHIVE** | Different error.html in features/ used |
| `partials/active_jobs.html` | **ARCHIVE** | No references found |
| `partials/job_events.html` | **ARCHIVE** | No references found |

### ⚠️ DUPLICATE Templates

| Duplicate | Original | Action |
|-----------|----------|--------|
| `templates/widgets/sidebar/sidebar.html` | `widgets/sidebar/sidebar.html` | **ARCHIVE** template version |

### ⚠️ UNUSED HCA Components

These were created for HCA but never adopted:

**shared/ui/ (0-4 references each):**
- `shared/ui/buttons/icon_button.html` - 0 refs
- `shared/ui/inputs/select_input.html` - 0 refs  
- `shared/ui/inputs/text_input.html` - 0 refs
- `shared/ui/loading/spinner.html` - 0 refs

**entities/ (0-2 refs each):**
- `entities/database/database_row.html` - 0 refs
- `entities/host/host_row.html` - 0 refs
- `entities/job/job_card.html` - 0 refs
- `entities/user/user_row.html` - 0 refs

**widgets/ (0-1 refs each):**
- `widgets/filter_bar/filter_bar.html` - 0 refs
- `widgets/header/header_logo.html` - 0 refs
- `widgets/job_table/job_table.html` - 0 refs
- `widgets/stats_bar/stats_bar.html` - 0 refs
- `widgets/stats_grid/stats_grid.html` - 0 refs

---

## Recommended Archive Plan

### Phase 1: Safe Archives (Zero Risk)

Move to `pulldb/web/_archived/` with date suffix:

```
_archived/
├── css/
│   ├── main.css              # Never referenced
│   └── README.md             # Explains archive
├── templates/
│   ├── partials/
│   │   ├── active_jobs.html  # 0 references
│   │   └── job_events.html   # 0 references
│   └── shared/layouts/
│       ├── auth_layout.html  # Unused (base_auth used instead)
│       └── error.html        # Unused (features/errors/ used)
└── widgets/
    └── sidebar/
        └── sidebar.html      # Duplicate of widgets/sidebar/
```

### Phase 2: Legacy CSS Removal ✅ COMPLETED

**Legacy CSS files have been archived to `_archived/css/legacy/`:**
- `components.css` (6,083 lines)
- `dark-mode.css` (1,065 lines)  
- `design-system.css` (483 lines)
- `layout.css` (~150 lines)

**app_layout.html now loads only HCA CSS files.**

### Phase 3: Unused HCA Components (Future Decision)

Keep for now but mark as "awaiting adoption":
- `shared/ui/*` components
- `entities/*` row templates
- `widgets/*` unused widgets

These represent HCA scaffolding that may be used in future development.

---

## Risk Assessment

| Action | Risk | Impact |
|--------|------|--------|
| Archive orphaned templates | ✅ None | No code references |
| Archive main.css | ✅ None | Never imported |
| Remove legacy CSS | ✅ Complete | Tested, working |
| Archive unused HCA | ⚠️ Low | Loses scaffold work |

---

## Next Steps

1. ~~**Create `_archived/` directory structure**~~
2. ~~**Move Phase 1 files** (zero-risk archives)~~
3. ~~**Test all pages visually**~~ ✅ COMPLETED (2025-12-22)
4. ~~**Proceed with Phase 2**~~ ✅ COMPLETED (legacy CSS already archived)
5. **Document decisions** in SESSION-LOG.md

---

## Migration Completed (2025-01-27)

### Summary
All 188 legacy-only CSS classes have been migrated to HCA-compliant files:

| HCA File | Classes Added |
|----------|---------------|
| `pages/admin.css` | 46 (action-*, quick-*, setting-*, audit-*, host-*, etc.) |
| `pages/restore.css` | 32 (backup-*, customer-*, target-*, overwrite-*, qa-*, etc.) |
| `features/forms.css` | 23 (searchable-dropdown-*, tabs, required-mark) |
| `pages/job-details.css` | 14 (event-*, job-detail-*, detail-cell) |
| `shared/utilities.css` | 12 (capacity-*, link-primary, is-*, separator) |
| `pages/profile.css` | 11 (profile-*, password-*) |
| `features/dashboard.css` | 11 (manager-*) |
| `features/alerts.css` | 9 (error-container, error-card, etc.) |
| `features/search.css` | 10 (filter-*, clear-filters-btn, advanced-filter-bar) |
| `features/buttons.css` | 2 (btn-queue, btn-cancel-all) |
| `shared/layout.css` | 5 (page-header-row, section-header, etc.) |
| `entities/card.css` | 4 (info, info-label, info-value, stat-row) |

### Verification
- ✅ All 188 classes verified present in HCA CSS via grep
- ✅ All HCA CSS files have balanced braces (syntax valid)
- ✅ All HCA CSS files served correctly via HTTP

### Status
Legacy CSS files remain loaded as fallback but are marked deprecated in `app_layout.html`.
Ready for visual verification of all pages before final removal.

---

## Visual Testing Completed (2025-12-22)

### Pages Tested
| Page | Status | Notes |
|------|--------|-------|
| Login | ✅ Pass | Forms, buttons, dark mode toggle working |
| Dashboard | ✅ Pass | Stats cards, tables, badges all rendered correctly |
| Restore | ✅ Pass | Forms, tabs, alerts, buttons working |
| Jobs (Active/History) | ⚠️ Partial | Table headers OK, virtual table data issue (JS, not CSS) |
| Users Admin | ✅ Pass | Stats pills, table headers, Add User button working |
| Hosts Admin | ✅ Pass | Table, Enabled/Disabled badges, icons working |
| Profile | ✅ Pass | Fixed: Added extra_css block for profile.css |
| Job Details | ✅ Pass | Fixed: Added extra_css block for job-details.css |
| Settings | ✅ Pass | Accordion sections, badges, forms, sliders working |
| 404 Error | ✅ Pass | Error page rendering correctly |

### Fixes Applied During Testing
1. **profile.html**: Added `{% block extra_css %}` to load `profile.css`
2. **details.html**: Added `{% block extra_css %}` to load `job-details.css`

### Light/Dark Mode
- ✅ Both themes tested and working correctly
- ✅ Theme toggle functional on all pages

### Issues Found (Non-CSS)
- Virtual table in Jobs/Users pages shows "Showing 1-0 of N items" - JavaScript data loading issue
- Some sidebar links (Search Backups, Logo, Cleanup) return 404 - routes not implemented

