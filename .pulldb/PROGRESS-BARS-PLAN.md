# Progress Bars Implementation Plan

> **Status**: IN PROGRESS  
> **Created**: 2026-01-02  
> **Target**: Job Details Page - Download & Restore Progress Visualization

## Overview

Add visual progress bars for download (blue, with speed/ETA) and restore phases (green, with per-table progress from processlist polling). Worker polls MySQL processlist during restore and logs rich progress events. Template renders progress bars using existing CSS patterns.

---

## Phase 1: CSS Foundation

### Atom 1.1: Add progress bar base styles
- [ ] **File**: `pulldb/web/static/css/pages/job-details.css`
- Add `.log-progress`, `.log-progress-bar-container`, `.log-progress-bar` base styles

### Atom 1.2: Add phase-specific progress bar colors
- [ ] **File**: `pulldb/web/static/css/pages/job-details.css`
- Add `.log-progress--download` (blue/info), `.log-progress--restore` (green/success)

### Atom 1.3: Add progress stats styling
- [ ] **File**: `pulldb/web/static/css/pages/job-details.css`
- Add `.log-progress-stats`, `.log-progress-stats-value`

### Atom 1.4: Add per-table mini progress bars styling
- [ ] **File**: `pulldb/web/static/css/pages/job-details.css`
- Add `.log-progress-tables`, `.log-progress-table-row`, etc.

---

## Phase 2: Download Progress Enhancement

### Atom 2.1: Add elapsed_seconds to download progress events
- [ ] **File**: `pulldb/worker/downloader.py`
- Add `start_time = time.monotonic()` at download start
- Include `elapsed_seconds` in progress logging

### Atom 2.2: Update executor download progress event
- [ ] **File**: `pulldb/worker/executor.py`
- Update `_progress_callback` to include elapsed time

### Atom 2.3: Add Jinja2 filter for filesize formatting
- [ ] **File**: `pulldb/web/features/jobs/routes.py`
- Add `_format_filesize()` filter

### Atom 2.4: Add Jinja2 filter for speed formatting
- [ ] **File**: `pulldb/web/features/jobs/routes.py`
- Add `_format_speed()` filter

### Atom 2.5: Add Jinja2 filter for ETA formatting
- [ ] **File**: `pulldb/web/features/jobs/routes.py`
- Add `_format_eta()` filter

### Atom 2.6: Calculate download stats in route handler
- [ ] **File**: `pulldb/web/features/jobs/routes.py`
- Add `_calculate_download_stats()` function

### Atom 2.7: Pass download stats to template
- [ ] **File**: `pulldb/web/features/jobs/routes.py`
- Add `download_stats` to template context

---

## Phase 3: Download Progress Template

### Atom 3.1: Add download_progress renderer to template
- [ ] **File**: `pulldb/web/templates/features/jobs/details.html`
- Add progress bar renderer for `download_progress` events

---

## Phase 4: Metadata Row Count Extraction

### Atom 4.1: Create INI metadata parser function
- [ ] **File**: `pulldb/worker/metadata_synthesis.py`
- Add `parse_metadata_row_counts()` function

### Atom 4.2: Create total row count aggregation function
- [ ] **File**: `pulldb/worker/metadata_synthesis.py`
- Add `get_total_row_count()` function handling both formats

---

## Phase 5: Restore Progress Polling Infrastructure

### Atom 5.1: Create progress polling data class
- [ ] **File**: `pulldb/worker/restore.py`
- Add `RestoreProgressSnapshot` dataclass

### Atom 5.2: Create processlist query function
- [ ] **File**: `pulldb/worker/restore.py`
- Add `_query_restore_progress()` function

### Atom 5.3: Create table count query function
- [ ] **File**: `pulldb/worker/restore.py`
- Add `_query_table_count()` function

### Atom 5.4: Create row count query for completed tables
- [ ] **File**: `pulldb/worker/restore.py`
- Add `_query_rows_restored()` function

### Atom 5.5: Create polling thread function
- [ ] **File**: `pulldb/worker/restore.py`
- Add `_restore_progress_poller()` thread function

### Atom 5.6: Integrate polling thread into myloader execution
- [ ] **File**: `pulldb/worker/executor.py`
- Wrap myloader execution with polling thread start/stop

---

## Phase 6: Restore Progress Template

### Atom 6.1: Calculate restore stats in route handler
- [ ] **File**: `pulldb/web/features/jobs/routes.py`
- Add `_calculate_restore_stats()` function

### Atom 6.2: Add format_number filter
- [ ] **File**: `pulldb/web/features/jobs/routes.py`
- Add `_format_number()` filter for K/M suffixes

### Atom 6.3: Pass restore stats to template
- [ ] **File**: `pulldb/web/features/jobs/routes.py`
- Add `restore_stats` to template context

### Atom 6.4: Add restore_table_progress renderer to template
- [ ] **File**: `pulldb/web/templates/features/jobs/details.html`
- Add progress bar renderer with per-table breakdown

---

## Phase 7: Fallback & Edge Cases

### Atom 7.1: Fallback when metadata unavailable
- [ ] **File**: `pulldb/worker/metadata_synthesis.py`
- Handle missing metadata gracefully

### Atom 7.2: Template fallback for table-count-based progress
- [ ] **File**: `pulldb/web/templates/features/jobs/details.html`
- Fall back to table count if row count unavailable

### Atom 7.3: Handle complete state styling
- [ ] **File**: `pulldb/web/static/css/pages/job-details.css`
- Add `.log-progress--complete` styling

---

## Files Modified

| File | Changes |
|------|---------|
| `pulldb/web/static/css/pages/job-details.css` | Progress bar CSS |
| `pulldb/worker/downloader.py` | Add elapsed_seconds |
| `pulldb/worker/executor.py` | Update callback, integrate polling thread |
| `pulldb/worker/restore.py` | Polling functions, thread management |
| `pulldb/worker/metadata_synthesis.py` | INI parsing, row count aggregation |
| `pulldb/web/features/jobs/routes.py` | Filters, stat calculation, context |
| `pulldb/web/templates/features/jobs/details.html` | Progress bar renderers |

---

## Implementation Order

1. CSS (Atoms 1.1-1.4)
2. Jinja2 filters (Atoms 2.3-2.5, 6.2)
3. Download progress backend (Atoms 2.1-2.2, 2.6-2.7)
4. Download progress template (Atom 3.1)
5. Metadata parsing (Atoms 4.1-4.2)
6. Restore polling infrastructure (Atoms 5.1-5.6)
7. Restore progress route/template (Atoms 6.1, 6.3-6.4)
8. Fallbacks (Atoms 7.1-7.3)
