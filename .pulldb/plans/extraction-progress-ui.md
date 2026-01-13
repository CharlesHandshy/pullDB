# Extraction Progress & UI Bar Implementation Plan

**Branch**: `feature/extraction-progress-ui`  
**Created**: 2026-01-13  
**Status**: Planning Complete - Ready for Implementation  
**Last Updated**: 2026-01-13 (post-timeout-fix audit)

## Prerequisites & Related Work

### Related Bug Fixes (Completed 2026-01-13)

Before implementing extraction progress, critical timeout bugs were fixed that
could cause jobs to hang indefinitely after download+extraction completed:

| Module | Fix | Issue |
|--------|-----|-------|
| [staging.py](../../pulldb/worker/staging.py) | Added `connect_timeout_seconds=30` | Was using `timeout_seconds=7200s` for connection |
| [metadata.py](../../pulldb/worker/metadata.py) | Added `connect_timeout_seconds=30` | Same issue |
| [atomic_rename.py](../../pulldb/worker/atomic_rename.py) | Added `connect_timeout_seconds=30` | Same issue |
| [executor.py](../../pulldb/worker/executor.py) | Fixed PostSQLConnectionSpec | Was passing 600s as connect_timeout |
| [config.py](../../pulldb/domain/config.py) | Added `--connection-timeout=30` to myloader | myloader default was 0 (wait forever) |

**Impact on this feature**: After extraction completes, the workflow immediately
calls `cleanup_orphaned_staging()` which connects to MySQL. With the fix, if MySQL
is unreachable, the job fails fast (30s) instead of hanging for hours.

### HCA Layers Modified

This feature spans multiple HCA layers:
- **features/** (business logic): `pulldb/worker/executor.py`
- **features/** (web routes): `pulldb/web/features/jobs/routes.py`
- **templates/** (presentation): `pulldb/web/templates/features/jobs/details.html`
- **static/** (styling): `pulldb/web/static/css/main.css`

## Decisions

1. **Method**: Python `tar.extract(member)` loop (not subprocess)
2. **Progress Threshold**: Hybrid - 64MB OR 1000 files (whichever comes first)
3. **Abort Support**: Yes, with `abort_check` callback
4. **Time-based Fallback**: Yes, emit every 30s for large single-file archives
5. **Error Handling**: Add `extraction_failed` event to EVENT_TO_PHASE mapping

## Overview

Add real-time extraction progress tracking with UI progress bar. Currently extraction uses `tarfile.extractall()` which is silent. This feature will:
- Extract member-by-member with progress callbacks
- Emit `extraction_started`, `extraction_progress`, `extraction_complete`, and `extraction_failed` events
- Display orange progress bar in web UI between download and restore bars
- Time-based fallback ensures UI never appears frozen during long extractions

---

## Step 1: Update executor.py - Extraction Functions

**File**: [pulldb/worker/executor.py](../../pulldb/worker/executor.py)

### 1a. Add import (line 20)

```python
import time
```

### 1b. Add constants and type alias (after line 128, before extract_tar_archive)

```python
# Extraction progress emission thresholds (hybrid: bytes OR files OR time)
EXTRACTION_PROGRESS_BYTES = 64 * 1024 * 1024  # Every 64MB
EXTRACTION_PROGRESS_FILES = 1000  # Every 1000 files
EXTRACTION_PROGRESS_TIME = 30.0  # Every 30 seconds (fallback for large single files)


# Type alias for extraction progress callback
# (extracted_bytes, total_bytes, percent, elapsed_seconds, files_extracted, total_files)
ExtractionProgressCallback = t.Callable[[int, int, float, float, int, int], None]
```

### 1c. Replace extract_tar_archive function (lines 130-143)

```python
def extract_tar_archive(
    archive_path: str,
    dest_dir: Path,
    job_id: str,
    progress_callback: ExtractionProgressCallback | None = None,
    abort_check: t.Callable[[], bool] | None = None,
) -> str:
    """Extract tar archive into *dest_dir* with progress reporting.

    Extracts member-by-member to support progress callbacks and abort checks.
    Emits progress every 64MB extracted OR every 1000 files (hybrid approach).

    Args:
        archive_path: Path to tar archive.
        dest_dir: Destination directory for extraction.
        job_id: Job identifier for error context.
        progress_callback: Optional callback for progress updates.
            Signature: (extracted_bytes, total_bytes, percent, elapsed_seconds, files_extracted, total_files)
        abort_check: Optional callback that returns True to abort extraction.

    Returns:
        Path to destination directory.

    Raises:
        ExtractionError: When tar extraction fails or path escape attempted.
        CancellationError: If abort_check returns True during extraction.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:*") as tar:
            _safe_extract_with_progress(
                tar, dest_dir, progress_callback, abort_check, job_id
            )
    except CancellationError:
        raise  # Re-raise cancellation without wrapping
    except (tarfile.TarError, OSError, ValueError) as exc:
        raise ExtractionError(job_id, archive_path, str(exc)) from exc
    return str(dest_dir)
```

### 1d. Replace _safe_extract function (lines 145-153)

```python
def _safe_extract_with_progress(
    tar: tarfile.TarFile,
    dest: Path,
    progress_callback: ExtractionProgressCallback | None,
    abort_check: t.Callable[[], bool] | None,
    job_id: str,
) -> None:
    """Extract tar members with progress tracking and abort support.

    Validates each member path before extraction to prevent directory escape.
    Emits progress using hybrid threshold: 64MB or 1000 files or 30 seconds.
    """
    base = dest.resolve()
    members = tar.getmembers()
    total_files = len(members)
    total_bytes = sum(m.size for m in members if m.isfile())

    extracted_bytes = 0
    files_extracted = 0
    last_progress_bytes = 0
    last_progress_files = 0
    last_progress_time = time.monotonic()
    start_time = last_progress_time

    for member in members:
        # Abort check before each file
        if abort_check and abort_check():
            raise CancellationError(job_id, "extraction")

        # Validate path safety
        member_path = (base / member.name).resolve()
        if not str(member_path).startswith(str(base)):
            raise ValueError(
                f"Archive entry '{member.name}' escapes extraction directory"
            )

        # Extract single member
        tar.extract(member, path=base)
        files_extracted += 1
        if member.isfile():
            extracted_bytes += member.size

        # Emit progress using hybrid threshold (bytes OR files OR time)
        current_time = time.monotonic()
        bytes_since_last = extracted_bytes - last_progress_bytes
        files_since_last = files_extracted - last_progress_files
        time_since_last = current_time - last_progress_time

        should_emit = (
            bytes_since_last >= EXTRACTION_PROGRESS_BYTES
            or files_since_last >= EXTRACTION_PROGRESS_FILES
            or time_since_last >= EXTRACTION_PROGRESS_TIME
            or files_extracted == total_files  # Always emit on completion
        )

        if progress_callback and should_emit:
            elapsed = current_time - start_time
            percent = (extracted_bytes / total_bytes * 100) if total_bytes > 0 else 100.0
            progress_callback(
                extracted_bytes, total_bytes, percent, elapsed,
                files_extracted, total_files
            )
            last_progress_bytes = extracted_bytes
            last_progress_files = files_extracted
            last_progress_time = current_time
```

### 1e. Update _default_extract_archive function (lines 155-158)

```python
def _default_extract_archive(
    archive_path: str,
    dest_dir: Path,
    job_id: str,
    progress_callback: ExtractionProgressCallback | None = None,
    abort_check: t.Callable[[], bool] | None = None,
) -> str:
    """Forward to extract_tar_archive as overridable hook."""
    return extract_tar_archive(
        archive_path, dest_dir, job_id, progress_callback, abort_check
    )
```

---

## Step 2: Update executor.py - Hook Type Signature

**File**: `pulldb/worker/executor.py` (around line 207)

Update `WorkerExecutorHooks.extract_archive` type:

```python
extract_archive: t.Callable[
    [str, Path, str, ExtractionProgressCallback | None, t.Callable[[], bool] | None],
    str,
] = _default_extract_archive
```

---

## Step 3: Update executor.py - Extraction Phase Wiring

**File**: `pulldb/worker/executor.py` (lines 374-388)

Replace the extraction phase block:

```python
# Progress callback for extraction phase
def _extraction_progress_callback(
    extracted: int,
    total: int,
    percent: float,
    elapsed: float,
    files_extracted: int,
    total_files: int,
) -> None:
    self._append_event(
        job.id,
        "extraction_progress",
        {
            "extracted_bytes": extracted,
            "total_bytes": total,
            "percent_complete": round(percent, 1),
            "elapsed_seconds": round(elapsed, 1),
            "files_extracted": files_extracted,
            "total_files": total_files,
        },
    )

self._append_event(
    job.id,
    "extraction_started",
    {"archive_path": archive_path, "archive_size": backup_spec.size_bytes},
)

# Phase: Extraction
with profiler.phase(RestorePhase.EXTRACTION) as extraction_profile:
    extracted_dir = self._extract_archive(
        archive_path,
        extract_dir,
        job.id,
        _extraction_progress_callback,
        _cancel_check,
    )
    extraction_profile.metadata["extracted_dir"] = extracted_dir
    extraction_profile.metadata["bytes_processed"] = backup_spec.size_bytes

self._append_event(
    job.id,
    "extraction_complete",
    {"path": extracted_dir},
)
```

---

## Step 4: Update routes.py - Event Mapping

**File**: [pulldb/web/features/jobs/routes.py](../../pulldb/web/features/jobs/routes.py) (around line 257)

Add to `EVENT_TO_PHASE` dict:

```python
"extraction_started": "extraction",
"extraction_progress": "extraction",
"extraction_failed": "extraction",
```

Note: `extraction_complete` is already mapped in the existing code.

---

## Step 5: Update routes.py - Stats Calculation Function

**File**: [pulldb/web/features/jobs/routes.py](../../pulldb/web/features/jobs/routes.py) (after `_calculate_download_stats` at line ~349)

Add new function:

```python
def _calculate_extraction_stats(logs: list[Any]) -> dict[str, Any] | None:
    """Extract latest extraction progress stats from job events."""
    extracted_bytes = 0
    total_bytes = 0
    percent_complete = 0.0
    elapsed_seconds = 0.0
    files_extracted = 0
    total_files = 0
    is_complete = False
    started = False

    for event in logs:
        event_type = event.event_type if hasattr(event, "event_type") else event.get("event_type")
        detail = event.detail if hasattr(event, "detail") else event.get("detail")

        if event_type == "extraction_started":
            started = True
            if detail:
                try:
                    data = json.loads(detail) if isinstance(detail, str) else detail
                    total_bytes = data.get("archive_size", 0)
                except (json.JSONDecodeError, TypeError):
                    pass

        elif event_type == "extraction_progress" and detail:
            started = True
            try:
                data = json.loads(detail) if isinstance(detail, str) else detail
                extracted_bytes = data.get("extracted_bytes", 0)
                total_bytes = data.get("total_bytes", total_bytes)
                percent_complete = data.get("percent_complete", 0.0)
                elapsed_seconds = data.get("elapsed_seconds", 0.0)
                files_extracted = data.get("files_extracted", 0)
                total_files = data.get("total_files", 0)
            except (json.JSONDecodeError, TypeError):
                pass

        elif event_type == "extraction_complete":
            is_complete = True
            percent_complete = 100.0

    if not started:
        return None

    # Calculate speed and ETA
    speed_bps = int(extracted_bytes / elapsed_seconds) if elapsed_seconds > 0 else 0
    remaining_bytes = total_bytes - extracted_bytes
    eta_seconds = int(remaining_bytes / speed_bps) if speed_bps > 0 and not is_complete else 0

    return {
        "extracted_bytes": extracted_bytes,
        "total_bytes": total_bytes,
        "percent_complete": percent_complete,
        "speed_bps": speed_bps,
        "eta_seconds": eta_seconds,
        "files_extracted": files_extracted,
        "total_files": total_files,
        "is_complete": is_complete,
    }
```

---

## Step 6: Update routes.py - Route Context

**File**: [pulldb/web/features/jobs/routes.py](../../pulldb/web/features/jobs/routes.py) (in `job_detail()` function, around line 600)

Add extraction stats calculation and pass to template:

```python
extraction_stats = _calculate_extraction_stats(logs)
```

And in the template context dict:

```python
"extraction_stats": extraction_stats,
```

---

## Step 7: Update details.html - Progress Bar

**File**: [pulldb/web/templates/features/jobs/details.html](../../pulldb/web/templates/features/jobs/details.html) (after download progress section)

Insert extraction progress bar:

```html
{% if extraction_stats %}
<div class="log-progress log-progress--extraction{% if extraction_stats.is_complete %} log-progress--complete{% endif %}" id="extraction-progress">
    <div class="log-progress-bar-row">
        <span class="log-progress-label">Extraction</span>
        <div class="log-progress-bar-container">
            <div class="log-progress-bar" style="width: {{ extraction_stats.percent_complete }}%"></div>
        </div>
        <div class="log-progress-percent">{{ "%.1f" | format(extraction_stats.percent_complete) }}%</div>
        <span class="log-progress-stats">
            {% if extraction_stats.is_complete %}
            ✓ {{ extraction_stats.total_bytes | format_filesize }} ({{ extraction_stats.total_files }} files)
            {% else %}
            {{ extraction_stats.extracted_bytes | format_filesize }} / {{ extraction_stats.total_bytes | format_filesize }}
            ({{ extraction_stats.files_extracted }}/{{ extraction_stats.total_files }} files)
            {% if extraction_stats.eta_seconds > 0 %}
            <span class="log-progress-separator">•</span>
            ETA {{ extraction_stats.eta_seconds | format_eta }}
            {% endif %}
            {% endif %}
        </span>
    </div>
</div>
{% endif %}
```

---

## Step 8: Update main.css - Styling

**File**: [pulldb/web/static/css/main.css](../../pulldb/web/static/css/main.css) (after download styling)

Add extraction progress bar color:

```css
/* Extraction progress (orange/warning) */
.log-progress--extraction .log-progress-bar {
    background: var(--warning-500);
}
```

---

## Step 9: Add Tests

### 9a. Test extraction progress callback

**File**: [tests/qa/worker/test_executor.py](../../tests/qa/worker/test_executor.py)

```python
class TestExtractTarArchiveProgress:
    def test_emits_progress_callback(self, tmp_path: Path) -> None:
        """Progress callback is invoked during extraction."""
        # Create test archive with multiple files
        archive_path = tmp_path / "test.tar"
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        for i in range(10):
            (content_dir / f"file_{i}.txt").write_text("x" * 10000)
        
        with tarfile.open(archive_path, "w") as tar:
            for f in content_dir.iterdir():
                tar.add(f, arcname=f.name)
        
        progress_calls = []
        def callback(extracted, total, percent, elapsed, files_done, total_files):
            progress_calls.append((extracted, total, percent, files_done, total_files))
        
        dest = tmp_path / "extracted"
        extract_tar_archive(str(archive_path), dest, "test-job", callback)
        
        assert len(progress_calls) >= 1
        # Final call should show 100% complete
        assert progress_calls[-1][2] == 100.0
        assert progress_calls[-1][3] == 10  # 10 files

    def test_abort_raises_cancellation_error(self, tmp_path: Path) -> None:
        """Abort check triggers CancellationError."""
        # Create archive
        archive_path = tmp_path / "test.tar"
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        for i in range(5):
            (content_dir / f"file_{i}.txt").write_text("test")
        
        with tarfile.open(archive_path, "w") as tar:
            for f in content_dir.iterdir():
                tar.add(f, arcname=f.name)
        
        abort_after = [2]  # Abort after 2 files
        files_seen = [0]
        
        def abort_check():
            return files_seen[0] >= abort_after[0]
        
        def progress_cb(*args):
            files_seen[0] = args[3]  # files_extracted
        
        dest = tmp_path / "extracted"
        with pytest.raises(CancellationError):
            extract_tar_archive(str(archive_path), dest, "test-job", progress_cb, abort_check)
```

### 9b. Test extraction events emitted

**File**: [tests/qa/worker/test_executor.py](../../tests/qa/worker/test_executor.py)

```python
def test_extraction_events_emitted(self, ...) -> None:
    """Extraction emits started, progress, and complete events."""
    # ... setup and execute job ...
    
    events = [e.event_type for e in job_events]
    assert "extraction_started" in events
    assert "extraction_progress" in events
    assert "extraction_complete" in events

def test_time_based_progress_fallback(self, tmp_path: Path, monkeypatch) -> None:
    """Progress emits every 30s even with no byte/file threshold hit."""
    # Mock time to simulate 30+ seconds passing
    # Verify progress callback is invoked due to time threshold
```

---

## Files Modified Summary

| File | Changes |
|------|---------|
| [pulldb/worker/executor.py](../../pulldb/worker/executor.py) | Add time import, constants, rewrite extraction functions with progress/abort/time-fallback |
| [pulldb/web/features/jobs/routes.py](../../pulldb/web/features/jobs/routes.py) | Add event mapping (4 events), stats calculation, route context |
| [pulldb/web/templates/features/jobs/details.html](../../pulldb/web/templates/features/jobs/details.html) | Add extraction progress bar HTML |
| [pulldb/web/static/css/main.css](../../pulldb/web/static/css/main.css) | Add extraction progress bar styling |
| [tests/qa/worker/test_executor.py](../../tests/qa/worker/test_executor.py) | Add extraction progress and time-fallback tests |

---

## Event Schema

### extraction_started
```json
{
    "archive_path": "/path/to/archive.tar",
    "archive_size": 95020830720
}
```

### extraction_progress
```json
{
    "extracted_bytes": 67108864,
    "total_bytes": 95020830720,
    "percent_complete": 0.7,
    "elapsed_seconds": 12.5,
    "files_extracted": 1500,
    "total_files": 150000
}
```

### extraction_complete
```json
{
    "path": "/mnt/data/work/pulldb.service/job-id/extracted"
}
```

### extraction_failed
```json
{
    "error": "Archive entry escapes extraction directory",
    "job_id": "abc-123"
}
```
