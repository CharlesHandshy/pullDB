# VirtualLog Widget

> **HCA Layer**: widgets (Layer 3)  
> **Location**: `pulldb/web/static/widgets/virtual_log/`  
> **Version**: 1.0.0

A high-performance virtual scrolling log viewer for displaying large event logs. Only renders visible rows in the DOM while the scrollbar reflects the true total size of the data.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Configuration](#configuration)
4. [Usage](#usage)
5. [API Reference](#api-reference)
6. [Backend API Contract](#backend-api-contract)
7. [CSS Customization](#css-customization)
8. [Performance Characteristics](#performance-characteristics)
9. [Debugging](#debugging)

---

## Overview

### Problem Statement

Displaying thousands of log events in a web UI causes:
- **DOM bloat**: 10,000 rows = 10,000+ DOM nodes
- **Memory pressure**: Each row with event listeners and styles
- **Scroll jank**: Browser struggles to paint/composite large DOMs

### Solution

VirtualLog renders only ~30-50 rows at any time, regardless of total event count:

```
┌─────────────────────────────────┐
│ Scrollbar reflects 10,000 rows  │ ← Spacer element sets height
├─────────────────────────────────┤
│ [Row 150] visible               │
│ [Row 151] visible               │ ← Only ~30 DOM nodes
│ [Row 152] visible               │
│ ...                             │
├─────────────────────────────────┤
│ translateY positions content    │ ← CSS transform, no reflow
└─────────────────────────────────┘
```

### Key Features

- **True virtual scroll**: Scrollbar accurately represents data size
- **Debounced loading**: Prevents request storms during rapid scroll
- **Request cancellation**: Aborts stale requests when scroll continues
- **Dual fetch strategy**: Cursor-based for sequential, offset-based for jumps
- **Live polling**: Auto-updates for running jobs
- **Memory bounded**: Cache trimmed to configurable limit

---

## Architecture

### Loading Strategy Decision Tree

```
_onScroll()
    │
    ├─► _render() [IMMEDIATE]
    │   Shows cached data or placeholders instantly
    │
    ├─► Abort in-flight request
    │   Prevents stale data from overwriting
    │
    └─► setTimeout(150ms) → _loadVisibleRange()
                                │
                                ├─► _hasCachedRange() → 80%+ cached? → Skip load
                                │
                                ├─► _canExtendCache() → Gap ≤ pageSize?
                                │       │
                                │       ├─► YES → _fetchToExtendCache()
                                │       │         Uses cursor pagination
                                │       │
                                │       └─► NO → _fetchByOffset()
                                │                Direct offset/limit query
                                │
                                └─► Re-render with loaded data
```

### Cache Design

Position-based cache where `position 0 = newest event`:

```javascript
this._cache = new Map();      // position → event object
this._cacheStartPos = 0;      // Lowest cached position
this._cacheEndPos = 50;       // Highest position + 1
```

Cache window slides to follow viewport and trims when exceeding `maxCachedEvents`.

### DOM Structure

```html
<div class="virtual-log-widget">           <!-- Container -->
  <div class="virtual-log-scroll">         <!-- Scroll container -->
    <div class="virtual-log-spacer">       <!-- Sets total height -->
    </div>
    <div class="virtual-log-content">      <!-- Positioned content -->
      <div class="virtual-log-entry">...</div>
      <div class="virtual-log-entry">...</div>
      <!-- Only visible rows -->
    </div>
  </div>
</div>
```

---

## Configuration

### Constructor Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `container` | `HTMLElement` | **required** | Parent element for the widget |
| `jobId` | `string` | **required** | Job ID for API calls |
| `totalEvents` | `number` | `0` | Initial total event count |
| `isRunning` | `boolean` | `false` | Enable polling for live updates |
| `initialEvents` | `Array` | `[]` | Pre-loaded events (newest first) |
| `pollInterval` | `number` | `5000` | Polling interval in ms |

### Internal Config (modify in constructor)

| Property | Default | Description |
|----------|---------|-------------|
| `rowHeight` | `32` | Fixed row height in pixels |
| `pageSize` | `50` | Events per API request |
| `bufferRows` | `10` | Extra rows above/below viewport |
| `maxCachedEvents` | `300` | Maximum events in memory |
| `debounceMs` | `150` | Scroll settle delay before loading |

---

## Usage

### Basic Initialization

```javascript
const container = document.getElementById('log-container');

const virtualLog = new VirtualLog({
    container: container,
    jobId: 'job-123',
    totalEvents: 5000,
    isRunning: false,
    initialEvents: preloadedEvents  // First 50 events from server
});
```

### With Server-Side Pre-loading (Recommended)

```python
# Python/Jinja template
events = job_repo.get_job_events(job_id, limit=50)
total_count = job_repo.get_job_event_count(job_id)
```

```html
<script>
    const initialData = {{ events | tojson }};
    const totalCount = {{ total_count }};
    
    const log = new VirtualLog({
        container: document.getElementById('execution-log'),
        jobId: '{{ job.id }}',
        totalEvents: totalCount,
        isRunning: {{ 'true' if job.is_running else 'false' }},
        initialEvents: initialData
    });
</script>
```

### Cleanup

```javascript
// When removing from DOM or navigating away
virtualLog.destroy();
```

---

## API Reference

### Public Methods

#### `constructor(options)`
Creates a new VirtualLog instance. See [Configuration](#configuration) for options.

#### `destroy()`
Cleans up the widget:
- Stops polling
- Cancels pending debounce timer
- Aborts in-flight requests
- Removes event listeners
- Clears DOM and cache

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `totalEvents` | `number` | Current total event count |
| `isRunning` | `boolean` | Whether polling is enabled |

---

## Backend API Contract

The widget expects a REST endpoint at:

```
GET /web/jobs/{job_id}/events
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | `int` | Max events to return (default: 50) |
| `offset` | `int` | Position offset for jump scrolling |
| `cursor` | `int` | Event ID for cursor pagination |
| `direction` | `string` | `"older"` or `"newer"` (relative to cursor) |

### Response Format

```json
{
    "events": [
        {
            "id": 12345,
            "event_type": "restore_progress",
            "logged_at": "2026-01-29T10:30:00Z",
            "detail": {
                "percent": 45.5,
                "tables_complete": 10,
                "tables_total": 25
            }
        }
    ],
    "total_count": 5000,
    "has_more": true,
    "offset": 100
}
```

### Event Object Schema

| Field | Type | Description |
|-------|------|-------------|
| `id` | `int` | Unique event ID (for cursor pagination) |
| `event_type` | `string` | Event type identifier |
| `logged_at` | `string` | ISO 8601 timestamp |
| `detail` | `object` | Event-specific payload |

### Database Index Requirement

For efficient offset queries, create this index:

```sql
CREATE INDEX idx_job_events_job_id_desc 
ON job_events(job_id, id DESC);
```

---

## CSS Customization

### Required CSS Variables

The widget uses design tokens from your CSS manifest:

```css
/* Colors */
--color-border
--color-surface-hover
--color-text-muted
--color-text-secondary
--color-primary
--color-success
--color-error
--color-warning
--color-info
--color-scrollbar-thumb
--color-scrollbar-track
--color-scrollbar-thumb-hover

/* Typography */
--font-mono
--font-medium
--text-xs
--text-sm
--leading-relaxed

/* Spacing */
--space-2
--space-3
--space-4
--space-8
```

### Entry Variants

Style entries by event type:

```css
.virtual-log-entry--success .virtual-log-entry__type { color: green; }
.virtual-log-entry--error .virtual-log-entry__type { color: red; }
.virtual-log-entry--warning .virtual-log-entry__type { color: orange; }
.virtual-log-entry--info .virtual-log-entry__type { color: blue; }
.virtual-log-entry--loading { opacity: 0.5; }
```

### Container Sizing

The widget fills its container. Ensure the container has defined dimensions:

```css
#log-container {
    height: 400px;  /* Or flex: 1 in a flex container */
}
```

---

## Performance Characteristics

### Memory

| Events | DOM Nodes | Cache Memory |
|--------|-----------|--------------|
| 100 | ~30 | ~50 events |
| 10,000 | ~30 | ~300 events |
| 100,000 | ~30 | ~300 events |

DOM nodes remain constant. Cache is bounded by `maxCachedEvents`.

### Network

| Action | Requests |
|--------|----------|
| Slow scroll | 1 per `pageSize` rows crossed |
| Rapid scroll wheel | 1 (after 150ms settle) |
| Scrollbar drag | 1 (after 150ms settle) |
| Poll (running job) | 1 per `pollInterval` |

### Rendering

- Uses `DocumentFragment` for batch DOM updates
- Uses `transform: translateY()` for positioning (GPU accelerated)
- Skips render if visible range unchanged

---

## Debugging

### Console Logging

The widget logs loading activity:

```
[VirtualLog] Load #1 starting: 0-35, strategy: offset
[VirtualLog] Fetching offset=0, limit=35
[VirtualLog] Got 35 events
[VirtualLog] Load #1 complete, rendering

[VirtualLog] Load #2 starting: 100-135, strategy: offset
[VirtualLog] Load #2 cancelled  ← User scrolled before completion

[VirtualLog] Load #3 starting: 200-235, strategy: extend
[VirtualLog] Load #3 complete, rendering
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Loading row X..." never resolves | API error or network issue | Check Network tab for failed requests |
| Scrollbar height wrong | `totalEvents` not set correctly | Ensure server returns `total_count` |
| Scroll stutters | `rowHeight` doesn't match CSS | Ensure CSS `.virtual-log-entry` height matches config |
| Duplicate events | Cursor pagination bug | Check `id` uniqueness in events |
| Missing events after jump | Offset query not using index | Add `idx_job_events_job_id_desc` index |

### State Inspection

```javascript
// In browser console
const log = window.virtualLogInstance;  // If exposed globally

console.log('Cache size:', log._cache.size);
console.log('Cache range:', log._cacheStartPos, '-', log._cacheEndPos);
console.log('Total events:', log.totalEvents);
console.log('Visible range:', log._getVisibleRange());
console.log('Is loading:', log._isLoading);
```

---

## Extending the Widget

### Custom Event Formatters

Override `_formatDetails()` to add custom event type formatting:

```javascript
class MyVirtualLog extends VirtualLog {
    _formatDetails(event) {
        if (event.event_type === 'custom_event') {
            return `Custom: ${event.detail.custom_field}`;
        }
        return super._formatDetails(event);
    }
}
```

### Custom Entry Rendering

Override `_createEntry()` for completely custom row rendering:

```javascript
class MyVirtualLog extends VirtualLog {
    _createEntry(event) {
        const el = document.createElement('div');
        el.className = 'my-custom-entry';
        el.innerHTML = `<custom-event-component data-event='${JSON.stringify(event)}'></custom-event-component>`;
        return el;
    }
}
```

---

## Files

| File | Purpose |
|------|---------|
| `virtual_log.js` | Widget class implementation |
| `virtual_log.css` | Styles using design tokens |

---

## Changelog

### v1.0.0 (2026-01-29)
- Initial release with debounced loading
- Dual strategy: cursor-based and offset-based fetching
- AbortController for request cancellation
- Load ID tracking to prevent race conditions
- Cache cleared only after successful fetch
