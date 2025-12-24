# VirtualTable Widget

A high-performance, reusable table component with virtual scrolling, filtering, and sorting capabilities.

## Features

- **Virtual Scrolling**: Efficiently renders only visible rows, handling thousands of rows with ease
- **Multi-column Sorting**: Click to sort, shift+click for multi-column sorting
- **Status Filtering**: Quick filter buttons for status-based filtering
- **Column Filtering**: Dropdown checkboxes for filtering specific columns
- **Filter Chips**: Visual display of active filters with easy removal
- **Keyboard Navigation**: Arrow keys, Page Up/Down, Home/End support
- **Paging Controls**: First/Prev/Next/Last navigation
- **Configurable Columns**: Custom renderers, types, alignment, and width
- **Row Actions**: Configurable action buttons per row
- **Responsive**: Works well in flex/grid layouts

## Installation

Include the CSS and JS files:

```html
<link rel="stylesheet" href="/static/widgets/virtual_table/virtual_table.css">
<script src="/static/widgets/virtual_table/virtual_table.js"></script>
```

Or use the Jinja template:

```jinja
{% include "widgets/virtual_table/virtual_table.html" %}
```

## Basic Usage

```javascript
const table = new VirtualTable({
    container: document.getElementById('my-table'),
    data: [
        { id: 1, name: 'Alice', status: 'active', created: '2024-01-15T10:00:00Z' },
        { id: 2, name: 'Bob', status: 'inactive', created: '2024-01-14T09:00:00Z' },
        // ... more data
    ],
    columns: [
        { key: 'name', label: 'Name', sortable: true, filterable: true },
        { key: 'status', label: 'Status', sortable: true, filterable: true },
        { key: 'created', label: 'Created', sortable: true, type: 'date' }
    ]
});
```

## Configuration Options

### Required Options

| Option | Type | Description |
|--------|------|-------------|
| `container` | HTMLElement | Container element for the table |
| `columns` | Array | Column definitions (see below) |

### Optional Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `data` | Array | `[]` | Initial data array |
| `rowHeight` | number | `44` | Height of each row in pixels |
| `statusFilters` | Array | `null` | Status values for quick filter buttons |
| `statusField` | string | `'status'` | Field name for status filtering |
| `onRowClick` | Function | `null` | Callback when row is clicked |
| `actions` | Function | `null` | Function returning action buttons HTML |
| `rowClass` | Function | `null` | Function returning additional row classes |
| `emptyMessage` | string | `'No data available'` | Message when no data |
| `tableId` | string | auto-generated | ID prefix for table elements |
| `i18n` | Object | see below | Internationalization strings |

### Column Definition

```javascript
{
    key: 'fieldName',           // Required: data field key
    label: 'Display Name',      // Required: column header text
    sortable: true,             // Optional: enable sorting
    filterable: true,           // Optional: enable column filter
    type: 'string',             // Optional: 'string', 'number', 'date'
    width: '150px',             // Optional: fixed width
    align: 'left',              // Optional: 'left', 'center', 'right'
    className: 'custom-class',  // Optional: additional cell class
    render: (value, row, index) => {  // Optional: custom renderer
        return `<span class="badge">${value}</span>`;
    }
}
```

### Actions Function

```javascript
actions: (row, index) => `
    <a href="/view/${row.id}" class="btn-icon">View</a>
    <button onclick="deleteRow(${row.id})" class="btn-icon">Delete</button>
`
```

### Row Class Function

```javascript
rowClass: (row, index) => {
    if (row.status === 'error') return 'row-error';
    if (index % 2 === 0) return 'row-even';
    return '';
}
```

## Public API

### Methods

| Method | Description |
|--------|-------------|
| `setData(data)` | Replace all data and re-render |
| `getData()` | Get current filtered/sorted data |
| `getOriginalData()` | Get original unfiltered data |
| `refresh()` | Recalculate viewport and re-render |
| `destroy()` | Clean up and remove the widget |

### Example: Updating Data

```javascript
// Fetch new data and update table
fetch('/api/jobs')
    .then(res => res.json())
    .then(data => table.setData(data));
```

## Styling

The widget uses CSS custom properties for theming:

```css
:root {
    /* Surfaces */
    --color-surface-primary: #ffffff;
    --color-surface-secondary: #f8f9fa;
    --color-surface-hover: #f3f4f6;
    
    /* Text */
    --color-text-primary: #111827;
    --color-text-secondary: #374151;
    --color-text-muted: #6b7280;
    
    /* Borders */
    --color-border-primary: #e5e7eb;
    --color-border-secondary: #f3f4f6;
    
    /* Primary color */
    --primary-50: #eff6ff;
    --primary-100: #dbeafe;
    --primary-500: #3b82f6;
    --primary-600: #2563eb;
    --primary-700: #1d4ed8;
    
    /* Status colors */
    --status-queued-bg: #fef9c3;
    --status-queued-text: #854d0e;
    --status-running-bg: #dbeafe;
    --status-running-text: #1e40af;
    --status-complete-bg: #dcfce7;
    --status-complete-text: #166534;
    --status-failed-bg: #fee2e2;
    --status-failed-text: #991b1b;
    
    /* Spacing */
    --space-1: 4px;
    --space-2: 8px;
    --space-3: 12px;
    --space-4: 16px;
    --space-8: 32px;
    
    /* Radius */
    --radius-md: 6px;
    --radius-lg: 8px;
    --radius-full: 9999px;
}
```

## Example: Complete Implementation

```html
<div id="jobs-table-container"></div>

<script>
const jobsTable = new VirtualTable({
    container: document.getElementById('jobs-table-container'),
    tableId: 'jobs',
    data: jobsData,  // Your data array
    rowHeight: 44,
    statusFilters: ['queued', 'running', 'complete', 'failed'],
    statusField: 'status',
    emptyMessage: 'No jobs found',
    
    columns: [
        { 
            key: 'target', 
            label: 'Target Database', 
            sortable: true, 
            filterable: true,
            render: (val) => `<span class="font-mono">${val}</span>`
        },
        { 
            key: 'status', 
            label: 'Status', 
            sortable: true, 
            filterable: true,
            align: 'center',
            render: (val) => `<span class="badge badge-${val}">${val}</span>`
        },
        { 
            key: 'owner', 
            label: 'Owner', 
            sortable: true, 
            filterable: true 
        },
        { 
            key: 'submitted', 
            label: 'Submitted', 
            sortable: true, 
            type: 'date' 
        }
    ],
    
    actions: (row) => `
        <a href="/jobs/${row.id}" class="btn-icon" title="View">
            <svg>...</svg>
        </a>
    `,
    
    onRowClick: (row, index) => {
        window.location.href = `/jobs/${row.id}`;
    }
});
</script>
```

## Browser Support

- Chrome 60+
- Firefox 55+
- Safari 12+
- Edge 79+

## HCA Compliance

This widget is Layer 3 (widgets) in the Hierarchical Containment Architecture:
- Can import from: shared (Layer 1), entities (Layer 2)
- Cannot import from: features (Layer 4), pages (Layer 5), plugins (Layer 6)
