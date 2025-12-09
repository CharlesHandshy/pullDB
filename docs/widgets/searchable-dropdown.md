# Searchable Dropdown Widget

> **HCA Layer**: widgets  
> **Location**: `pulldb/web/widgets/searchable_dropdown/`

## Overview

The Searchable Dropdown is the standard component for all search/select fields in pullDB.
It implements a consistent type-ahead search pattern:

1. User types in a text box
2. After 3-5 characters, the system fetches and displays matching options
3. User selects an option, which populates the input and closes the dropdown

## Quick Start

### 1. Import the Macros

```jinja
{% from "partials/searchable_dropdown.html" import searchable_dropdown, searchable_dropdown_styles, searchable_dropdown_scripts %}
```

### 2. Include Styles (once per page)

In your `<style>` block or in the `{% block extra_styles %}`:

```jinja
{{ searchable_dropdown_styles() }}
```

### 3. Add the Component

```jinja
{{ searchable_dropdown(
    id="customer",
    name="customer",
    label="Customer Name",
    placeholder="Type at least 5 characters...",
    min_chars=5,
    api_endpoint="/api/customers/search",
    hint="Type 5+ characters to search customers"
) }}
```

### 4. Include Scripts (once per page, before `</body>`)

```jinja
{{ searchable_dropdown_scripts() }}
```

## API Response Format

Your API endpoint should return JSON in this format:

```json
{
    "results": [
        {
            "value": "acmecorp",
            "label": "ACME Corporation",
            "sublabel": "12 backups"
        },
        {
            "value": "bigco",
            "label": "BigCo Industries",
            "sublabel": "8 backups"
        }
    ],
    "total": 42
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `results` | array | Yes | Array of option objects |
| `results[].value` | string | Yes | The value to submit in the form |
| `results[].label` | string | Yes | Primary display text |
| `results[].sublabel` | string | No | Secondary text (shown on right) |
| `total` | number | No | Total matches (for "Showing X of Y") |

## Macro Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `id` | string | (required) | Unique ID for the input |
| `name` | string | (required) | Form field name |
| `label` | string | (required) | Label text above input |
| `placeholder` | string | "Type to search..." | Placeholder text |
| `min_chars` | int | 3 | Min characters before search triggers |
| `debounce_ms` | int | 300 | Delay before API call (ms) |
| `api_endpoint` | string | "" | URL for search API |
| `hint` | string | "" | Help text below input |
| `required` | bool | false | Mark field as required |
| `initial_value` | string | "" | Pre-populated value |
| `initial_label` | string | "" | Pre-populated display text |
| `max_results` | int | 10 | Max options to show |
| `no_results_text` | string | "No results found" | Empty state message |
| `loading_text` | string | "Searching..." | Loading state message |
| `allow_custom` | bool | false | Allow values not in list |
| `class_name` | string | "" | Additional CSS classes |
| `disabled` | bool | false | Disable the input |

## Events

The component dispatches custom events you can listen for:

```javascript
// When user selects an option
document.getElementById('customer').addEventListener('searchable-dropdown:select', (e) => {
    console.log('Selected:', e.detail.value, e.detail.label);
    // e.detail.option contains the full option object
});

// When user clears the selection
document.getElementById('customer').addEventListener('searchable-dropdown:clear', (e) => {
    console.log('Selection cleared');
});
```

## JavaScript API

Each dropdown instance exposes a public API:

```javascript
const dropdown = document.getElementById('customer-container').searchableDropdown;

// Get current value
const value = dropdown.getValue();
const label = dropdown.getLabel();

// Set value programmatically
dropdown.setValue('acmecorp', 'ACME Corporation');

// Clear selection
dropdown.clear();

// Enable/disable
dropdown.disable();
dropdown.enable();
```

## Static Options (No API)

For dropdowns with a fixed list of options:

```jinja
{{ searchable_dropdown_static(
    id="environment",
    name="environment",
    label="Environment",
    options=[
        {"value": "production", "label": "Production"},
        {"value": "staging", "label": "Staging"},
        {"value": "development", "label": "Development"}
    ],
    placeholder="Select environment..."
) }}
```

## Styling Customization

The component uses CSS custom properties from the design system:

```css
/* Override in your page or theme */
.searchable-dropdown-input {
    --dropdown-border-color: var(--gray-300);
    --dropdown-focus-color: var(--primary-500);
}
```

## Accessibility

- Full keyboard navigation (↑↓ arrows, Enter, Escape)
- ARIA attributes for screen readers
- Focus management
- Clear visual feedback for states

## Migration Guide

### From Old Combo Box (restore.html pattern)

Replace:
```html
<div class="combo-container" id="customer-combo">
    <input type="text" id="customer" name="customer" class="form-input combo-input" ...>
    <svg class="input-icon">...</svg>
    <div class="combo-dropdown" id="customer-dropdown"></div>
</div>
```

With:
```jinja
{% from "partials/searchable_dropdown.html" import searchable_dropdown %}
{{ searchable_dropdown(
    id="customer",
    name="customer",
    label="Customer Name",
    min_chars=5,
    api_endpoint="/api/customers/search",
    ...
) }}
```

Update JavaScript:
```javascript
// Old way
customerInput.addEventListener('input', function() { ... });

// New way - listen for events
document.getElementById('customer').addEventListener('searchable-dropdown:select', (e) => {
    selectedCustomer = e.detail.option;
    loadBackups(selectedCustomer);
});
```

## Common Patterns

### Customer Search (5 chars minimum)
```jinja
{{ searchable_dropdown(
    id="customer",
    name="customer", 
    label="Customer Name",
    min_chars=5,
    api_endpoint="/api/customers/search",
    hint="Type 5+ characters to search"
) }}
```

### User Search (3 chars minimum)
```jinja
{{ searchable_dropdown(
    id="user",
    name="user_id",
    label="User",
    min_chars=3,
    api_endpoint="/api/users/search",
    hint="Search by username or name"
) }}
```

### Host Search with Pre-selection
```jinja
{{ searchable_dropdown(
    id="dbhost",
    name="dbhost",
    label="Database Host",
    min_chars=3,
    api_endpoint="/api/hosts/search",
    initial_value=current_host.hostname,
    initial_label=current_host.display_name
) }}
```

## File Locations

| File | Purpose |
|------|---------|
| `widgets/searchable_dropdown/__init__.py` | Python config classes |
| `templates/partials/searchable_dropdown.html` | Jinja macros (HTML/CSS/JS) |
| `docs/widgets/searchable-dropdown.md` | This documentation |
