# pullDB New Page Template Guide

> **Version**: 1.5.0  
> **Last Updated**: January 22, 2026  
> **Status**: Active

This document provides a copy-paste template and reference for creating new pages in the pullDB web UI. All code follows the established design system and HCA architecture.

**Related**: See [DESIGN-ENCYCLOPEDIA.md](DESIGN-ENCYCLOPEDIA.md) for comprehensive standards.

---

## Table of Contents

1. [Quick Start Template](#quick-start-template)
2. [Page Structure](#page-structure)
3. [Breadcrumbs](#breadcrumbs)
4. [Utility Classes Reference](#utility-classes-reference)
5. [Component Patterns](#component-patterns)
6. [Modal Patterns](#modal-patterns)
7. [HTMX Patterns](#htmx-patterns)
8. [Animation & Loading](#animation--loading)
9. [Accessibility](#accessibility-patterns)
10. [Inline Style Rules](#inline-style-rules)
11. [JavaScript Patterns](#javascript-patterns)
12. [Checklist](#checklist)

---

## Quick Start Template

Copy this template for any new feature page:

```html
{% extends "base.html" %}

{% block title %}Page Title - Section - pullDB{% endblock %}

{% block page_id %}section-page-name{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', path='css/pages/section.css') }}">
{# Only add <style> block for truly page-specific styles that can't use utilities #}
{% endblock %}

{# Note: header_title/header_subtitle exist in HCA layouts but aren't rendered in base.html yet #}
{% block header_title %}Page Title{% endblock %}
{% block header_subtitle %}Brief description of page purpose{% endblock %}

{% block header_actions %}
{# Optional: header-level action buttons #}
{% endblock %}

{% block content %}
{% from "partials/icons/_index.html" import icon %}
<div class="feature-page">
    {# Page Header Row #}
    <div class="page-header-row mb-4">
        <div class="page-header-left">
            <h1 class="page-title">
                {{ icon('layout-grid', size='20', class='icon-sm') }}
                Page Title
            </h1>
            {# Optional: inline action button #}
            <button class="btn-icon btn-icon-primary ml-2" onclick="doAction()" title="Action">
                {{ icon('plus', size='18') }}
            </button>
        </div>
        {# Optional: status bar for stats #}
        <div class="status-bar">
            <span class="status-item" title="Total Items">
                {{ icon('database', size='16') }}
                <span class="status-count" id="stat-total">0</span>
                <span class="status-label">total</span>
            </span>
        </div>
    </div>

    {# Flash messages #}
    {% if flash_message %}
    <div class="alert alert-{{ flash_type }} mb-4">
        {{ flash_message }}
    </div>
    {% endif %}

    {# Main content #}
    <div class="card">
        <div class="card-header">
            <div class="card-header-left">
                <h3 class="card-title">
                    {{ icon('list', size='18', class='icon-sm') }}
                    Section Title
                </h3>
            </div>
        </div>
        <div class="card-body">
            {# Content here #}
        </div>
    </div>
</div>
{% endblock %}

{% block modals %}
{# Modals go here, outside main content #}
{% endblock %}

{% block extra_js %}
<script>
document.addEventListener('DOMContentLoaded', function() {
    // Page initialization
});
</script>
{% endblock %}
```

---

## Page Structure

### Base Blocks

| Block | Purpose | Required |
|-------|---------|----------|
| `{% block title %}` | Browser tab title | ✅ Yes |
| `{% block page_id %}` | Unique page identifier for CSS/JS targeting | Recommended |
| `{% block header_title %}` | App header title text | Recommended |
| `{% block header_subtitle %}` | App header subtitle | Optional |
| `{% block header_actions %}` | App header action buttons | Optional |
| `{% block extra_css %}` | Page-specific stylesheets | If needed |
| `{% block content %}` | Main page content | ✅ Yes |
| `{% block modals %}` | Modal dialogs (outside main) | If needed |
| `{% block extra_js %}` | Page JavaScript | If needed |

### Title Convention

```html
{% block title %}Page Name - Section - pullDB{% endblock %}

{# Examples: #}
{% block title %}Users - Admin - pullDB{% endblock %}
{% block title %}Job History - Admin - pullDB{% endblock %}
{% block title %}Host Management - pullDB Admin{% endblock %}
```

### Page ID Convention

```html
{% block page_id %}section-feature{% endblock %}

{# Examples: #}
{% block page_id %}admin-users{% endblock %}
{% block page_id %}admin-job-history{% endblock %}
{% block page_id %}admin-hosts{% endblock %}
```

### Standard Page Layout

```html
<div class="feature-page">
    {# Page Header Row - title + optional stats #}
    <div class="page-header-row mb-4">
        <div class="page-header-left">
            <h1 class="page-title">
                {{ icon('icon-name', size='20', class='icon-sm') }}
                Page Title
            </h1>
        </div>
        <div class="status-bar">
            {# Status items for quick stats #}
        </div>
    </div>

    {# Flash messages #}
    {% if flash_message %}
    <div class="alert alert-{{ flash_type }} mb-4">
        {{ flash_message }}
    </div>
    {% endif %}

    {# Stats row (alternative to status-bar for detailed stats) #}
    <div class="admin-stats-row">
        <div class="admin-stat-card">
            <div class="admin-stat-label">Label</div>
            <div class="admin-stat-value">42</div>
        </div>
    </div>
    
    {# Main content card #}
    <div class="card">
        <div class="card-header">
            <div class="card-header-left">
                <h3 class="card-title">
                    {{ icon('list', size='18', class='icon-sm') }}
                    Section Title
                </h3>
            </div>
            <div class="card-actions">
                {# Header action buttons #}
            </div>
        </div>
        <div class="card-body">
            {# Content #}
        </div>
    </div>
</div>
```

---

## Breadcrumbs

Navigation context is provided by the route, not the template. Set up in your route handler:

### Route Setup

```python
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs

@router.get("/web/admin/my-feature")
async def my_feature_page(request: Request, ...):
    return templates.TemplateResponse(
        "features/admin/my_feature.html",
        {
            "request": request,
            "breadcrumbs": get_breadcrumbs("admin"),  # ← Pre-defined path
            # ... other context
        }
    )
```

### Pre-defined Breadcrumb Keys

| Key | Path |
|-----|------|
| `"dashboard"` | Dashboard |
| `"my_jobs"` | Dashboard → My Jobs |
| `"admin"` | Dashboard → Administration |
| `"admin_users"` | Dashboard → Administration → Users |
| `"admin_job_history"` | Dashboard → Administration → Job History |
| `"manager"` | Dashboard → Team Management |
| `"job_detail"` | Dashboard → Jobs → Job (use with `job=job_id[:8]`) |

### Custom Breadcrumbs

```python
from pulldb.web.widgets.breadcrumbs import build_breadcrumbs

breadcrumbs = build_breadcrumbs(
    ("Dashboard", "/web/dashboard"),
    ("Custom Section", "/web/custom"),
    ("Current Page", None),  # Last item has url=None (not a link)
)
```

---

## Utility Classes Reference

### ⚠️ CRITICAL: Always Use Utilities Over Inline Styles

**NEVER** write inline styles when a utility class exists. This is the #1 source of technical debt.

### Display

```html
<div class="flex">              <!-- display: flex -->
<div class="inline-flex">       <!-- display: inline-flex -->
<div class="block">             <!-- display: block -->
<div class="hidden">            <!-- display: none -->
<div class="js-hidden">         <!-- display: none (JS-controlled visibility) -->
```

### Flexbox

```html
<!-- Direction -->
<div class="flex flex-row">     <!-- row (default) -->
<div class="flex flex-col">     <!-- column -->

<!-- Justify (main axis) -->
<div class="flex justify-start">
<div class="flex justify-center">
<div class="flex justify-between">
<div class="flex justify-end">

<!-- Align (cross axis) -->
<div class="flex items-start">
<div class="flex items-center">
<div class="flex items-end">
<div class="flex items-baseline">

<!-- Gap -->
<div class="flex gap-2">        <!-- 8px -->
<div class="flex gap-3">        <!-- 12px -->
<div class="flex gap-4">        <!-- 16px -->

<!-- Flex item utilities -->
<div class="flex-1">            <!-- flex: 1 1 0% -->
<div class="flex-shrink-0">     <!-- flex-shrink: 0 -->
```

### Spacing (Margin)

```html
<!-- All sides -->
<div class="m-0">               <!-- margin: 0 -->
<div class="m-4">               <!-- margin: 16px -->

<!-- Top margin (most common for section spacing) -->
<div class="mt-2">              <!-- margin-top: 8px -->
<div class="mt-3">              <!-- margin-top: 12px -->
<div class="mt-4">              <!-- margin-top: 16px -->
<div class="mt-6">              <!-- margin-top: 24px -->
<div class="mt-8">              <!-- margin-top: 32px -->

<!-- Bottom margin (most common for elements) -->
<div class="mb-2">              <!-- margin-bottom: 8px -->
<div class="mb-3">              <!-- margin-bottom: 12px -->
<div class="mb-4">              <!-- margin-bottom: 16px -->
<div class="mb-6">              <!-- margin-bottom: 24px -->

<!-- Horizontal margins -->
<div class="ml-2">              <!-- margin-left: 8px -->
<div class="mr-2">              <!-- margin-right: 8px -->
<div class="mx-auto">           <!-- margin: 0 auto (centering) -->
```

### Spacing (Padding)

```html
<div class="p-4">               <!-- padding: 16px -->
<div class="px-4">              <!-- padding-left/right: 16px -->
<div class="py-2">              <!-- padding-top/bottom: 8px -->
```

### Typography

```html
<!-- Size -->
<span class="text-xs">          <!-- 0.75rem (12px) -->
<span class="text-sm">          <!-- 0.875rem (14px) -->
<span class="text-base">        <!-- 1rem (16px) -->
<span class="text-lg">          <!-- 1.125rem (18px) -->

<!-- Weight -->
<span class="font-medium">      <!-- 500 -->
<span class="font-semibold">    <!-- 600 -->
<span class="font-bold">        <!-- 700 -->

<!-- Color -->
<span class="text-muted">       <!-- Secondary/muted text -->
<span class="text-secondary">   <!-- Secondary text color -->
<span class="text-primary">     <!-- Primary brand blue -->
<span class="text-success">     <!-- Green -->
<span class="text-warning">     <!-- Amber -->
<span class="text-danger">      <!-- Red -->

<!-- Alignment -->
<div class="text-left">
<div class="text-center">
<div class="text-right">

<!-- Font -->
<span class="font-mono">        <!-- Monospace (for IDs, codes, technical values) -->
```

### Width Constraints

```html
<!-- Content max-widths -->
<div class="max-w-md">          <!-- Medium content width -->
<div class="max-w-lg">          <!-- Large content width -->
<div class="max-w-full">        <!-- Full width -->

<!-- Form input widths (for number inputs, small fields) -->
<input class="max-w-input-xs">  <!-- 60px -->
<input class="max-w-input-sm">  <!-- 100px -->
<input class="max-w-input-md">  <!-- 150px -->
<input class="max-w-input-lg">  <!-- 200px -->
```

### Icons

The icon system uses HCA-layered Jinja macros. Import and use at the top of your `{% block content %}`:

```html
{% from "partials/icons/_index.html" import icon %}

<!-- Signature: icon(name, size='20', class='', stroke_width='1.5') -->

<!-- Size guidelines -->
{{ icon('check', size='12', class='icon-xs') }}    <!-- Micro: badges -->
{{ icon('check', size='16', class='icon-sm') }}    <!-- Inline: text, tables -->
{{ icon('check', size='18') }}                      <!-- Buttons -->
{{ icon('check', size='20', class='icon-md') }}    <!-- Default: card titles -->
{{ icon('check', size='24', class='icon-lg') }}    <!-- Large: page titles -->
{{ icon('check', size='48', class='icon-xl') }}    <!-- Empty states -->

<!-- Common patterns -->
{{ icon('plus', size='18') }}                      <!-- Button icons -->
{{ icon('database', size='16') }}                  <!-- Status bar icons -->
{{ icon('info', size='16', class='text-primary') }} <!-- With color class -->
```

#### Available Icons by Layer

| Layer | Icons |
|-------|-------|
| **shared** | database, server, cloud, cog, folder, globe |
| **entities** | user, users, shield, key, lock |
| **features** | play, pause, check, x, alert-triangle, alert-circle, clock |
| **widgets** | menu, chevron-down, chevron-right, arrow-left, refresh |
| **pages** | home, layout-grid, settings |

**Note:** Unknown icon names render a question mark placeholder with `data-icon="unknown:name"` for debugging.

### Borders & Radius

```html
<div class="border">            <!-- 1px solid border -->
<div class="border-t">          <!-- Top border only -->
<div class="border-b">          <!-- Bottom border only -->

<div class="rounded">           <!-- Standard radius (8px) -->
<div class="rounded-lg">        <!-- Large radius (12px) -->
<div class="rounded-full">      <!-- Fully rounded (pills) -->
```

### Shadows

```html
<div class="shadow-sm">         <!-- Subtle shadow -->
<div class="shadow">            <!-- Standard shadow -->
<div class="shadow-lg">         <!-- Large shadow -->
```

### Visibility & State

```html
<div class="hidden">            <!-- Hidden from layout -->
<div class="js-hidden">         <!-- JS-controlled hidden (use for show/hide) -->
<div class="sr-only">           <!-- Screen reader only -->
```

---

## Component Patterns

### Buttons

```html
<!-- Primary button (main action) -->
<button type="button" class="btn btn-primary">
    {{ icon('plus', size='18') }}
    Create Item
</button>

<!-- Secondary button (secondary action) -->
<button type="button" class="btn btn-secondary">
    {{ icon('x', size='18') }}
    Cancel
</button>

<!-- Danger button (destructive action) -->
<button type="button" class="btn btn-danger">
    {{ icon('trash-2', size='18') }}
    Delete
</button>

<!-- Ghost button (tertiary/subtle action) -->
<button type="button" class="btn btn-ghost">
    {{ icon('refresh-cw', size='18') }}
    Refresh
</button>

<!-- Icon-only button (standard) -->
<button type="button" class="btn-icon" title="Action name" aria-label="Action name">
    {{ icon('settings', size='18') }}
</button>

<!-- Icon-only button (primary variant) -->
<button class="btn-icon btn-icon-primary" onclick="doAction()" title="Add Item" aria-label="Add item">
    {{ icon('plus', size='18') }}
</button>

<!-- Button sizes -->
<button class="btn btn-primary btn-sm">Small</button>
<button class="btn btn-primary">Default</button>
<button class="btn btn-primary btn-lg">Large</button>
```

**Note:** SVGs inside `.btn` are automatically sized to 16x16px with margin-right via `buttons.css`. No inline styles needed.

### Alerts

```html
<!-- Error/Danger alert -->
<div class="alert alert-error mb-4">
    {{ icon('alert-circle', size='20') }}
    <div>Error message here</div>
</div>

<!-- Success alert -->
<div class="alert alert-success mb-4">
    {{ icon('check-circle', size='20') }}
    <div>Success message here</div>
</div>

<!-- Warning alert -->
<div class="alert alert-warning mb-4">
    {{ icon('alert-triangle', size='20') }}
    <div>Warning message here</div>
</div>

<!-- Info alert -->
<div class="alert alert-info mb-4">
    {{ icon('info', size='20') }}
    <div>Information message here</div>
</div>

<!-- Flash message pattern (from context) -->
{% if flash_message %}
<div class="alert alert-{{ flash_type }} mb-4">
    {{ flash_message }}
</div>
{% endif %}
```

### Cards

```html
<!-- Standard card -->
<div class="card">
    <div class="card-header">
        <div class="card-header-left">
            <h3 class="card-title">
                {{ icon('database', size='18', class='icon-sm') }}
                Card Title
            </h3>
        </div>
        <div class="card-actions">
            <button class="btn btn-ghost btn-sm">Action</button>
        </div>
    </div>
    <div class="card-body">
        Content here
    </div>
</div>

<!-- Card with no padding body (for tables) -->
<div class="card">
    <div class="card-header">
        <h3 class="card-title">Table Card</h3>
    </div>
    <div class="card-body no-padding">
        <table>...</table>
    </div>
</div>

<!-- Admin stat cards (for stats rows) -->
<div class="admin-stats-row">
    <div class="admin-stat-card">
        <div class="admin-stat-label">Total Records</div>
        <div class="admin-stat-value" id="stat-total">42</div>
    </div>
    <div class="admin-stat-card">
        <div class="admin-stat-label">Completed</div>
        <div class="admin-stat-value text-success" id="stat-complete">38</div>
    </div>
    <div class="admin-stat-card">
        <div class="admin-stat-label">Failed</div>
        <div class="admin-stat-value text-danger" id="stat-failed">4</div>
    </div>
</div>

<!-- Stat card (dashboard style) -->
<div class="stat-card">
    <div class="stat-icon stat-icon-primary">
        {{ icon('activity', size='24') }}
    </div>
    <div class="stat-content">
        <div class="stat-value">42</div>
        <div class="stat-label">Active Items</div>
    </div>
</div>
```

### Status Bar (Page Header Stats)

```html
<div class="status-bar">
    <span class="status-item" title="Total Items">
        {{ icon('database', size='16') }}
        <span class="status-count" id="stat-total">{{ stats.total }}</span>
        <span class="status-label">total</span>
    </span>
    <span class="status-divider"></span>
    <span class="status-item status-enabled" title="Enabled">
        {{ icon('check', size='16') }}
        <span class="status-count" id="stat-enabled">{{ stats.enabled }}</span>
        <span class="status-label">enabled</span>
    </span>
    <span class="status-divider"></span>
    <span class="status-item status-active" title="Active">
        {{ icon('refresh-cw', size='16') }}
        <span class="status-count">{{ stats.active }}</span>
        <span class="status-label">active</span>
    </span>
</div>
```

### Form Groups

```html
<div class="form-group">
    <label for="field-name" class="form-label">Field Label</label>
    <input type="text" id="field-name" name="field_name" class="form-input" placeholder="Enter value">
    <p class="form-hint">Helper text explaining the field</p>
</div>

<!-- Select -->
<div class="form-group">
    <label for="select-field" class="form-label">Select Label</label>
    <select id="select-field" name="select_field" class="form-select">
        <option value="">Choose option...</option>
        <option value="1">Option 1</option>
        <option value="2">Option 2</option>
    </select>
</div>

<!-- Checkbox -->
<div class="form-group">
    <label class="form-checkbox">
        <input type="checkbox" name="checkbox_field">
        <span>Checkbox label</span>
    </label>
</div>

<!-- Small number input -->
<div class="form-group">
    <label for="days" class="form-label">Retention Days</label>
    <input type="number" id="days" name="days" value="30" min="1" 
           class="form-input max-w-input-sm">
</div>
```

### Form Actions

```html
<div class="form-actions">
    <button type="submit" class="btn btn-primary">
        {{ icon('save', size='16') }}
        Save Changes
    </button>
    <a href="{{ url_for('previous_page') }}" class="btn btn-ghost">Cancel</a>
</div>
```

### Badges

```html
<!-- Status badges -->
<span class="badge badge-queued">
    <span class="badge-dot"></span>
    Queued
</span>

<span class="badge badge-running">
    <span class="badge-dot"></span>
    Running
</span>

<span class="badge badge-complete">
    <span class="badge-dot"></span>
    Complete
</span>

<span class="badge badge-failed">
    <span class="badge-dot"></span>
    Failed
</span>

<!-- Role badges -->
<span class="role-badge admin">Admin</span>
<span class="role-badge manager">Manager</span>
<span class="role-badge user">User</span>
```

### Tables

```html
<div class="table-container">
    <table>
        <thead>
            <tr>
                <th>Column 1</th>
                <th>Column 2</th>
                <th class="text-right">Actions</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Value 1</td>
                <td>Value 2</td>
                <td class="text-right">
                    <button class="btn-icon" title="Edit" aria-label="Edit">
                        {{ icon('edit-2', size='16') }}
                    </button>
                </td>
            </tr>
        </tbody>
    </table>
</div>
```

### Empty State

```html
<div class="empty-state">
    <div class="empty-state-icon">
        {{ icon('inbox', size='48', class='icon-muted') }}
    </div>
    <h3 class="empty-state-title">No items found</h3>
    <p class="empty-state-description">Create your first item to get started.</p>
    <div class="empty-state-action">
        <a href="{{ url_for('create_item') }}" class="btn btn-primary">
            {{ icon('plus', size='18') }}
            Create Item
        </a>
    </div>
</div>
```

### Error State

```html
<div class="error-state">
    <div class="error-state-icon">
        {{ icon('alert-circle', size='48', class='text-error') }}
    </div>
    <h3 class="error-state-title">Failed to load data</h3>
    <p class="error-state-description">{{ error_message }}</p>
    <div class="error-state-action">
        <button class="btn btn-primary" onclick="location.reload()">
            {{ icon('refresh', size='18') }} Try Again
        </button>
    </div>
</div>
```

### Info Panels

```html
<!-- Flex layout with icon + description (common pattern) -->
<div class="flex gap-4 items-center justify-between mb-4">
    <div class="flex items-center gap-2">
        {{ icon('info', size='16', class='text-primary') }}
        <span class="text-sm">Information about this section</span>
    </div>
    <button class="btn btn-secondary btn-sm">Action</button>
</div>

<!-- Info callout box -->
<div class="info-callout">
    {{ icon('info', size='20', class='info-callout-icon') }}
    <div class="info-callout-content">
        <strong>Note:</strong> Important information goes here.
    </div>
</div>
```

### Hint Text

```html
<p class="text-muted text-sm mb-3">
    Descriptive hint text explaining the section or form field.
</p>
```

### Back Links

```html
<a href="{{ url_for('parent_page') }}" class="back-link">
    {{ icon('chevron-left', size='16') }}
    Back to Parent
</a>
```

### Loading Spinner

```html
<!-- Standard spinner -->
<span class="loading-spinner"></span>

<!-- Small spinner (in buttons) -->
<span class="loading-spinner loading-spinner--sm"></span>

<!-- Large spinner -->
<span class="loading-spinner loading-spinner--lg"></span>

<!-- Button with loading state -->
<button class="btn btn-primary" disabled>
    <span class="loading-spinner loading-spinner--sm"></span>
    Saving...
</button>
```

### Modals

```html
{% block modals %}
<div id="example-modal" class="modal modal-hidden">
    <div class="modal-backdrop" onclick="closeModal('example-modal')"></div>
    <div class="modal-content">
        <div class="modal-header">
            <h3 class="modal-title flex items-center gap-2">
                {{ icon('settings', size='20', class='icon-md') }}
                Modal Title
            </h3>
            <button type="button" class="modal-close" onclick="closeModal('example-modal')">
                {{ icon('x', size='20') }}
            </button>
        </div>
        <div class="modal-body">
            Modal content here
        </div>
        <div class="modal-footer">
            <button type="button" class="btn btn-ghost" onclick="closeModal('example-modal')">Cancel</button>
            <button type="button" class="btn btn-primary">Confirm</button>
        </div>
    </div>
</div>
{% endblock %}
```

#### Modal Size Variants

```html
<!-- Small (confirmations) - max-width: 400px -->
<div class="modal-content modal__content--sm">

<!-- Default - max-width: 500px -->
<div class="modal-content">

<!-- Wide (forms) - max-width: 600px -->
<div class="modal-content modal__content--wide">

<!-- Large (complex forms) - max-width: 700px -->
<div class="modal-content modal__content--lg">
```

#### Complete Form Modal

```html
{% block modals %}
<div id="add-item-modal" class="modal modal-hidden">
    <div class="modal-content modal__content--wide">
        <div class="modal-header">
            <h3 class="modal-title">
                {{ icon('plus', size='20', class='icon-md') }}
                Add New Item
            </h3>
            <button type="button" class="modal-close" 
                    onclick="closeModal('add-item-modal')"
                    title="Close" aria-label="Close modal">
                {{ icon('x', size='20') }}
            </button>
        </div>
        
        <form id="add-item-form" onsubmit="handleAddItem(event)">
            <div class="modal-body">
                <div class="form-section">
                    <h4 class="form-section-title">Basic Settings</h4>
                    
                    <div class="form-row">
                        <div class="form-group form-group-wide">
                            <label for="item_name" class="form-label required">Name</label>
                            <input type="text" id="item_name" name="item_name" 
                                   class="form-input" required>
                        </div>
                        <div class="form-group form-group-narrow">
                            <label for="item_count" class="form-label">Count</label>
                            <input type="number" id="item_count" name="item_count" 
                                   class="form-input" value="1" min="1">
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label for="item_type" class="form-label">Type</label>
                        <select id="item_type" name="item_type" class="form-select">
                            <option value="default">Default</option>
                            <option value="special">Special</option>
                        </select>
                    </div>
                </div>
            </div>
            
            <div class="modal-footer">
                <button type="button" class="btn btn-ghost" 
                        onclick="closeModal('add-item-modal')">
                    Cancel
                </button>
                <button type="submit" class="btn btn-primary">
                    {{ icon('check', size='18') }}
                    Create Item
                </button>
            </div>
        </form>
    </div>
</div>
{% endblock %}
```

#### Danger Modal (Delete Confirmation)

```html
<div id="delete-modal" class="modal modal-hidden">
    <div class="modal-content modal__content--sm">
        <div class="modal-header modal-header-danger">
            <h3 class="modal-title">
                {{ icon('alert-triangle', size='20') }}
                Delete Item
            </h3>
            <button type="button" class="modal-close" onclick="closeModal('delete-modal')">
                {{ icon('x', size='20') }}
            </button>
        </div>
        <div class="modal-body">
            <p>Are you sure you want to delete <strong id="delete-item-name"></strong>?</p>
            <p class="text-muted text-sm mt-2">This action cannot be undone.</p>
        </div>
        <div class="modal-footer">
            <button type="button" class="btn btn-ghost" onclick="closeModal('delete-modal')">
                Cancel
            </button>
            <button type="button" class="btn btn-danger" onclick="confirmDelete()">
                {{ icon('trash-2', size='18') }}
                Delete
            </button>
        </div>
    </div>
</div>
```

### HTMX Patterns

#### Auto-Refresh Container

```html
<!-- Dashboard auto-refresh -->
<div class="dashboard-container" 
     hx-get="{{ request.url }}" 
     hx-trigger="every {{ refresh_interval }}s" 
     hx-select=".dashboard-container" 
     hx-swap="outerHTML">
    <!-- Content auto-refreshes -->
</div>
```

#### Conditional Polling (Active Jobs)

```html
<div id="job-details" 
     hx-get="{{ request.url.path }}" 
     {% if job.status.value in ['running', 'queued'] %}
     hx-trigger="every 5s"
     {% endif %}
     hx-select="#job-content" 
     hx-swap="innerHTML" 
     hx-target="#job-content">
    <div id="job-content">
        <!-- Only polls while job is active -->
    </div>
</div>
```

#### Inline Validation

```html
<div class="form-group">
    <label for="alias" class="form-label required">Alias</label>
    <div class="input-with-status">
        <input type="text" id="alias" name="alias" class="form-input"
               hx-post="/web/admin/check-alias"
               hx-trigger="blur changed delay:300ms"
               hx-target="#alias-status"
               hx-swap="innerHTML">
        <span id="alias-status" class="input-status"></span>
    </div>
</div>
```

#### Load More Pagination

```html
<div id="items-container">
    <!-- Items here -->
</div>
<button class="btn btn-secondary"
        hx-get="/api/items?page={{ next_page }}"
        hx-target="#items-container"
        hx-swap="beforeend"
        hx-indicator=".load-more-spinner">
    <span class="load-more-spinner loading-spinner loading-spinner--sm hidden"></span>
    Load More
</button>
```

---

## Animation & Loading

### Loading Spinners

```html
<!-- Default size (14px) -->
<span class="loading-spinner"></span>

<!-- Small (12px) - for buttons -->
<span class="loading-spinner loading-spinner--sm"></span>

<!-- Large (20px) -->
<span class="loading-spinner loading-spinner--lg"></span>

<!-- Button with loading state -->
<button class="btn btn-primary" disabled>
    <span class="loading-spinner loading-spinner--sm"></span>
    Saving...
</button>
```

### Animation Utilities

```html
<!-- Spinning (for icons/spinners) -->
<span class="animate-spin">{{ icon('loader', size='18') }}</span>

<!-- Pulsing (for loading states) -->
<div class="animate-pulse">Loading...</div>

<!-- Fade in (on mount) -->
<div class="animate-fade-in">Content</div>
```

### Transition Utilities

```html
<!-- Default transition (200ms) -->
<div class="transition">Smooth changes</div>

<!-- Fast transition (150ms) -->
<button class="transition-fast">Quick hover</button>

<!-- Slow transition (300ms) -->
<div class="transition-slow">Deliberate animation</div>

<!-- No transition -->
<div class="transition-none">Instant change</div>
```

---

## Accessibility Patterns

### Required Attributes

```html
<!-- Icon-only buttons MUST have both -->
<button class="btn-icon" title="Delete item" aria-label="Delete item">
    {{ icon('trash-2', size='18') }}
</button>

<!-- Form inputs MUST have labels -->
<label for="db-name" class="form-label">Database Name</label>
<input type="text" id="db-name" name="db_name" class="form-input">

<!-- Hint text uses aria-describedby -->
<input type="text" id="db-name" aria-describedby="db-hint">
<p id="db-hint" class="form-hint">Target database for restore</p>
```

### Screen Reader Utilities

```html
<!-- Visually hidden but accessible -->
<span class="sr-only">Additional context for screen readers</span>

<!-- Skip link (in base.html) -->
<a href="#main-content" class="skip-link">Skip to main content</a>
```

### Color + Text Pattern

```html
<!-- ✅ GOOD: Color AND text indicator -->
<span class="badge badge-failed">
    <span class="badge-dot"></span>
    Failed
</span>

<!-- ❌ BAD: Color only -->
<span class="badge badge-failed">
    <span class="badge-dot"></span>
</span>
```

### Toast Accessibility

```html
<!-- Toasts should have role="alert" for screen readers -->
<div class="toast toast-success" role="alert">
    Settings saved successfully
</div>
```

### Keyboard Navigation

```html
<!-- All interactive elements must be focusable -->
<!-- Focus styles are automatic via :focus-visible in reset.css -->

<!-- Modal close on Escape (handled in JS) -->
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});
```

---

## Inline Style Rules

### ✅ ALLOWED Inline Styles

Only these scenarios justify inline styles:

1. **Dynamic JavaScript values:**
   ```javascript
   element.style.cursor = row.locked ? 'not-allowed' : 'pointer';
   ```

2. **Style guide color swatches** (demonstration purposes):
   ```html
   <div class="swatch" style="background-color: var(--primary-500);"></div>
   ```

3. **Truly unique one-off measurements** with no reuse potential

### ❌ NEVER Use Inline Styles For

| Inline Style | Use Instead |
|-------------|-------------|
| `style="display: flex"` | `class="flex"` |
| `style="margin-bottom: 16px"` | `class="mb-4"` |
| `style="margin-top: 16px"` | `class="mt-4"` |
| `style="margin-left: 8px"` | `class="ml-2"` |
| `style="color: var(--gray-500)"` | `class="text-muted"` |
| `style="font-size: 14px"` | `class="text-sm"` |
| `style="width: 16px; height: 16px"` on SVG | `class="icon-sm"` |
| `style="width: 20px; height: 20px"` on SVG | `class="icon-md"` |
| `style="max-width: 100px"` on input | `class="max-w-input-sm"` |
| `style="display: none"` for JS toggle | `class="js-hidden"` |

### Special Case: Buttons with Icons

Buttons using `.btn` class automatically size inline SVGs. **Do not add size styles:**

```html
<!-- ✅ CORRECT: Let buttons.css handle icon sizing -->
<button class="btn btn-primary">
    {{ icon('plus', size='16') }}
    Add Item
</button>

<!-- ❌ WRONG: Redundant inline styles -->
<button class="btn btn-primary">
    <svg style="width: 16px; height: 16px">...</svg>
    Add Item
</button>
```

---

## JavaScript Patterns

### DOMContentLoaded Initialization

```javascript
document.addEventListener('DOMContentLoaded', function() {
    initializePage();
});

function initializePage() {
    // Setup event listeners
    // Initialize components
}
```

### Global Functions (Available Everywhere)

These are defined in `static/js/main.js` and available globally:

#### showToast() - User Feedback

```javascript
// Signature: showToast(message, type = 'info')
// Types: 'info', 'success', 'warning', 'error'
// Auto-dismiss: info=5s, success=4s, warning=10s, error=60s

showToast('Settings saved', 'success');
showToast('Check your input', 'warning');
showToast(`Error: ${error.message}`, 'error');
```

#### showConfirm() - Themed Confirmation Dialog

```javascript
// Signature: showConfirm(message, options = {}) → Promise<boolean>
// Options: title, okText, type ('default'|'danger'|'warning')

// Basic
const confirmed = await showConfirm('Are you sure?');
if (!confirmed) return;

// Danger confirmation (red header/button)
const confirmed = await showConfirm(
    'Delete this user? This cannot be undone.',
    { title: 'Delete User', okText: 'Delete', type: 'danger' }
);
```

#### showValidationSummary() - Multiple Errors

```javascript
// Signature: showValidationSummary(errors, title)
showValidationSummary([
    'Username is required',
    'Password must be 8+ characters'
]);
```

### DateTime Formatting

UTC timestamps are converted to local time via `local-datetime.js`:

#### HTML (Auto-converts on page load)

```html
<!-- Basic: "Jan 15, 2026 3:45 PM" -->
<time data-utc="{{ job.created_at.isoformat() }}"></time>

<!-- Date only: "Jan 15, 2026" -->
<time data-utc="{{ job.created_at.isoformat() }}" data-format="date"></time>

<!-- Relative: "2 hours ago" -->
<time data-utc="{{ job.created_at.isoformat() }}" data-format="relative"></time>

<!-- Short: "Jan 15, 3:45 PM" -->
<time data-utc="{{ job.created_at.isoformat() }}" data-format="short"></time>
```

#### JavaScript API

```javascript
// Manual conversion after dynamic content
LocalDateTime.convert(document.querySelector('time[data-utc]'));

// Convert all on page
LocalDateTime.initAll();

// Format a Date object
LocalDateTime.format(new Date(), 'relative');  // "just now"
```

### Modal Functions

```javascript
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('modal-hidden');
        document.body.style.overflow = 'hidden';
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('modal-hidden');
        document.body.style.overflow = '';
    }
}
```

### Lazy Table Column Renderers

```javascript
// Standard text cell
const renderText = (val, row) => {
    return `<span class="cell-primary">${val || '-'}</span>`;
};

// Muted/secondary text
const renderMuted = (val, row) => {
    return val ? val : `<span class="text-muted">—</span>`;
};

// Size with null handling
const renderSize = (val, row) => {
    return val !== null 
        ? formatBytes(val) 
        : `<span class="text-muted">—</span>`;
};

// Monospace values (IDs, codes)
const renderCode = (val, row) => {
    return `<span class="font-mono text-sm">${val}</span>`;
};
```

---

## Checklist

Before submitting a new page, verify:

### Structure
- [ ] Extends `base.html`
- [ ] Has proper `{% block title %}` with convention: `Page - Section - pullDB`
- [ ] Has `{% block page_id %}` with convention: `section-feature`
- [ ] Has `{% block header_title %}` for app header
- [ ] Uses `{% block content %}` for main content
- [ ] Content wrapped in feature-specific div (e.g., `<div class="admin-page">`)
- [ ] Page header uses `page-header-row` with `page-header-left`
- [ ] Modals are in `{% block modals %}` (outside main content)

### Styling
- [ ] **NO inline styles** where utility classes exist
- [ ] Uses utility classes for spacing (`mb-4`, `mt-4`, `gap-4`, etc.)
- [ ] Uses utility classes for text (`text-muted`, `text-sm`, `font-mono`)
- [ ] Uses icon size classes via macro (`class='icon-sm'`)
- [ ] Button icons have no inline size styles (`.btn` handles it)
- [ ] Number inputs use `max-w-input-*` classes

### Icons
- [ ] Uses `{{ icon('name', size='20') }}` macro, not raw SVG
- [ ] Icon sizes: 16 for inline, 18 for buttons, 20 for default, 24 for large
- [ ] Pass `class` parameter for styling (e.g., `class='icon-sm'`)

### Components
- [ ] Alerts use `mb-4` class (not inline margin)
- [ ] Cards use `card-header > card-header-left > h3.card-title` structure
- [ ] Icon-only buttons have `title` AND `aria-label` attributes
- [ ] Forms use `form-group > form-label + form-input` structure
- [ ] Action buttons wrapped in `form-actions`

### Accessibility
- [ ] All images have `alt` text
- [ ] All icon-only buttons have `title` and `aria-label` attributes
- [ ] Form inputs have associated `<label>` elements
- [ ] Color is not the only indicator of state

### Dark Mode
- [ ] Uses CSS custom properties for colors (not hardcoded)
- [ ] Tested in both light and dark themes

---

## Quick Reference Card

```
SPACING           ICON MACRO                TEXT
─────────────     ──────────────────────    ─────────────
mb-2  = 8px      size='16' (inline)        text-xs = 12px
mb-3  = 12px     size='18' (buttons)       text-sm = 14px
mb-4  = 16px     size='20' (default)       text-base = 16px
mb-6  = 24px     size='24' (large)         text-lg = 18px
gap-4 = 16px     size='32' (extra large)   text-muted = gray

ICON CLASSES      FLEX               BUTTONS
─────────────     ─────────────      ─────────────
icon-xs = 12px   flex               btn btn-primary
icon-sm = 16px   items-center       btn btn-secondary
icon-md = 20px   justify-between    btn btn-danger
icon-lg = 24px   gap-4              btn btn-ghost
icon-xl = 32px   flex-col           btn-icon

INPUTS            PAGE STRUCTURE
─────────────     ─────────────────────────────────────
max-w-input-xs    page-header-row > page-header-left
max-w-input-sm    card > card-header > card-header-left
max-w-input-md    admin-stats-row > admin-stat-card
max-w-input-lg    status-bar > status-item
```

---

## Related Documentation

- [STYLE-GUIDE.md](STYLE-GUIDE.md) - Complete design system reference
- [utilities.css](../pulldb/web/shared/css/utilities.css) - All utility classes
- [buttons.css](../pulldb/web/static/css/features/buttons.css) - Button component
- [HCA Standards](../.pulldb/standards/hca.md) - File organization

---

*Template maintained by pullDB development team. Updated: January 2026*
