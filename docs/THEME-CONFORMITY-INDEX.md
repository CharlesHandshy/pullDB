# Theme Conformity Index

> **Purpose**: Track theme variable usage across all CSS/HTML files for site-wide theming consistency.
> **Last Updated**: 2026-01-04
> **Status**: Active tracking document

## Overview

pullDB uses a **semantic CSS variable system** with 68+ theme tokens generated from `ColorSchema` objects. This index tracks compliance across all files to ensure consistent theming in both Light and Dark modes.

### Compliance Legend

| Status | Meaning |
|--------|---------|
| ✅ | Fully compliant - uses only semantic `--color-*` variables |
| ⚠️ | Partial - uses `[data-theme]` overrides (should migrate to variables) |
| ❌ | Non-compliant - has hardcoded hex colors |
| 🔧 | Acceptable - design tokens or fallback values |
| 📦 | Archived - not in active use |

---

## CSS Files Inventory

### Shared Layer (pulldb/web/shared/css/)

| File | Status | Notes |
|------|--------|-------|
| [design-tokens.css](../pulldb/web/shared/css/design-tokens.css) | 🔧 | Raw palette definitions - hardcoded by design |
| [manifest.css](../pulldb/web/shared/css/manifest.css) | ✅ | Import manifest only |
| [reset.css](../pulldb/web/shared/css/reset.css) | ✅ | Uses semantic variables |
| [utilities.css](../pulldb/web/shared/css/utilities.css) | ✅ | Utility classes with variables |
| [fonts.css](../pulldb/web/shared/css/fonts.css) | ✅ | Font definitions |
| [layout.css](../pulldb/web/shared/css/layout.css) | ⚠️ | Has `[data-theme="dark"]` overrides (L475-555) |

### Static CSS - Pages Layer (pulldb/web/static/css/pages/)

| File | Status | Issues | Lines |
|------|--------|--------|-------|
| [profile.css](../pulldb/web/static/css/pages/profile.css) | ❌ | Hardcoded gradient `#0f172a`, `#1e293b`, `#334155`, `#4ade80` | L772, L906 |
| [admin.css](../pulldb/web/static/css/pages/admin.css) | ✅ | Uses semantic variables | - |
| [admin-hosts.css](../pulldb/web/static/css/pages/admin-hosts.css) | ✅ | Uses semantic variables | - |
| [job-details.css](../pulldb/web/static/css/pages/job-details.css) | ✅ | Uses semantic variables | - |
| [restore.css](../pulldb/web/static/css/pages/restore.css) | ✅ | Uses semantic variables | - |
| [styleguide.css](../pulldb/web/static/css/pages/styleguide.css) | ✅ | Uses semantic variables | - |

### Static CSS - Features Layer (pulldb/web/static/css/features/)

| File | Status | Notes |
|------|--------|-------|
| buttons.css | ✅ | Uses semantic variables |
| forms.css | ✅ | Uses semantic variables |
| alerts.css | ✅ | Uses semantic variables |
| badges.css | ✅ | Uses semantic variables |
| cards.css | ✅ | Uses semantic variables |
| modals.css | ✅ | Uses semantic variables |
| tables.css | ✅ | Uses semantic variables |
| progress.css | ⚠️ | Check for hardcoded progress colors |

### Widgets Layer (pulldb/web/widgets/css/)

| File | Status | Issues | Lines |
|------|--------|--------|-------|
| [stats-bar.css](../pulldb/web/widgets/css/stats-bar.css) | ⚠️ | Has `[data-theme="dark"]` overrides | L111, L156 |
| [sidebar.css](../pulldb/web/widgets/css/sidebar.css) | ✅ | Uses semantic variables | - |

### Pages Layer CSS (pulldb/web/pages/css/)

| File | Status | Notes |
|------|--------|-------|
| admin.css | ✅ | Uses semantic variables |
| admin-hosts.css | ✅ | Uses semantic variables |
| job-details.css | ✅ | Uses semantic variables |
| restore.css | ✅ | Uses semantic variables |
| profile.css | ✅ | Uses semantic variables |
| styleguide.css | ✅ | Uses semantic variables |

### Archived (pulldb/web/_archived/)

| File | Status | Notes |
|------|--------|-------|
| css/legacy/*.css | 📦 | Archived - not in active use |
| css/orphaned/*.css | 📦 | Archived - not in active use |

---

## HTML Templates Inventory

### Base Templates

| File | Status | Notes |
|------|--------|-------|
| [base.html](../pulldb/web/templates/base.html) | ✅ | Theme detection script, uses variables |
| [base_auth.html](../pulldb/web/templates/base_auth.html) | ✅ | Auth page base, uses variables |

### Feature Templates

| File | Status | Issues | Lines |
|------|--------|--------|-------|
| features/admin/partials/_appearance.html | ❌ | Hardcoded toast colors, fallback hex values | L308-310, L347-361 |
| features/admin/settings.html | ✅ | Uses semantic variables | - |
| features/admin/*.html | ✅ | All compliant | - |
| features/auth/login.html | ✅ | Uses semantic variables | - |
| features/auth/profile.html | ✅ | Uses semantic variables | - |
| features/dashboard/*.html | ✅ | Uses semantic variables | - |
| features/jobs/*.html | ✅ | Uses semantic variables | - |
| features/restore/*.html | ✅ | Uses semantic variables | - |

### Widget Templates

| File | Status | Notes |
|------|--------|-------|
| widgets/stats_bar.html | ✅ | Uses semantic variables |

### Partial Templates

| File | Status | Notes |
|------|--------|-------|
| partials/breadcrumbs.html | ✅ | Uses semantic variables |
| partials/searchable_dropdown.html | ✅ | Uses semantic variables |
| partials/icons/*.html | ✅ | SVG icons, no colors |

---

## Generated Theme Files

| File | Purpose | Generated By |
|------|---------|--------------|
| static/css/generated/manifest-light.css | Light mode variables | theme_generator.py |
| static/css/generated/manifest-dark.css | Dark mode variables | theme_generator.py |
| static/css/generated/version.txt | Cache-busting version | theme_generator.py |

---

## Remediation Queue

### Priority 1: Hardcoded Colors (Must Fix)

| File | Issue | Fix |
|------|-------|-----|
| [profile.css#L772](../pulldb/web/static/css/pages/profile.css#L772) | `#0f172a`, `#1e293b`, `#334155` gradient | Replace with `var(--gray-900)`, `var(--gray-800)`, `var(--gray-700)` |
| [profile.css#L906](../pulldb/web/static/css/pages/profile.css#L906) | `#4ade80` green color | Replace with `var(--color-success)` |
| [_appearance.html#L308-310](../pulldb/web/templates/features/admin/partials/_appearance.html#L308) | Toast hardcoded colors | Replace with `var(--color-success)`, `var(--color-error)`, `var(--color-info)` |

### Priority 2: Data-Theme Overrides (Should Migrate)

| File | Lines | Current Pattern | Migration Path |
|------|-------|-----------------|----------------|
| [layout.css](../pulldb/web/shared/css/layout.css) | L475-555 | `[data-theme="dark"] .selector { }` | Move colors to ColorSchema, use `--color-*` variables |
| [stats-bar.css](../pulldb/web/widgets/css/stats-bar.css) | L111, L156 | `[data-theme="dark"] .stats-bar--compact { }` | Use semantic variables |

### Priority 3: Fallback Values (Acceptable but Track)

Files using `var(--color-*, #fallback)` pattern are acceptable but tracked for monitoring:
- _appearance.html: L279-280 (demo gallery backgrounds)
- _appearance.html: L347-361 (JS fallbacks)

---

## ColorSchema Variable Coverage

### Currently Exposed in Admin UI (via _appearance.html)

| Category | Tokens | Exposed | Missing from UI |
|----------|--------|---------|-----------------|
| Surface | 6 | 3 | subtle, primary, secondary |
| Background | 7 | 3 | tertiary, hover, subtle, muted |
| Text | 5 | 3 | inverse, base |
| Border | 6 | 3 | light, primary, secondary |
| Status | 12 | 4 | *_bg, *_border variants |
| Interactive | 7 | 3 | primary_active, accent, accent_hover |
| Input | 5 | 0 | ALL (bg, border, focus, focus_ring, placeholder) |
| Link | 3 | 0 | ALL (default, hover, visited) |
| Code | 3 | 0 | ALL (bg, text, border) |
| Table | 3 | 0 | ALL (header_bg, row_hover, row_stripe) |
| Scrollbar | 3 | 0 | ALL (track, thumb, thumb_hover) |
| Shadows | 4 | 0 | ALL (sm, md, lg, xl) |

**Total**: 68 tokens, 19 exposed, 49 missing from UI

---

## Audit Scripts

### Check for hardcoded colors
```bash
grep -rn "#[0-9a-fA-F]\{6\}" pulldb/web --include="*.css" --include="*.html" | grep -v "_archived" | grep -v "design-tokens"
```

### Check for data-theme overrides
```bash
grep -rn "\[data-theme" pulldb/web --include="*.css" | grep -v "_archived" | grep -v "generated"
```

### Check for inline styles with colors
```bash
grep -rn 'style="[^"]*color' pulldb/web/templates --include="*.html"
```

---

## Pre-commit Integration

See: [scripts/audit_theme_conformity.py](../scripts/audit_theme_conformity.py)

The audit script enforces:
1. No hardcoded hex colors in CSS (except design-tokens.css)
2. No hardcoded hex colors in HTML templates
3. No new `[data-theme]` selectors outside generated files
4. Inline styles must use `var()` for colors

---

## Changelog

### 2025-12-30
- Initial index created
- Identified 3 files with hardcoded colors requiring remediation
- Identified 2 files with `[data-theme]` overrides to migrate
- Documented 49 missing theme tokens from admin UI
