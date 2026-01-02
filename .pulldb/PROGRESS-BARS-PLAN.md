# Progress Bars Implementation Plan

> **Status**: ✅ COMPLETED  
> **Created**: 2026-01-02  
> **Completed**: 2026-01-02  
> **Target**: Job Details Page - Download & Restore Progress Visualization

## Overview

Add visual progress bars for download (blue, with speed/ETA) and restore phases (green, with per-table progress from processlist polling). Worker polls MySQL processlist during restore and logs rich progress events. Template renders progress bars using existing CSS patterns.

---

## Phase 1: CSS Foundation ✅

### Atom 1.1: Add progress bar base styles
- [x] **File**: `pulldb/web/static/css/pages/job-details.css`
- Add `.log-progress`, `.log-progress-bar-container`, `.log-progress-bar` base styles

### Atom 1.2: Add phase-specific progress bar colors
- [x] **File**: `pulldb/web/static/css/pages/job-details.css`
- Add `.log-progress--download` (blue/info), `.log-progress--restore` (green/success)

### Atom 1.3: Add progress stats styling
- [x] **File**: `pulldb/web/static/css/pages/job-details.css`
- Add `.log-progress-stats`, `.log-progress-stats-value`

### Atom 1.4: Add per-table mini progress bars styling
- [x] **File**: `pulldb/web/static/css/pages/job-details.css`
- Add `.log-progress-tables`, `.log-progress-table-row`, etc.

---

## Phase 2: Download Progress Enhancement ✅

### Atom 2.1: Add elapsed_seconds to download progress events
- [x] **File**: `pulldb/worker/downloader.py`
- Add `start_time = time.monotonic()` at download start
- Include `elapsed_seconds` in progress logging

### Atom 2.2: Update executor download progress event
- [x] **File**: `pulldb/worker/executor.py`
- Update `_progress_callback` to include elapsed time

### Atom 2.3: Add Jinja2 filter for filesize formatting
- [x] **File**: `pulldb/web/dependencies.py`
- Add `_format_filesize()` filter

### Atom 2.4: Add Jinja2 filter for speed formatting
- [x] **File**: `pulldb/web/dependencies.py`
- Add `_format_speed()` filter

### Atom 2.5: Add Jinja2 filter for ETA formatting
- [x] **File**: `pulldb/web/dependencies.py`
- Add `_format_eta()` filter

### Atom 2.6: Calculate download stats in route handler
- [x] **File**: `pulldb/web/features/jobs/routes.py`
- Add `_calculate_download_stats()` function

### Atom 2.7: Pass download stats to template
- [x] **File**: `pulldb/web/features/jobs/routes.py`
- Add `download_stats` to template context

---

## Phase 3: Download Progress Template ✅

### Atom 3.1: Add download_progress renderer to template
- [x] **File**: `pulldb/web/templates/features/jobs/details.html`
- Add progress bar renderer for `download_progress` events

---

## Phase 4: Metadata Row Count Extraction ✅

### Atom 4.1: Create dump metadata parser module
- [x] **File**: `pulldb/worker/dump_metadata.py` (NEW)
- Add `parse_dump_metadata()` function with INI and file scanning

### Atom 4.2: Create total row count aggregation function
- [x] **File**: `pulldb/worker/dump_metadata.py` (NEW)
- `DumpMetadata` dataclass with `total_rows` aggregation

---

## Phase 5: Restore Progress Polling Infrastructure ✅

### Atom 5.1: Create processlist monitor module
- [x] **File**: `pulldb/worker/processlist_monitor.py` (NEW)
- Add `ProcesslistMonitor` class with background polling thread

### Atom 5.2: Create processlist query function
- [x] **File**: `pulldb/worker/processlist_monitor.py`
- Add `poll_once()` and `_execute_poll()` methods

### Atom 5.3: Create snapshot data classes
- [x] **File**: `pulldb/worker/processlist_monitor.py`
- Add `TableProgress`, `ProcesslistSnapshot` dataclasses

### Atom 5.4: Add completion percentage extraction
- [x] **File**: `pulldb/worker/processlist_monitor.py`
- Parse `/* Completed: XX% */` from myloader queries

### Atom 5.5: Create monitor start/stop lifecycle
- [x] **File**: `pulldb/worker/processlist_monitor.py`
- Add `start()`, `stop()`, `get_snapshot()` methods

### Atom 5.6: Create utility polling function
- [x] **File**: `pulldb/worker/processlist_monitor.py`
- Add `poll_processlist_once()` convenience function

---

## Phase 6: Restore Progress Template ✅

### Atom 6.1: Calculate restore stats in route handler
- [x] **File**: `pulldb/web/features/jobs/routes.py`
- Add `_calculate_restore_stats()` function

### Atom 6.2: Add format_number filter
- [x] **File**: `pulldb/web/dependencies.py`
- Add `_format_number()` filter for K/M suffixes

### Atom 6.3: Pass restore stats to template
- [x] **File**: `pulldb/web/features/jobs/routes.py`
- Add `restore_stats` to template context

### Atom 6.4: Add restore progress renderer to template
- [x] **File**: `pulldb/web/templates/features/jobs/details.html`
- Add progress bar renderer for restore phase

---

## Phase 7: Fallback & Edge Cases ✅

### Atom 7.1: Fallback when metadata unavailable
- [x] **File**: `pulldb/worker/dump_metadata.py`
- Falls back to file scanning when INI unavailable

### Atom 7.2: Template handles missing stats gracefully
- [x] **File**: `pulldb/web/templates/features/jobs/details.html`
- Conditional rendering only when stats available

### Atom 7.3: Handle complete state styling
- [x] **File**: `pulldb/web/static/css/pages/job-details.css`
- Add `.log-progress--complete` styling

---

## Files Modified

| File | Changes |
|------|---------|
| `pulldb/web/static/css/pages/job-details.css` | Progress bar CSS (~95 lines) |
| `pulldb/worker/downloader.py` | Add elapsed_seconds, start_time tracking |
| `pulldb/worker/executor.py` | Update callback signature (4 params) |
| `pulldb/worker/dump_metadata.py` | **NEW** - INI parsing, row count extraction |
| `pulldb/worker/processlist_monitor.py` | **NEW** - Background polling thread |
| `pulldb/web/dependencies.py` | 4 new Jinja2 filters |
| `pulldb/web/features/jobs/routes.py` | `_calculate_download_stats()`, `_calculate_restore_stats()` |
| `pulldb/web/templates/features/jobs/details.html` | Progress bar renderers |

---

## Implementation Notes

1. **CSS (Phase 1)**: Added before BUTTON VARIANTS section, follows existing color system
2. **Jinja2 filters (Phase 2)**: Added to `dependencies.py` alongside existing filters
3. **Download progress**: Uses `time.monotonic()` for accurate elapsed time
4. **Dump metadata**: Separate module handles both INI (0.19+) and file scanning (0.9)
5. **Processlist monitor**: Background thread with configurable poll interval
6. **Restore stats**: Extracts from existing `restore_progress` events

## Future Enhancements

- [ ] Integrate `ProcesslistMonitor` into `run_myloader()` for live per-table progress
- [ ] Add row-based progress when dump metadata available
- [ ] WebSocket push for real-time progress updates
