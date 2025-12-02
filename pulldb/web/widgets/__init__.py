# HCA Layer 3: Widgets
# ====================
# Purpose: Composite UI components that combine entities and shared atoms.
# 
# Structure:
#   widgets/
#   ├── stats_grid/    - Dashboard 4-card stats display
#   ├── stats_bar/     - Compact horizontal stats bar
#   ├── filter_bar/    - Job filtering controls
#   ├── job_table/     - Complete job list table
#   ├── sidebar/       - Navigation sidebar (in shared/layouts/partials)
#   └── header/        - Page header bar (in shared/layouts/partials)
#
# Contract:
#   - Widgets compose entities and shared UI atoms
#   - Each widget is self-contained with clear inputs
#   - Can include page-specific JavaScript
