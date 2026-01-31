# Release Notes v1.0.8

**Release Date**: January 31, 2026  
**Type**: Feature Release with UI/UX Improvements

## Summary

This release introduces the VirtualLog widget for virtualized job event viewing, phase-weighted progress tracking for accurate completion percentages, and real-time HTMX-based UI updates. Includes myloader 0.20.1 upgrade and removes user_code prefix validation in favor of pullDB table-based ownership.

## 🎉 New Features

### VirtualLog Widget
- **Virtualized Event Viewing**: New scrollable event log with offset-based pagination for large job histories
- **Auto-Pause on Scroll**: Polling automatically pauses when user scrolls away from live edge to read history
- **Resume to Top**: Clicking Resume scrolls to top to show latest events
- **Scroll-Snap Fix**: Fixed cache bounds tracking in `_trimCache()` to prevent scroll-snap bugs
- **Live Polling**: Supports real-time updates for running jobs with HTMX integration

### HTMX Phase Stepper & Status Header
- **Real-Time Updates**: Phase stepper and status badge now poll `/web/jobs/{job_id}/header` every 2s
- **Extracted Partial**: New `job_header.html` partial for clean separation
- **Effective Status Handling**: Correctly handles stale DB status race conditions

### Phase-Weighted Progress Tracking
- **Accurate Percentages**: Tables contribute 85% during data loading, 100% only after indexing completes
- **Prevents Premature 100%**: New `DATA_PHASE_WEIGHT` (85%) and `INDEX_PHASE_WEIGHT` (15%) constants
- **Indexing Visibility**: Added `indexing_started` and `indexing_progress` events for UI visibility
- **Heartbeat Suppression**: Skip heartbeat when meaningful events emitted within 30s

### Schema Creation Events
- **Schema Phase Visibility**: Users now see activity during schema creation phase (first 5-10s of restore)
- **New Events**: `schema_creating` and `schema_created` events in Execution Log
- **Myloader Completion Signal**: Added `myloader_completed` property for authoritative completion detection

### Bytes-Based ETA Calculation
- **ExtractionStats Dataclass**: Track extraction metrics through workflow
- **Improved ETA**: Priority chain: rows → bytes → files (graceful fallback)
- **Strike-Based Completion**: Replaces time-based detection for reliability

### Myloader 0.21.1 Upgrade
- **Updated Binary**: Upgrade from 0.19.x to 0.21.1-1
- **Drop Table**: Replace `--overwrite-tables` with `--drop-table` (now supports modes: FAIL, NONE, DROP, TRUNCATE, DELETE)
- **OOM Prevention**: Add `--max-threads-for-index-creation=1` to prevent memory issues during index rebuilds
- **AWS Support**: New `--source-control-command=AWS` option for replication configuration

## 🐛 Bug Fixes

### Job Details Page
- **Real-Time Updates**: Extract phase stepper + status header into HTMX-polled partial
- **Completion State**: Reorder `_finalize_workflow` to call `mark_job_deployed()` before `restore_profile` event
- **Race Condition Fix**: Handle effective_status for stale DB status race condition
- **restore_profile Detection**: Check before is_active to ensure page reload triggers

### Restore Progress Tracking
- **Early Analyze Phase**: Add `early_analyze_enabled` mode to prevent premature 100%
- **Phase Completion Flags**: Add `index_complete`/`analyze_complete` flags for accurate tracking
- **Timeout Safety Net**: Add `finalize_analyze_phase()` for timeout handling

### Settings UI Fixes
- **Remove Invalid Option**: Remove `--connection-timeout` from myloader args (doesn't exist in 0.20.x)
- **Command Preview**: Fix 'View full command' modal stuck on Loading
- **Save DB to .env**: Fix 422 error by moving route before parameterized `/settings/{key}`
- **Filter Deprecated**: Hide `myloader_default_args` from Paths panel
- **Security**: Restrict `.env` write path to `/opt/pulldb.service/.env` only

## 🔧 Improvements

### UI Enhancements
- **Performance Profile Bar**: Stacked color bar with rounded pill ends
- **Compact Header**: Inline labels with values, reduced padding
- **Download Stats**: Synthesize from `backup_selected` when no progress events
- **Execution Log**: Improved legibility, cleaner `backup_selected` format

### Worker Performance
- **Faster Index Capture**: ProcesslistMonitor poll interval reduced from 2.0s to 0.5s
- **Page Reload Delay**: Increased from 500ms to 1500ms for better UX

### Code Quality
- **Dead Code Removal**: ~80 lines of confirmed dead code removed (unused imports, dead functions)
- **Test Coverage**: All tests passing with updated assertions

### Simulation Mode
- **Production-Identical Events**: Simulation now emits same event types as production worker
- **Full Event Sequence**: running → backup_selected → download_started → etc.

## ⚠️ Breaking Changes

### User Code Prefix Validation Removed
- **Change**: `user_code-in-name` validation removed from delete operations
- **New Model**: pullDB metadata table is now the single source of truth for ownership
- **Authorization**: Handled upstream by `can_delete_job_database()`
- **Defense-in-Depth**: Protection remains via `_drop_target_database_unsafe()` pullDB table check

## 📦 Package Information

| Component | Value |
|-----------|-------|
| Version | 1.0.8 |
| Package | `pulldb-1.0.8-py3-none-any.whl` |
| Debian | `pulldb_1.0.8_amd64.deb` |
| Client | `pulldb-client_1.0.8_amd64.deb` |
| myloader | 0.21.1-1 |
| Python | ≥3.12 |

## 🔄 Upgrade Path

Standard upgrade from v1.0.7:
```bash
# Debian package
wget https://github.com/CharlesHandshy/pullDB/releases/download/v1.0.8/pulldb_1.0.8_amd64.deb
sudo dpkg -i pulldb_1.0.8_amd64.deb

# Or pip
pip install --upgrade pulldb
```

**Note**: The myloader binary has been upgraded to 0.21.1. If you maintain custom myloader configurations, review the option changes:
- `--overwrite-tables` → `--drop-table` (now with modes: FAIL, NONE, DROP, TRUNCATE, DELETE)
- `--connection-timeout` has been removed (never existed in myloader)
- Default without `--drop-table` parameter is now FAIL (was implicit DROP in 0.20.x)

## 📋 Key Files Changed

### New Widget & Partial
- `pulldb/web/static/widgets/virtual_log/` - VirtualLog widget
- `pulldb/web/templates/partials/job_header.html` - HTMX-polled partial

### Progress Tracking
- `pulldb/worker/restore_progress.py` - Phase weighting, bytes-based ETA
- `pulldb/worker/heartbeat.py` - Heartbeat suppression

### Worker
- `pulldb/worker/executor.py` - Reordered finalization (mark_job_deployed before restore_profile)
- `pulldb/worker/restore.py` - Faster processlist polling (0.5s)

### Simulation
- `pulldb/simulation/core/seeding.py` - Production-identical event types
