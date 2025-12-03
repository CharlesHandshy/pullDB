# pullDB Web UI - HCA Restructuring Plan

**Version**: 1.0.0  
**Created**: 2025-12-02  
**Purpose**: Restructure the pullDB Web UI using Hierarchical Containment Architecture (HCA) with Modular Architecture Principles (MAP)

---

## Executive Summary

The current web UI has:
- **1 monolithic routes.py** (1,214 lines) - violates atom size limits
- **Flat template structure** - violates containment principles
- **No clear layer separation** - violates HCA laws

This plan restructures the web UI into a clean HCA-compliant architecture.

---

## Current State Analysis

### Current Structure
```
pulldb/web/
├── __init__.py
├── routes.py                    # 1,214 lines - VIOLATION: >300 lines
└── templates/
    ├── base.html
    ├── login.html
    ├── dashboard.html
    ├── restore.html
    ├── search.html
    ├── job_detail.html
    ├── job_profile.html
    ├── error.html
    ├── admin/
    │   ├── jobs.html            # 518 lines - mixed concerns
    │   ├── users.html
    │   ├── user_detail.html
    │   ├── hosts.html
    │   ├── settings.html
    │   ├── cleanup.html
    │   └── logo.html
    └── partials/
        ├── filter_bar.html
        ├── job_row.html
        ├── active_jobs.html
        └── job_events.html
```

### Violations Identified

| Issue | HCA Law Violated | Severity |
|-------|------------------|----------|
| routes.py 1,214 lines | Law 1 (Atoms at Bottom) - Size limit | HIGH |
| All routes in one file | Law 2 (Containers Only Contain) | HIGH |
| Flat template structure | Law 4 (Names Tell Story) | MEDIUM |
| No interface contracts | Law 6 (Modules via Contracts) | MEDIUM |
| Mixed admin/user pages | Layer Model violation | MEDIUM |

---

## Target HCA Structure

### Layer Mapping for pullDB Web

| HCA Layer | pullDB Web Equivalent |
|-----------|----------------------|
| shared/ | Reusable UI components, utilities, contracts |
| entities/ | Domain models (Job, User, Host, Database) |
| features/ | User actions (login, restore, search, job-view) |
| widgets/ | Self-contained blocks (job-table, filter-bar, sidebar) |
| pages/ | Complete page compositions (dashboard, admin/jobs) |

### Target Directory Structure

```
pulldb/web/
├── __init__.py
├── router.py                     # Main router that includes all feature routers
├── dependencies.py               # Shared FastAPI dependencies
├── exceptions.py                 # Custom exceptions & handlers
│
├── shared/                       # Layer 0: Universal atoms
│   ├── __init__.py
│   ├── contracts/                # Interface definitions
│   │   ├── __init__.py
│   │   ├── page_interface.py     # BasePage contract
│   │   ├── widget_interface.py   # BaseWidget contract
│   │   └── service_interface.py  # Service contracts
│   ├── ui/                       # Reusable UI atoms
│   │   ├── buttons/
│   │   │   └── button.html
│   │   ├── inputs/
│   │   │   ├── text_input.html
│   │   │   └── select.html
│   │   ├── icons/
│   │   │   └── icons.html        # Icon macro definitions
│   │   └── typography/
│   │       └── headings.html
│   ├── layouts/                  # Layout templates
│   │   ├── base.html             # Base HTML structure
│   │   ├── auth_layout.html      # Layout for login pages
│   │   └── app_layout.html       # Layout for authenticated pages
│   └── utils/                    # Template utilities
│       ├── formatters.py         # Date, number formatters
│       └── validators.py         # Input validators
│
├── entities/                     # Layer 1: Domain display components
│   ├── __init__.py
│   ├── job/
│   │   ├── __init__.py
│   │   ├── job_card/
│   │   │   └── job_card.html     # Single job display atom
│   │   ├── job_row/
│   │   │   └── job_row.html      # Table row atom
│   │   └── job_status/
│   │       └── job_status_badge.html
│   ├── user/
│   │   ├── __init__.py
│   │   ├── user_card/
│   │   │   └── user_card.html
│   │   └── user_avatar/
│   │       └── user_avatar.html
│   ├── host/
│   │   ├── __init__.py
│   │   └── host_card/
│   │       └── host_card.html
│   └── database/
│       ├── __init__.py
│       └── database_card/
│           └── database_card.html
│
├── features/                     # Layer 2: User actions
│   ├── __init__.py
│   ├── auth/                     # Authentication feature
│   │   ├── __init__.py
│   │   ├── routes.py             # Login/logout routes (~100 lines)
│   │   ├── login/
│   │   │   ├── login_form.html
│   │   │   └── login_page.html
│   │   └── logout/
│   │       └── logout_handler.py
│   ├── restore/                  # Database restore feature
│   │   ├── __init__.py
│   │   ├── routes.py             # Restore routes (~150 lines)
│   │   ├── restore_form/
│   │   │   └── restore_form.html
│   │   ├── restore_preview/
│   │   │   └── restore_preview.html
│   │   └── restore_submit/
│   │       └── restore_handler.py
│   ├── search/                   # Database search feature
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── search_form/
│   │       └── search_form.html
│   ├── job_view/                 # View job details feature
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   ├── job_detail/
│   │   │   └── job_detail.html
│   │   └── job_events/
│   │       └── job_events.html
│   └── job_cancel/               # Cancel job feature
│       ├── __init__.py
│       └── routes.py
│
├── widgets/                      # Layer 3: Self-contained blocks
│   ├── __init__.py
│   ├── sidebar/
│   │   ├── __init__.py
│   │   ├── sidebar.html          # Coordinator template
│   │   ├── sidebar_nav/
│   │   │   └── sidebar_nav.html
│   │   └── sidebar_user/
│   │       └── sidebar_user.html
│   ├── header/
│   │   ├── __init__.py
│   │   └── header.html
│   ├── job_table/
│   │   ├── __init__.py
│   │   ├── job_table.html        # Coordinator
│   │   ├── job_table_header/
│   │   │   └── table_header.html
│   │   ├── job_table_body/
│   │   │   └── table_body.html
│   │   └── job_table_filters/
│   │       └── table_filters.html
│   ├── filter_bar/
│   │   ├── __init__.py
│   │   └── filter_bar.html       # Status filter buttons
│   ├── active_jobs/
│   │   ├── __init__.py
│   │   └── active_jobs.html      # Active jobs summary widget
│   └── stats_cards/
│       ├── __init__.py
│       └── stats_cards.html      # Dashboard stat cards
│
├── pages/                        # Layer 4: Complete compositions
│   ├── __init__.py
│   ├── dashboard/
│   │   ├── __init__.py
│   │   ├── routes.py             # Dashboard routes (~50 lines)
│   │   └── dashboard_page.html
│   ├── error/
│   │   ├── __init__.py
│   │   └── error_page.html
│   └── admin/                    # Admin page group
│       ├── __init__.py
│       ├── jobs/
│       │   ├── __init__.py
│       │   ├── routes.py         # Admin job routes (~100 lines)
│       │   └── admin_jobs_page.html
│       ├── users/
│       │   ├── __init__.py
│       │   ├── routes.py
│       │   ├── users_list_page.html
│       │   └── user_detail_page.html
│       ├── hosts/
│       │   ├── __init__.py
│       │   ├── routes.py
│       │   └── hosts_page.html
│       ├── settings/
│       │   ├── __init__.py
│       │   ├── routes.py
│       │   └── settings_page.html
│       └── cleanup/
│           ├── __init__.py
│           ├── routes.py
│           └── cleanup_page.html
│
└── static/                       # Static assets
    ├── css/
    │   ├── base.css              # CSS variables, reset
    │   ├── components.css        # Component styles
    │   └── pages.css             # Page-specific styles
    ├── js/
    │   ├── htmx.min.js
    │   └── app.js                # Shared JS utilities
    └── images/
        └── logo.svg
```

---

## Migration Plan

### Phase 1: Foundation (shared/, dependencies)
**Goal**: Create the foundation layer without breaking existing code

1. Create `shared/` directory structure
2. Extract base layouts from `base.html`
3. Create `dependencies.py` with FastAPI dependencies
4. Create `exceptions.py` with error handling
5. Create shared UI atoms (buttons, inputs, icons)

**Files to create**:
- `shared/layouts/base.html`
- `shared/layouts/app_layout.html`
- `shared/layouts/auth_layout.html`
- `shared/ui/buttons/button.html`
- `shared/ui/icons/icons.html`
- `shared/contracts/page_interface.py`
- `dependencies.py`
- `exceptions.py`

### Phase 2: Entities (domain display components)
**Goal**: Create reusable entity display atoms

1. Extract job display components from existing templates
2. Create user, host, database display atoms
3. Ensure atoms have no page knowledge

**Files to create**:
- `entities/job/job_row/job_row.html`
- `entities/job/job_card/job_card.html`
- `entities/job/job_status/job_status_badge.html`
- `entities/user/user_card/user_card.html`
- `entities/host/host_card/host_card.html`

### Phase 3: Widgets (self-contained blocks)
**Goal**: Create reusable widget compositions

1. Extract sidebar from base.html
2. Extract filter_bar (already exists as partial)
3. Create job_table widget with sub-components
4. Create stats_cards widget

**Files to create**:
- `widgets/sidebar/sidebar.html`
- `widgets/filter_bar/filter_bar.html`
- `widgets/job_table/job_table.html`
- `widgets/stats_cards/stats_cards.html`

### Phase 4: Features (split routes.py)
**Goal**: Break monolithic routes.py into feature modules

1. Extract auth routes (~100 lines)
2. Extract restore routes (~150 lines)
3. Extract search routes (~80 lines)
4. Extract job_view routes (~100 lines)
5. Create feature-specific templates

**routes.py breakdown**:
| Feature | Estimated Lines | Routes |
|---------|-----------------|--------|
| auth | ~100 | login, logout |
| restore | ~150 | restore page, submit, status |
| search | ~80 | search page, results |
| job_view | ~100 | job detail, job profile |
| dashboard | ~50 | dashboard page |
| admin/jobs | ~150 | job list, job actions |
| admin/users | ~150 | user list, user detail, CRUD |
| admin/hosts | ~100 | host list, CRUD |
| admin/settings | ~80 | settings page |
| admin/cleanup | ~80 | cleanup page |

### Phase 5: Pages (final composition)
**Goal**: Create page coordinators that compose widgets and features

1. Create dashboard page coordinator
2. Create admin pages coordinators
3. Wire up all routers in main router.py

**Files to create**:
- `pages/dashboard/dashboard_page.html`
- `pages/admin/jobs/admin_jobs_page.html`
- `pages/admin/users/users_list_page.html`
- etc.

### Phase 6: Cleanup & Validation
**Goal**: Remove old structure, validate HCA compliance

1. Remove old `templates/` directory
2. Update imports throughout codebase
3. Run HCA validation checks
4. Update tests

---

## Implementation Order

```
Week 1: Phase 1 (Foundation)
├── Day 1-2: shared/layouts/, dependencies.py, exceptions.py
├── Day 3-4: shared/ui/ atoms
└── Day 5: shared/contracts/, testing

Week 2: Phase 2-3 (Entities & Widgets)
├── Day 1-2: entities/job/, entities/user/
├── Day 3-4: widgets/sidebar/, widgets/filter_bar/
└── Day 5: widgets/job_table/, widgets/stats_cards/

Week 3: Phase 4 (Features - Route Split)
├── Day 1: features/auth/
├── Day 2: features/restore/
├── Day 3: features/search/, features/job_view/
├── Day 4: features/job_cancel/
└── Day 5: Testing all features

Week 4: Phase 5-6 (Pages & Cleanup)
├── Day 1-2: pages/dashboard/, pages/error/
├── Day 3-4: pages/admin/*
└── Day 5: Cleanup old structure, final validation
```

---

## HCA Validation Checklist

After restructuring, verify:

- [ ] No file exceeds 300 lines
- [ ] Each directory has a clear, specific name
- [ ] Dependencies only flow downward (shared → entities → features → widgets → pages)
- [ ] No upward imports (entities cannot import from features)
- [ ] Each feature has its own routes.py (<200 lines each)
- [ ] Templates follow containment (atoms in component directories)
- [ ] No generic names (utils, helpers, common, misc)
- [ ] Path reads as logical hierarchy

---

## Quick Reference: File Size Targets

| Component Type | Ideal | Maximum |
|----------------|-------|---------|
| Route file | 100 lines | 200 lines |
| Template (atom) | 50 lines | 150 lines |
| Template (coordinator) | 100 lines | 200 lines |
| Python module | 200 lines | 300 lines |

---

## Dependencies Diagram

```
                    ┌─────────────────┐
                    │     pages/      │  Layer 4
                    │  (compositions) │
                    └────────┬────────┘
                             │ uses
                    ┌────────▼────────┐
                    │    widgets/     │  Layer 3
                    │ (UI blocks)     │
                    └────────┬────────┘
                             │ uses
                    ┌────────▼────────┐
                    │   features/     │  Layer 2
                    │ (user actions)  │
                    └────────┬────────┘
                             │ uses
                    ┌────────▼────────┐
                    │   entities/     │  Layer 1
                    │ (domain atoms)  │
                    └────────┬────────┘
                             │ uses
                    ┌────────▼────────┐
                    │    shared/      │  Layer 0
                    │ (universal)     │
                    └─────────────────┘
```

---

## Next Steps

1. **Review this plan** - Confirm the structure makes sense
2. **Start Phase 1** - Create foundation (`shared/`, `dependencies.py`)
3. **Iterate** - Build up layer by layer, testing as we go

Ready to begin Phase 1 on your command.
