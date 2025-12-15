# 03 — PR Breakdown

---

## Dependency Graph

```
PR 0: Tooling & Baseline
 │
 ▼
PR 1: Foundation (Icons + CSS + Accessibility)
 │
 ├──► PR 2: Auth Feature ──────────────────────┐
 ├──► PR 3: Dashboard Feature ─────────────────┤
 ├──► PR 4: Jobs Feature ──────────────────────┤
 ├──► PR 5: Restore + QA Template ─────────────┤  (PARALLEL)
 ├──► PR 6: Manager Feature ───────────────────┤
 └──► PR 10: Audit Feature ────────────────────┘
          │
          ▼
     PR 7: Admin Core
          │
          ├──► PR 8: Admin Settings + Theme
          └──► PR 9: Admin Maintenance
                    │
                    ▼
               PR 12: Dark Mode
                    │
                    ▼
               PR 11: Navigation Polish
                    │
                    ▼
               PR 13: STYLE-GUIDE Sync
```

**Critical Path**: PR 0 → PR 1 → PR 7 → PR 8 → PR 12 → PR 13

---

## Phase 0: Tooling

### PR 0: Audit Tooling + Icon Categorization
**Branch**: `gui/pr0-tooling-baseline`  
**Effort**: 2-4 hours  
**Dependencies**: None

**Tasks**:
1. Verify audit scripts work
2. Categorize 40 "unknown" icons manually
3. Add E2E tests to CI
4. Capture screenshot baseline

---

## Phase 1: Foundation

### PR 1: CSS + Icons + Accessibility
**Branch**: `gui/pr1-foundation-icons`  
**Effort**: 6-8 hours  
**Dependencies**: PR 0

**Creates**:
- `partials/icons/*.html` (5 files, 101 icons)
- `static/css/dark-mode.css`

**Modifies**:
- `design-system.css` — utility classes, accessibility
- `components.css` — `.stat-card`, `.alert-*`
- `base.html` — `data-theme`, skip link

---

## Phase 2: Features (Parallelizable)

### PR 2: Auth Feature
**Branch**: `gui/pr2-auth-feature`  
**Effort**: 1-2 hours  
**Dependencies**: PR 1

- Enhance `features/auth/login.html` (CSS Grid, no Bootstrap)
- DELETE `templates/login.html`

### PR 3: Dashboard Feature
**Branch**: `gui/pr3-dashboard-feature`  
**Effort**: 3-4 hours  
**Dependencies**: PR 1

- Extract ~590 lines CSS from dashboard templates
- Convert stat displays to `.stat-card` with icons

### PR 4: Jobs Feature
**Branch**: `gui/pr4-jobs-feature`  
**Effort**: 3-4 hours  
**Dependencies**: PR 1

- MOVE: `my_job.html`, `my_jobs.html`, `job_profile.html`, `job_history.html`
- Update routes to new paths

### PR 5: Restore + QA Template ⚠️ CRITICAL
**Branch**: `gui/pr5-restore-qatemplate`  
**Effort**: 5-6 hours  
**Dependencies**: PR 1

**⚠️ MUST PORT QA Template functionality:**
- Tab UI for Customer vs QA Template
- Hidden input `qatemplate=true/false`
- QA extension suffix input
- JavaScript tab switching logic

- Extract 416 lines inline CSS
- DELETE `templates/restore.html`

### PR 6: Manager Feature
**Branch**: `gui/pr6-manager-feature`  
**Effort**: 3-4 hours  
**Dependencies**: PR 1

- MOVE 5 templates from `manager/` to `features/manager/`
- DELETE `manager/` folder

### PR 10: Audit Feature
**Branch**: `gui/pr10-audit-feature`  
**Effort**: 1-2 hours  
**Dependencies**: PR 1

- MOVE 3 templates from `audit/` to `features/audit/`
- Add sidebar link (admin-only)

---

## Phase 3: Admin Suite (Sequential)

### PR 7: Admin Core
**Branch**: `gui/pr7-admin-core`  
**Effort**: 6-8 hours  
**Dependencies**: PR 1

- MOVE 6 templates to `features/admin/`
- Extract 1,109 lines CSS from `hosts.html`
- Replace ~50 inline SVGs

### PR 8: Admin Settings + Theme GUI
**Branch**: `gui/pr8-admin-settings`  
**Effort**: 4-6 hours  
**Dependencies**: PR 7

- Add `SettingCategory.APPEARANCE` to settings.py
- Create `/web/theme.css` endpoint
- Build Appearance settings UI with color sliders

### PR 9: Admin Maintenance
**Branch**: `gui/pr9-admin-maintenance`  
**Effort**: 2-3 hours  
**Dependencies**: PR 7

- MOVE remaining 4 templates
- DELETE `admin/` folder

---

## Phase 4: Polish

### PR 11: Navigation Polish
**Branch**: `gui/pr11-navigation-polish`  
**Effort**: 1-2 hours  
**Dependencies**: All feature PRs

- Update sidebar with icon macros
- Standardize `active_nav` detection
- Audit breadcrumbs

### PR 12: Dark Mode Integration
**Branch**: `gui/pr12-dark-mode`  
**Effort**: 3-4 hours  
**Dependencies**: PR 8

- Create theme toggle widget
- Create `theme.js` for localStorage + system preference
- Wire to admin settings

### PR 13: STYLE-GUIDE.md Sync
**Branch**: `gui/pr13-styleguide-sync`  
**Effort**: 1-2 hours  
**Dependencies**: All PRs

- Update docs/STYLE-GUIDE.md with new components
- Remove "Draft" status

---

## Phase 5: Cleanup (Added 2025-12-15)

Post-migration audit identified deferred/missed items requiring cleanup.

```
PR 13: STYLE-GUIDE Sync
 │
 ▼
PR 14: Accessibility & Icon Completion
 │
 ▼
PR 15: Audit Feature ─────────────────┐
 │                                     │
PR 16: JS Render CSS Classes ──────────┤ (PARALLEL)
 │                                     │
PR 17: Skeleton Loading States ────────┘
 │
 ▼
PR 18: Component Documentation Page
 │
 ▼
PR 19: Batch Style Block Extraction
 │
 ▼
PR 20: File Cleanup & Archive
```

### PR 14: Accessibility & Icon Completion
**Branch**: `gui/pr14-accessibility-icons`  
**Effort**: 4-5 hours  
**Dependencies**: PR 13

**Tasks**:
1. Add skip link to `base.html`
2. Add `aria-label` to icon-only buttons
3. Convert inline SVGs to `{{ icon() }}` macros

### PR 15: Audit Feature (Full Implementation)
**Branch**: `gui/pr15-audit-feature`  
**Effort**: 3-4 hours  
**Dependencies**: PR 14

**Creates**:
- `features/audit/index.html` — Paginated log browser
- `features/audit/by_user.html` — Filter by user
- `features/audit/by_resource.html` — Filter by target
- Routes in `routes/admin.py`
- Sidebar link (admin-only)

### PR 16: JS Render Function CSS Classes
**Branch**: `gui/pr16-render-css-classes`  
**Effort**: 3-4 hours  
**Dependencies**: PR 14

- Add `.cell-mono-sm`, `.cell-truncate`, `.cell-badge-*`, `.cell-actions`
- Refactor render functions in users.html and jobs.html

### PR 17: Skeleton Loading States
**Branch**: `gui/pr17-skeleton-loading`  
**Effort**: 3-4 hours  
**Dependencies**: PR 14

- Add skeleton CSS with shimmer animation
- Create `partials/skeleton.html` macro
- Apply to jobs table and dashboard stat cards

### PR 18: Component Documentation Page
**Branch**: `gui/pr18-styleguide-page`  
**Effort**: 4-6 hours  
**Dependencies**: PR 17

- Create `/admin/styleguide` route (admin-only)
- Live examples: Colors, Typography, Buttons, Cards, Forms, Tables, etc.

### PR 19: Batch Style Block Extraction
**Branch**: `gui/pr19-style-extraction`  
**Effort**: 8-10 hours  
**Dependencies**: PR 18

- Extract `<style>` blocks from 17 templates to components.css
- Priority: settings.html (~500), users.html (~160), hosts.html (~100)

### PR 20: File Cleanup & Archive
**Branch**: `gui/pr20-cleanup-archive`  
**Effort**: 1-2 hours  
**Dependencies**: PR 19

- Delete `archived/web2-legacy/`
- Move `.pulldb/gui-migration/` → `docs/archived/gui-migration/`
- Move `error.html` → `features/errors/error.html`
- Update README status to "Complete"
