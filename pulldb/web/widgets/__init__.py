# HCA Layer 3: Widgets
# ====================
# Purpose: Composite UI components that combine entities and shared atoms.
#
# Structure:
#   widgets/
#   ├── breadcrumbs/           - Breadcrumb navigation trail
#   ├── searchable_dropdown/   - Type-ahead search/select component
#   ├── stats_grid/            - Dashboard 4-card stats display
#   ├── stats_bar/             - Compact horizontal stats bar
#   ├── filter_bar/            - Job filtering controls
#   ├── job_table/             - Complete job list table
#   ├── sidebar/               - Navigation sidebar (in shared/layouts/partials)
#   └── header/                - Page header bar (in shared/layouts/partials)
#
# Contract:
#   - Widgets compose entities and shared UI atoms
#   - Each widget is self-contained with clear inputs
#   - Can include page-specific JavaScript
#
# Searchable Dropdown Usage:
#   The searchable_dropdown widget provides a standard type-ahead search/select
#   pattern used throughout the site:
#     1. User types 3-5 characters in search box
#     2. System fetches and displays matching options
#     3. User selects an option, populating the input
#
#   See: templates/partials/searchable_dropdown.html for Jinja macros
#   See: widgets/searchable_dropdown/__init__.py for Python config
