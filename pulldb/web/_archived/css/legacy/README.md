# Archived Legacy CSS Files

**Date Archived:** 2025-12-16  
**Reason:** Replaced by HCA-compliant CSS architecture

## Files

| File | Lines | Replacement |
|------|-------|-------------|
| `components.css` | 6,083 | All 188 classes migrated to HCA files |
| `dark-mode.css` | 1,065 | Co-located `[data-theme="dark"]` in HCA files |
| `design-system.css` | 483 | `shared/css/design-tokens.css` |
| `layout.css` | ~150 | `shared/css/layout.css` |

## Migration Details

All classes from these files were migrated to the HCA CSS architecture:

- **shared/css/** - design-tokens, reset, utilities, layout
- **entities/css/** - badge, avatar, card
- **features/css/** - buttons, forms, tables, modals, alerts, status, dashboard, search
- **pages/css/** - profile, admin, job-details, restore, styleguide

## Restoration

If needed, these files can be restored by:
1. Moving them back to `pulldb/web/static/css/`
2. Adding imports to `shared/layouts/app_layout.html`

However, this should not be necessary as all styles have been migrated.
