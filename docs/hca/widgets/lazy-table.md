# LazyTable Widget

> **Version**: 1.0.1 | **Last Updated**: January 2026

LazyTable is the core reusable table component used throughout pullDB's Web UI for displaying paginated, sortable, filterable data with bulk selection capabilities.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Features](#features)
4. [API Contract](#api-contract)
5. [JavaScript API](#javascript-api)
6. [Usage Examples](#usage-examples)
7. [Styling](#styling)

---

## Overview

### What is LazyTable?

LazyTable is a vanilla JavaScript table component that:
- Loads data lazily (on demand)
- Supports server-side pagination
- Provides sortable columns
- Enables column filtering
- Supports bulk row selection
- Works without JavaScript frameworks

### Where It's Used

| Page | Purpose |
|------|---------|
| My Databases | Job list with status filters |
| Manager Dashboard | Team member jobs |
| Admin Jobs | All system jobs |
| Feature Requests | Request list with voting |
| Orphan Databases | Paginated orphan scan results |
| Audit Logs | Filterable log entries |

---

## Architecture

### Component Structure

```
LazyTable
├── Header Row
│   ├── Checkbox (bulk select all)
│   ├── Sortable Column Headers
│   └── Filter Dropdowns
├── Body
│   ├── Data Rows
│   │   ├── Checkbox (row select)
│   │   └── Cell Data
│   └── Loading Skeleton
├── Footer
│   ├── Page Info ("1-50 of 234")
│   ├── Page Size Selector
│   └── Pagination Controls
└── Bulk Action Bar (when rows selected)
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  User Action (sort/filter/page) ──► LazyTable State Update     │
│                                           │                     │
│                                           ▼                     │
│                                    Build API URL                │
│                                           │                     │
│                                           ▼                     │
│                                    fetch() to API               │
│                                           │                     │
│                                           ▼                     │
│                                    Parse Response               │
│                                           │                     │
│                                           ▼                     │
│                                    Render Table ◄───────────────┤
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### State Management

LazyTable maintains internal state:

```javascript
{
  page: 1,
  pageSize: 50,
  sortColumn: 'created_at',
  sortDirection: 'desc',
  filters: {
    status: 'deployed',
    search: 'customers'
  },
  selectedRows: [1, 5, 12],
  loading: false,
  data: [...],
  total: 234
}
```

---

## Features

### Pagination

- **Server-side**: Only loads current page
- **Configurable page sizes**: 10, 25, 50, 100
- **Jump to page**: Direct page number input
- **First/Last/Prev/Next**: Full navigation controls

### Sorting

- **Click column header**: Toggle sort direction
- **Visual indicator**: Arrow shows sort column and direction
- **Single column sort**: One sort column at a time
- **Server-side**: Sort parameter sent to API

### Filtering

- **Dropdown filters**: Select from predefined options
- **Text search**: Free-text search (debounced)
- **Multiple filters**: Combine multiple filters
- **Clear all**: Reset all filters button
- **URL sync**: Filters reflected in URL for sharing

### Bulk Selection

- **Header checkbox**: Select/deselect all on page
- **Row checkboxes**: Select individual rows
- **Selection count**: Shows "X selected" badge
- **Bulk actions**: Action buttons appear when rows selected
- **Persistence**: Selection maintained across page changes

---

## API Contract

### Request Format

LazyTable expects the API endpoint to accept these query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | int | Page number (1-indexed) |
| `page_size` | int | Items per page |
| `sort` | string | Column to sort by |
| `sort_dir` | string | `asc` or `desc` |
| `{filter_name}` | string | Filter values |

**Example URL:**
```
/api/jobs?page=2&page_size=50&sort=created_at&sort_dir=desc&status=deployed
```

### Response Format

API must return JSON with this structure:

```json
{
  "items": [
    {"id": 1, "name": "...", ...},
    {"id": 2, "name": "...", ...}
  ],
  "total": 234,
  "page": 2,
  "page_size": 50
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `items` | array | Yes | Array of row objects |
| `total` | int | Yes | Total items (all pages) |
| `page` | int | Yes | Current page number |
| `page_size` | int | Yes | Items per page |

### Row ID Requirement

Each item must have a unique identifier field (default: `id`). This is used for:
- Row selection tracking
- Bulk action payloads
- Row key for rendering

---

## JavaScript API

### Initialization

```javascript
const table = new LazyTable({
  container: '#job-table',
  apiUrl: '/api/jobs',
  columns: [
    { key: 'id', label: 'ID', sortable: true },
    { key: 'source_db', label: 'Database', sortable: true },
    { key: 'status', label: 'Status', sortable: true, 
      filter: { type: 'dropdown', options: ['queued', 'running', 'deployed'] }},
    { key: 'created_at', label: 'Created', sortable: true,
      format: 'datetime' },
    { key: 'actions', label: '', 
      render: (row) => `<button data-id="${row.id}">View</button>` }
  ],
  defaultSort: { column: 'created_at', direction: 'desc' },
  selectable: true,
  onSelect: (selectedIds) => console.log('Selected:', selectedIds),
  onRowClick: (row) => window.location = `/jobs/${row.id}`
});
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `container` | string | required | CSS selector for container |
| `apiUrl` | string | required | API endpoint URL |
| `columns` | array | required | Column definitions |
| `defaultSort` | object | - | Initial sort column/direction |
| `defaultPageSize` | int | 50 | Initial page size |
| `pageSizes` | array | [10,25,50,100] | Available page sizes |
| `selectable` | boolean | false | Enable row selection |
| `idField` | string | 'id' | Row identifier field |
| `onSelect` | function | - | Selection change callback |
| `onRowClick` | function | - | Row click callback |
| `onLoad` | function | - | Data load callback |
| `emptyMessage` | string | 'No data' | Empty state message |

### Column Definition

```javascript
{
  key: 'status',           // Field name in row data
  label: 'Status',         // Column header text
  sortable: true,          // Enable sorting
  width: '100px',          // Optional fixed width
  align: 'center',         // Text alignment
  format: 'datetime',      // Built-in formatter
  render: (row) => html,   // Custom render function
  filter: {                // Enable filtering
    type: 'dropdown',      // 'dropdown' or 'text'
    options: [...],        // Dropdown options
    placeholder: '...'     // Placeholder text
  }
}
```

### Built-in Formatters

| Format | Description |
|--------|-------------|
| `datetime` | ISO date to locale string |
| `date` | ISO date to locale date |
| `time` | ISO date to locale time |
| `relative` | "5 minutes ago" |
| `boolean` | ✓ or ✗ |
| `number` | Locale number format |
| `bytes` | Human-readable file size |

### Methods

```javascript
// Refresh data
table.refresh();

// Go to specific page
table.goToPage(3);

// Set filter programmatically
table.setFilter('status', 'deployed');

// Clear all filters
table.clearFilters();

// Get selected row IDs
const ids = table.getSelected();

// Clear selection
table.clearSelection();

// Destroy and cleanup
table.destroy();
```

### Events

```javascript
// Listen to events
table.on('load', (data) => console.log('Loaded', data.total, 'items'));
table.on('select', (ids) => updateBulkActions(ids));
table.on('error', (err) => showError(err.message));
```

---

## Usage Examples

### Basic Table

```html
<div id="simple-table"></div>

<script>
new LazyTable({
  container: '#simple-table',
  apiUrl: '/api/users',
  columns: [
    { key: 'username', label: 'Username', sortable: true },
    { key: 'email', label: 'Email', sortable: true },
    { key: 'created_at', label: 'Joined', format: 'date' }
  ]
});
</script>
```

### With Filters and Selection

```html
<div id="job-table"></div>
<div id="bulk-actions" style="display: none;">
  <span id="selected-count"></span> selected
  <button onclick="deleteSelected()">Delete</button>
</div>

<script>
const table = new LazyTable({
  container: '#job-table',
  apiUrl: '/api/jobs',
  selectable: true,
  columns: [
    { key: 'source_db', label: 'Database', sortable: true,
      filter: { type: 'text', placeholder: 'Search...' }},
    { key: 'status', label: 'Status', sortable: true,
      filter: { type: 'dropdown', 
                options: ['queued', 'running', 'deployed', 'failed'] }},
    { key: 'created_at', label: 'Created', format: 'relative' }
  ],
  onSelect: (ids) => {
    document.getElementById('bulk-actions').style.display = 
      ids.length ? 'block' : 'none';
    document.getElementById('selected-count').textContent = ids.length;
  }
});

function deleteSelected() {
  const ids = table.getSelected();
  fetch('/api/jobs/bulk-delete', {
    method: 'POST',
    body: JSON.stringify({ job_ids: ids })
  }).then(() => table.refresh());
}
</script>
```

### Custom Cell Rendering

```javascript
new LazyTable({
  container: '#feature-requests',
  apiUrl: '/api/feature-requests',
  columns: [
    { key: 'title', label: 'Title', sortable: true },
    { key: 'vote_count', label: 'Votes', sortable: true, align: 'center',
      render: (row) => `
        <button class="vote-btn ${row.has_voted ? 'voted' : ''}" 
                data-id="${row.id}">
          ▲ ${row.vote_count}
        </button>
      `
    },
    { key: 'status', label: 'Status',
      render: (row) => `<span class="badge badge-${row.status}">${row.status}</span>`
    }
  ]
});
```

---

## Styling

### CSS Classes

| Class | Description |
|-------|-------------|
| `.lazy-table` | Table container |
| `.lazy-table-header` | Header row |
| `.lazy-table-body` | Body container |
| `.lazy-table-row` | Data row |
| `.lazy-table-row.selected` | Selected row |
| `.lazy-table-cell` | Table cell |
| `.lazy-table-sortable` | Sortable header |
| `.lazy-table-sorted-asc` | Ascending sort |
| `.lazy-table-sorted-desc` | Descending sort |
| `.lazy-table-loading` | Loading state |
| `.lazy-table-empty` | Empty state |
| `.lazy-table-pagination` | Pagination container |

### Theme Integration

LazyTable inherits CSS variables from pullDB's theme:

```css
.lazy-table {
  --table-bg: var(--card-bg);
  --table-border: var(--border-color);
  --table-header-bg: var(--header-bg);
  --table-row-hover: var(--hover-bg);
  --table-row-selected: var(--selected-bg);
}
```

See [Theme System](theme-system.md) for customization.

---

## File Locations

| File | Purpose |
|------|---------|
| `pulldb/web/static/js/lazy-table.js` | Main component |
| `pulldb/web/static/css/lazy-table.css` | Styles |
| `pulldb/web/templates/components/lazy-table.html` | Jinja2 template |

---

## See Also

- [Theme System](theme-system.md) - Styling and theming
- [API Reference](../pages/api-reference.md) - API endpoint formats
- [Web UI Architecture](architecture.md) - Overall web structure
