# Archived Templates

**Last Updated:** 2025-12-23  
**Reason:** HCA refactoring cleanup - these templates were scaffolding that was never adopted in production feature templates.

## Archived Contents

### Widget Directories (`widgets/`)
- `header/` - Header logo widget (never used by features)
- `job_table/` - Legacy job table widget (replaced by lazy_table)
- `stats_bar/` - Stats bar widget (features use inline styles)
- `stats_grid/` - Stats grid widget (features use inline styles)
- `filter_bar.html` - Filter bar widget HTML
- `header_logo.html` - Header logo widget HTML
- `job_table.html` - Job table widget HTML
- `stats_bar.html` - Stats bar widget HTML
- `stats_grid.html` - Stats grid widget HTML
- `virtual_table.html` - Virtual table widget HTML

### Partial Templates (`partials/`)
- `filter_bar.html` - Filter bar partial (features use lazy_table filtering)
- `job_row.html` - Job row partial (never used)
- `skeleton.html` - Skeleton loader partial (never used)

### Template Widgets (`templates/widgets/lazy_table/`)
- `lazy_table.html` - HTML template wrapper (features use CSS/JS directly)

### Entity Templates (`templates/entities/`)
- `database/database_row.html` - Database row entity
- `host/host_row.html` - Host row entity  
- `job/job_card.html` - Job card entity
- `job/job_row.html` - Job row entity
- `user/user_row.html` - User row entity

### Shared Layout Templates (`templates/shared/layouts/`)
- `auth_layout.html` - Auth layout (replaced by base_auth.html)
- `error.html` - Error layout (replaced by feature error templates)

### Shared UI Templates (`shared/ui/`)
- `alerts/alert.html` - Alert component
- `badges/status_badge.html` - Status badge component
- `buttons/button.html` - Button component
- `buttons/icon_button.html` - Icon button component
- `empty/empty_state.html` - Empty state component
- `inputs/select_input.html` - Select input component
- `inputs/text_input.html` - Text input component
- `loading/spinner.html` - Loading spinner component

## Notes

These templates were part of the HCA (Hierarchical Containment Architecture) scaffolding but feature templates evolved to use:
1. **LazyTable widget** - For all data tables (jobs, users, cleanup, etc.)
2. **Inline Jinja macros** - For badges, buttons, and form elements
3. **CSS-only components** - Design tokens and utilities instead of HTML templates

The CSS and JavaScript files in widget directories are still in use - only HTML templates were archived.

## Restoration

If any of these templates are needed again, they can be restored from this archive directory.
