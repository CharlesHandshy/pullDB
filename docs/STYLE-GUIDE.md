# pullDB Web UI Style Guide

> **Version**: 1.2.0  
> **Last Updated**: January 4, 2026  
> **Status**: Stable

This document establishes the design system and style standards for the pullDB web interface. It serves as the single source of truth for UI consistency.

---

## Table of Contents

1. [Design Philosophy](#design-philosophy)
2. [Color System](#color-system)
3. [Typography](#typography)
4. [Spacing & Layout](#spacing--layout)
5. [Components](#components)
6. [Patterns](#patterns)
7. [Icon System](#icon-system)
8. [Dark Mode](#dark-mode)
9. [Accessibility](#accessibility)
10. [Browser Support & CSS Strategy](#browser-support--css-strategy)
11. [Implementation Status](#implementation-status)

---

## Design Philosophy

### Guiding Principles

pullDB is an **internal operations tool** for database restore management. The UI should prioritize:

| Principle | Rationale | Application |
|-----------|-----------|-------------|
| **Clarity over Cleverness** | Users need fast, accurate information | Clear status badges, readable tables |
| **Efficiency over Aesthetics** | Power users need speed | Keyboard shortcuts, minimal clicks |
| **Consistency over Creativity** | Reduce cognitive load | Same patterns everywhere |
| **Information Density** | Show what matters | Progressive disclosure |

### UX Laws Applied

Based on [Laws of UX](https://lawsofux.com/) and [Nielsen's Heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/):

#### 1. Visibility of System Status
> "Keep users informed through appropriate feedback"

**Implementation:**
- Live update indicators (green pulsing dot)
- Job status badges with color coding
- Progress indicators during long operations
- Simulation mode banner when active

#### 2. Doherty Threshold
> "Productivity soars when response time < 400ms"

**Implementation:**
- All transitions: 150-300ms
- HTMX for instant UI updates
- Skeleton loading states (planned)

#### 3. Hick's Law
> "Decision time increases with number of choices"

**Implementation:**
- Maximum 4 stat cards on dashboard
- 7±2 navigation items per section
- Progressive disclosure for advanced options

#### 4. Fitts's Law
> "Time to target = f(distance, size)"

**Implementation:**
- Minimum button size: 32px (icon buttons)
- Primary actions: 40px+ height
- Adequate spacing between clickable elements

#### 5. Jakob's Law
> "Users prefer familiar patterns"

**Implementation:**
- Standard sidebar navigation
- Card-based dashboard layout
- Conventional form patterns

#### 6. Law of Common Region
> "Elements in bounded areas are perceived as grouped"

**Implementation:**
- Cards for logical groupings
- Bordered sections in forms
- Visual separation between nav sections

#### 7. Von Restorff Effect
> "Different items stand out and are remembered"

**Implementation:**
- Status badges use distinct colors
- Running jobs have animated indicators
- Error states use red with icons

---

## Color System

### Brand Colors

```css
/* Primary - Blue */
--primary-50:  #eff6ff;   /* Backgrounds */
--primary-100: #dbeafe;   /* Light fills */
--primary-200: #bfdbfe;   /* Borders */
--primary-300: #93c5fd;   /* Hover states */
--primary-400: #60a5fa;   /* Icons */
--primary-500: #3b82f6;   /* Main brand color */
--primary-600: #2563eb;   /* Primary buttons */
--primary-700: #1d4ed8;   /* Hover on primary */
--primary-800: #1e40af;   /* Dark accents */
--primary-900: #1e3a8a;   /* Text on light */
```

### Semantic Colors

#### Success (Green)
```css
--success-50:  #f0fdf4;   /* Background */
--success-100: #dcfce7;   /* Light fill */
--success-500: #22c55e;   /* Main */
--success-600: #16a34a;   /* Hover */
--success-700: #15803d;   /* Text */
```

**Usage:** Completed jobs, enabled states, positive actions

#### Warning (Amber)
```css
--warning-50:  #fffbeb;   /* Background */
--warning-100: #fef3c7;   /* Light fill */
--warning-500: #f59e0b;   /* Main */
--warning-600: #d97706;   /* Hover */
```

**Usage:** Canceled jobs, caution states, simulation mode

#### Danger (Red)
```css
--danger-50:  #fef2f2;    /* Background */
--danger-100: #fee2e2;    /* Light fill */
--danger-500: #ef4444;    /* Main */
--danger-600: #dc2626;    /* Hover */
--danger-700: #b91c1c;    /* Text */
```

**Usage:** Failed jobs, errors, destructive actions

#### Info (Cyan)
```css
--info-50:  #ecfeff;
--info-100: #cffafe;
--info-500: #06b6d4;
--info-600: #0891b2;
```

**Usage:** Informational callouts, help text, neutral highlights

### Neutral Grays

```css
--gray-25:  #fcfcfd;   /* Subtle background */
--gray-50:  #f9fafb;   /* Page background */
--gray-100: #f3f4f6;   /* Card hover */
--gray-200: #e5e7eb;   /* Borders */
--gray-300: #d1d5db;   /* Disabled borders */
--gray-400: #9ca3af;   /* Placeholder text */
--gray-500: #6b7280;   /* Secondary text */
--gray-600: #4b5563;   /* Body text */
--gray-700: #374151;   /* Headings */
--gray-800: #1f2937;   /* Sidebar background */
--gray-900: #111827;   /* Primary text */
--gray-950: #030712;   /* Near black */
```

### Status Color Mapping

| Status | Background | Text | Dot/Icon |
|--------|------------|------|----------|
| **Queued** | `gray-100` | `gray-700` | `gray-500` |
| **Running** | `primary-100` | `primary-700` | `primary-500` (animated) |
| **Complete** | `success-100` | `success-700` | `success-500` |
| **Failed** | `danger-100` | `danger-700` | `danger-500` |
| **Canceled** | `warning-100` | `warning-700` | `warning-500` |

### Color Usage Rules

1. **Never use color alone** to convey meaning (accessibility)
2. **Pair color with icons** for status indication
3. **Use 100-level backgrounds** for badges and callouts
4. **Use 600-700 level** for text on light backgrounds
5. **Maintain 4.5:1 contrast** minimum for body text

---

## Typography

### Font Stack

```css
/* Sans-serif - UI text */
--font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;

/* Monospace - Code, IDs, technical values */
--font-mono: 'JetBrains Mono', ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace;
```

### Type Scale

| Token | Size | Weight | Line Height | Usage |
|-------|------|--------|-------------|-------|
| `--text-page-title` | 1.125rem (18px) | 700 | 1.2 | Page headers |
| `--text-card-title` | 1rem (16px) | 600 | 1.3 | Card headers |
| `--text-section-title` | 0.6875rem (11px) | 600 | 1.2 | Section labels (uppercase) |
| `--text-body` | 0.9375rem (15px) | 400 | 1.6 | Body text |
| `--text-small` | 0.8125rem (13px) | 400 | 1.5 | Secondary text |
| `--text-micro` | 0.75rem (12px) | 500 | 1.4 | Badges, timestamps |
| `--text-code` | 0.8125rem (13px) | 400 | 1.5 | Monospace content |

### Typography Rules

```css
/* Page Title */
.page-title {
    font-size: 1.125rem;
    font-weight: 700;
    color: var(--gray-900);
    letter-spacing: -0.025em;
    line-height: 1.2;
}

/* Section Labels (uppercase) */
.section-title {
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--gray-500);
}

/* Body Text */
body {
    font-family: var(--font-sans);
    font-size: 0.9375rem;
    line-height: 1.6;
    color: var(--gray-900);
}

/* Monospace (IDs, codes) */
.font-mono {
    font-family: var(--font-mono);
    font-size: 0.8125rem;
}
```

### Typography Guidelines

1. **Use Inter** for all UI text
2. **Use JetBrains Mono** for:
   - Job IDs
   - User codes
   - Database names
   - Technical values
3. **Limit heading levels** to 3 max (page, card, section)
4. **Avoid bold for emphasis** in body text - use color or icons instead

---

## Spacing & Layout

### Spacing Scale

Based on 4px increments:

```css
--space-1:  0.25rem;   /*  4px */
--space-2:  0.5rem;    /*  8px */
--space-3:  0.75rem;   /* 12px */
--space-4:  1rem;      /* 16px */
--space-5:  1.25rem;   /* 20px */
--space-6:  1.5rem;    /* 24px */
--space-8:  2rem;      /* 32px */
--space-10: 2.5rem;    /* 40px */
--space-12: 3rem;      /* 48px */
--space-16: 4rem;      /* 64px */
```

### Spacing Application

| Context | Token | Pixels |
|---------|-------|--------|
| Button padding (y) | `space-2` to `space-3` | 8-12px |
| Button padding (x) | `space-4` | 16px |
| Card padding | `space-6` | 24px |
| Section margin | `space-8` | 32px |
| Gap between cards | `space-4` | 16px |
| Table cell padding | `space-2` to `space-3` | 8-12px |
| Form field margin | `space-5` | 20px |

### Border Radius

```css
--radius-sm:   0.375rem;  /*  6px - inputs, small buttons */
--radius-md:   0.5rem;    /*  8px - buttons, badges */
--radius-lg:   0.75rem;   /* 12px - cards, dropdowns */
--radius-xl:   1rem;      /* 16px - main cards */
--radius-2xl:  1.5rem;    /* 24px - modals */
--radius-full: 9999px;    /* Pills, avatars */
```

### Layout Structure

```
┌─────────────────────────────────────────────────────────────┐
│ 3px │ Page Header (56px)                        │ User Info │
│ strip├──────────────────────────────────────────┴───────────┤
│     │                                                       │
│     │  ┌─────────────────────────────────────────────────┐ │
│     │  │ Content Body (scrollable)                       │ │
│     │  │                                                 │ │
│     │  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐ │ │
│     │  │  │ Stat    │ │ Stat    │ │ Stat    │ │ Stat  │ │ │
│     │  │  │ Card    │ │ Card    │ │ Card    │ │ Card  │ │ │
│     │  │  └─────────┘ └─────────┘ └─────────┘ └───────┘ │ │
│     │  │                                                 │ │
│     │  │  ┌───────────────────────────────────────────┐ │ │
│     │  │  │ Data Table                                │ │ │
│ Hover│  │  │                                          │ │ │
│ Nav  │  │  │                                          │ │ │
│     │  │  └───────────────────────────────────────────┘ │ │
│     │  └─────────────────────────────────────────────────┘ │
│     ├───────────────────────────────────────────────────────┤
│     │ Footer                                                │
└─────┴───────────────────────────────────────────────────────┘
```

### Grid Specifications

```css
/* Stats Grid */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-4);
}

/* Admin Sections Grid */
.admin-sections-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: var(--space-4);
}

/* Form Layout */
.form-card {
    max-width: 560px;  /* ~65 characters for readability */
    margin: 0 auto;
}
```

---

## Components

### Buttons

#### Primary Button
```css
.btn-primary {
    background: var(--primary-600);
    color: white;
    padding: 0.625rem 1rem;
    border-radius: var(--radius-md);
    font-size: 0.875rem;
    font-weight: 500;
    transition: background var(--transition-fast);
}

.btn-primary:hover {
    background: var(--primary-700);
}

.btn-primary:focus {
    outline: none;
    box-shadow: 0 0 0 3px var(--primary-100);
}
```

#### Button Variants

| Variant | Background | Text | Border | Use Case |
|---------|------------|------|--------|----------|
| `btn-primary` | `primary-600` | white | none | Main actions |
| `btn-secondary` | white | `gray-700` | `gray-300` | Secondary actions |
| `btn-ghost` | transparent | `gray-600` | none | Tertiary actions |
| `btn-danger` | `danger-600` | white | none | Destructive actions |
| `btn-outline-primary` | transparent | `primary-600` | `primary-300` | Alternative primary |
| `btn-outline-danger` | transparent | `danger-600` | `danger-300` | Soft destructive |

#### Button Sizes

| Size | Padding | Font Size | Height |
|------|---------|-----------|--------|
| `btn-sm` | 6px 12px | 13px | ~30px |
| `btn` (default) | 10px 16px | 14px | ~40px |
| `btn-lg` | 12px 24px | 16px | ~48px |

#### Icon Buttons
```css
.btn-icon {
    width: 32px;
    height: 32px;
    padding: 0;
    border-radius: var(--radius-md);
}

.btn-icon svg {
    width: 18px;
    height: 18px;
}
```

### Cards

#### Standard Card
```css
.card {
    background: white;
    border: 1px solid var(--gray-200);
    border-radius: var(--radius-xl);
    overflow: hidden;
}

.card-header {
    padding: var(--space-5) var(--space-6);
    border-bottom: 1px solid var(--gray-100);
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.card-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--gray-900);
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.card-body {
    padding: var(--space-6);
}
```

#### Stat Card
```html
<div class="stat-card">
    <div class="stat-icon stat-icon-primary">
        <svg><!-- icon --></svg>
    </div>
    <div class="stat-content">
        <div class="stat-value">42</div>
        <div class="stat-label">Active Jobs</div>
    </div>
</div>
```

```css
.stat-card {
    background: white;
    border: 1px solid var(--gray-200);
    border-radius: var(--radius-xl);
    padding: var(--space-6);
    display: flex;
    align-items: flex-start;
    gap: var(--space-4);
    transition: all var(--transition-base);
}

.stat-card:hover {
    box-shadow: var(--shadow-md);
    border-color: var(--gray-300);
}

.stat-icon {
    width: 48px;
    height: 48px;
    border-radius: var(--radius-lg);
    display: flex;
    align-items: center;
    justify-content: center;
}

.stat-icon svg {
    width: 24px;
    height: 24px;
}

.stat-icon-primary { background: var(--primary-100); color: var(--primary-600); }
.stat-icon-success { background: var(--success-100); color: var(--success-600); }
.stat-icon-warning { background: var(--warning-100); color: var(--warning-600); }
.stat-icon-danger  { background: var(--danger-100);  color: var(--danger-600); }
.stat-icon-info    { background: var(--primary-100); color: var(--primary-600); }

.stat-value {
    font-size: 2rem;
    font-weight: 700;
    color: var(--gray-900);
    line-height: 1.2;
    letter-spacing: -0.025em;
}

.stat-label {
    font-size: 0.875rem;
    color: var(--gray-500);
    font-weight: 500;
}
```

#### Form Card
```html
<div class="form-card">
    <div class="form-card-header">
        <div class="form-card-icon">
            <svg><!-- contextual icon --></svg>
        </div>
        <h2 class="form-card-title">Create User</h2>
    </div>
    <div class="form-card-body">
        <!-- form content -->
    </div>
</div>
```

```css
.form-card {
    background: white;
    border: 1px solid var(--gray-200);
    border-radius: var(--radius-xl);
    overflow: hidden;
    max-width: 560px;
    margin: 0 auto;
}

.form-card-header {
    padding: var(--space-5) var(--space-6);
    background: linear-gradient(135deg, var(--primary-50) 0%, var(--primary-100) 100%);
    border-bottom: 1px solid var(--gray-200);
    display: flex;
    align-items: center;
    gap: var(--space-4);
}

.form-card-icon {
    width: 48px;
    height: 48px;
    border-radius: var(--radius-lg);
    background: white;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--primary-600);
    box-shadow: var(--shadow-sm);
}

.form-card-icon svg {
    width: 24px;
    height: 24px;
}

.form-card-title {
    font-size: 1.125rem;
    font-weight: 600;
    margin: 0;
    color: var(--gray-900);
}

.form-card-body {
    padding: var(--space-6);
}
```

### Badges

#### Status Badge
```html
<span class="badge badge-{{ status }}">
    <span class="badge-dot"></span>
    {{ status | capitalize }}
</span>
```

```css
.badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-1);
    padding: 0.25rem 0.625rem;
    border-radius: var(--radius-full);
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: capitalize;
    white-space: nowrap;
    min-width: 90px;
}

.badge-dot {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-full);
}

/* Status variants */
.badge-queued  { background: var(--gray-100);    color: var(--gray-700); }
.badge-running { background: var(--primary-100); color: var(--primary-700); }
.badge-complete { background: var(--success-100); color: var(--success-700); }
.badge-failed  { background: var(--danger-100);  color: var(--danger-700); }
.badge-canceled { background: var(--warning-100); color: var(--warning-700); }

.badge-queued .badge-dot  { background: var(--gray-500); }
.badge-running .badge-dot { background: var(--primary-500); animation: pulse 2s infinite; }
.badge-complete .badge-dot { background: var(--success-500); }
.badge-failed .badge-dot  { background: var(--danger-500); }
.badge-canceled .badge-dot { background: var(--warning-500); }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
```

#### Role Badge
```css
.role-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
}

.role-badge.admin   { background: var(--warning-100); color: var(--warning-700); }
.role-badge.manager { background: var(--info-100);    color: var(--info-700); }
.role-badge.user    { background: var(--gray-100);    color: var(--gray-700); }
```

### Tables

```css
.table-container {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
}

thead {
    background: var(--gray-50);
    border-bottom: 1px solid var(--gray-200);
}

th {
    text-align: left;
    padding: var(--space-2) var(--space-3);
    font-size: 0.6875rem;
    font-weight: 600;
    color: var(--gray-500);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    white-space: nowrap;
}

td {
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--gray-100);
    font-size: 0.8125rem;
    color: var(--gray-700);
}

tr:last-child td {
    border-bottom: none;
}

tbody tr {
    transition: background var(--transition-fast);
}

tbody tr:hover {
    background: var(--gray-50);
}
```

#### Table Cell Standards

**Username columns** in `lazy_table` components display text only—no avatar or monogram elements. This keeps tables scannable and information-dense.

```javascript
// Standard: username columns use text only
const renderUsername = (val, row) => {
    return `<span class="cell-primary">${val || '-'}</span>`;
};
```

> **Rationale:** Avatars/monograms add visual noise without providing actionable information in data tables. Reserve avatars for profile areas (sidebar, user cards) where identity emphasis is appropriate.

### Forms

#### Form Group
```html
<div class="form-group">
    <label for="field" class="form-label">Field Label</label>
    <input type="text" id="field" class="form-input" placeholder="...">
    <p class="form-hint">Helper text goes here</p>
</div>
```

```css
.form-group {
    margin-bottom: var(--space-5);
}

.form-label {
    display: block;
    margin-bottom: var(--space-2);
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--gray-700);
}

.form-input,
.form-select {
    width: 100%;
    padding: var(--space-3) var(--space-4);
    font-size: 0.9375rem;
    border: 1px solid var(--gray-300);
    border-radius: var(--radius-md);
    background: white;
    transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.form-input:focus,
.form-select:focus {
    outline: none;
    border-color: var(--primary-400);
    box-shadow: 0 0 0 3px var(--primary-100);
}

.form-input::placeholder {
    color: var(--gray-400);
}

.form-hint {
    font-size: 0.8125rem;
    color: var(--gray-500);
    margin-top: var(--space-1);
}
```

#### Form Section
```html
<div class="form-section">
    <div class="form-section-title">Section Name</div>
    <!-- form groups -->
</div>
```

```css
.form-section {
    margin-bottom: var(--space-6);
}

.form-section-title {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--gray-500);
    margin-bottom: var(--space-4);
    padding-bottom: var(--space-2);
    border-bottom: 1px solid var(--gray-200);
}
```

### Alerts

```html
<div class="alert alert-{{ type }}">
    <svg><!-- icon --></svg>
    <div>Alert message content</div>
</div>
```

```css
.alert {
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    padding: var(--space-4);
    border-radius: var(--radius-lg);
    margin-bottom: var(--space-4);
}

.alert svg {
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    margin-top: 1px;
}

.alert-error   { background: var(--danger-50);  border: 1px solid var(--danger-200);  color: var(--danger-700); }
.alert-success { background: var(--success-50); border: 1px solid var(--success-200); color: var(--success-700); }
.alert-warning { background: var(--warning-50); border: 1px solid var(--warning-200); color: var(--warning-700); }
.alert-info    { background: var(--primary-50); border: 1px solid var(--primary-200); color: var(--primary-700); }
```

### Info Callout

```html
<div class="info-callout">
    <svg class="info-callout-icon"><!-- info icon --></svg>
    <div class="info-callout-content">
        <strong>Note:</strong> Callout content here.
    </div>
</div>
```

```css
.info-callout {
    display: flex;
    gap: var(--space-3);
    padding: var(--space-4);
    background: var(--primary-50);
    border: 1px solid var(--primary-200);
    border-radius: var(--radius-lg);
}

.info-callout-icon {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    color: var(--primary-600);
}

.info-callout-content {
    font-size: 0.875rem;
    color: var(--primary-800);
    line-height: 1.5;
}
```

### Empty State

```html
<div class="empty-state">
    <svg class="empty-state-icon"><!-- illustration --></svg>
    <h3 class="empty-state-title">No items found</h3>
    <p class="empty-state-text">Description of what to do next.</p>
    <a href="..." class="btn btn-primary">Action</a>
</div>
```

```css
.empty-state {
    text-align: center;
    padding: var(--space-12) var(--space-8);
}

.empty-state-icon {
    width: 64px;
    height: 64px;
    margin: 0 auto var(--space-4);
    color: var(--gray-300);
}

.empty-state-title {
    font-size: 1.125rem;
    font-weight: 600;
    color: var(--gray-700);
    margin-bottom: var(--space-2);
}

.empty-state-text {
    font-size: 0.9375rem;
    color: var(--gray-500);
    max-width: 300px;
    margin: 0 auto var(--space-5);
}
```

---

## Patterns

### Navigation Link Pattern

```html
<a href="/web/..." class="nav-link {% if active %}active{% endif %}">
    <svg><!-- icon --></svg>
    <span>Link Text</span>
    {% if badge %}<span class="nav-badge">{{ badge }}</span>{% endif %}
</a>
```

### Back Link Pattern

```html
<a href="..." class="back-link">
    <svg><!-- chevron-left --></svg>
    Back to Previous
</a>
```

```css
.back-link {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--gray-600);
    text-decoration: none;
    font-size: 0.875rem;
    transition: color var(--transition-fast);
    margin-bottom: var(--space-5);
}

.back-link:hover {
    color: var(--primary-600);
}

.back-link svg {
    width: 16px;
    height: 16px;
}
```

### Action Buttons Pattern

```html
<div class="form-actions">
    <button type="submit" class="btn btn-primary">
        <svg><!-- icon --></svg>
        Primary Action
    </button>
    <a href="..." class="btn btn-secondary">Cancel</a>
</div>
```

```css
.form-actions {
    display: flex;
    gap: var(--space-3);
    padding-top: var(--space-4);
    border-top: 1px solid var(--gray-200);
}
```

### Profile Header Pattern

```html
<div class="profile-header">
    <div class="profile-avatar">{{ initial }}</div>
    <div class="profile-info">
        <h2>{{ name }}</h2>
        <span class="profile-meta">{{ code }}</span>
        <span class="badge">{{ status }}</span>
    </div>
</div>
```

### Toast Notifications

```html
<div class="toast-container">
    <div class="toast toast-success">
        <svg><!-- check icon --></svg>
        <span>Success message here</span>
    </div>
</div>
```

```css
.toast-container {
    position: fixed;
    bottom: var(--space-6);
    right: var(--space-6);
    z-index: 1000;
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
}

.toast {
    background: var(--color-surface, white);
    border: 1px solid var(--color-border, var(--gray-200));
    border-radius: var(--radius-md);
    padding: var(--space-4);
    box-shadow: var(--shadow-md);
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 300px;
    animation: slideIn 0.3s ease-out;
}

.toast-success { border-left: 4px solid var(--success-500); }
.toast-error   { border-left: 4px solid var(--danger-500); }
.toast-info    { border-left: 4px solid var(--primary-500); }
```

### Modal Dialog

```html
<div class="modal">
    <div class="modal-backdrop"></div>
    <div class="modal-content">
        <div class="modal-header">
            <h3 class="modal-title">Modal Title</h3>
            <button class="modal-close" aria-label="Close">
                <svg><!-- x icon --></svg>
            </button>
        </div>
        <div class="modal-body">
            <!-- Content -->
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary">Cancel</button>
            <button class="btn btn-primary">Confirm</button>
        </div>
    </div>
</div>
```

```css
.modal {
    position: fixed;
    inset: 0;
    z-index: 100;
    display: flex;
    align-items: center;
    justify-content: center;
}

.modal-hidden { display: none !important; }

.modal-backdrop {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
}

.modal-content {
    position: relative;
    width: 100%;
    max-width: 480px;
    background: var(--color-surface, white);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-xl);
}

.modal-content-wide { max-width: 640px; }
.modal-content-lg   { max-width: 800px; }
```

### Breadcrumb Navigation

```html
<nav class="breadcrumb-nav">
    <ol class="breadcrumb-list">
        <li class="breadcrumb-item">
            <a href="/" class="breadcrumb-link">Home</a>
        </li>
        <li class="breadcrumb-item">
            <a href="/admin" class="breadcrumb-link">Admin</a>
        </li>
        <li class="breadcrumb-item">
            <span class="breadcrumb-current">Users</span>
        </li>
    </ol>
</nav>
```

```css
.breadcrumb-nav { margin-bottom: var(--space-4); }

.breadcrumb-list {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    list-style: none;
    margin: 0;
    padding: 0;
}

.breadcrumb-item { font-size: 0.875rem; }
.breadcrumb-item:not(:last-child)::after {
    content: "/";
    color: var(--gray-400);
    margin-left: var(--space-2);
}

.breadcrumb-link {
    color: var(--gray-600);
    text-decoration: none;
}
.breadcrumb-link:hover { color: var(--primary-600); }

.breadcrumb-current {
    color: var(--gray-900);
    font-weight: 500;
}
```

---

## Icon System

The pullDB icon system uses a macro-based approach following HCA principles.

### Usage

```jinja2
{% from 'partials/icons/_index.html' import icon %}

{{ icon('database') }}
{{ icon('user', size='24', class='text-muted') }}
{{ icon('check', stroke_width='2') }}
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `name` | (required) | Icon name |
| `size` | `20` | Width/height in pixels |
| `class` | `''` | Additional CSS classes |
| `stroke_width` | `1.5` | SVG stroke width |

### Available Icons by Layer

**Shared** (universal icons):
`chevron-down`, `chevron-left`, `chevron-right`, `chevron-up`, `x`, `check`, `plus`, `minus`, `search`, `menu`, `settings`, `info`, `alert-triangle`, `alert-circle`, `trash`, `edit`, `copy`, `external-link`, `download`, `upload`, `refresh`, `eye`, `eye-off`, `lock`, `unlock`, `home`, `logout`, `arrow-left`, `arrow-right`, `calendar`, `clock`, `filter`, `sort`

**Entities** (domain model icons):
`database`, `server`, `folder`, `file`, `table`

**Features** (business feature icons):
`user`, `users`, `key`, `shield`, `activity`, `terminal`, `zap`

**Widgets** (orchestration icons):
`loader`, `progress`, `chart`

**Pages** (entry-point specific):
`dashboard`, `backup`, `restore`

### Fallback Behavior

Unknown icons display a question mark circle with `data-icon="unknown:name"` attribute for debugging.

---

## Dark Mode

Dark mode is implemented via CSS variables with the `[data-theme="dark"]` selector.

### Activation

Dark mode is controlled by three mechanisms (in priority order):

1. **User localStorage** - Explicit user choice persists across sessions
2. **Admin Default** - Server-configurable default via `data-admin-theme-default` attribute
3. **System Preference** - Falls back to `prefers-color-scheme: dark`

### Theme Toggle

```html
<button class="theme-toggle" aria-label="Toggle theme">
    {{ icon('sun', class='theme-icon-light') }}
    {{ icon('moon', class='theme-icon-dark') }}
</button>
```

### Key CSS Variables

Dark mode overrides these semantic variables in `dark-mode.css`:

```css
[data-theme="dark"] {
    /* Surfaces */
    --color-surface: #1f2937;
    --color-surface-elevated: #374151;
    
    /* Text */
    --color-text: #f9fafb;
    --color-text-muted: #9ca3af;
    
    /* Borders */
    --color-border: #4b5563;
    
    /* Gray scale adjustments */
    --gray-50: #1f2937;
    --gray-100: #374151;
    --gray-900: #f9fafb;
}
```

### Component Support

All major components support dark mode through CSS variable fallbacks:
- Cards, modals, dropdowns use `var(--color-surface, white)`
- Borders use `var(--color-border, var(--gray-200))`
- Form inputs, toasts, and tables adapt automatically

---

## Accessibility

### Focus States

All interactive elements must have visible focus states:

```css
/* Default focus ring */
:focus-visible {
    outline: 2px solid var(--primary-500);
    outline-offset: 2px;
}

/* Form inputs - use box-shadow instead */
.form-input:focus,
.form-select:focus {
    outline: none;
    border-color: var(--primary-400);
    box-shadow: 0 0 0 3px var(--primary-100);
}
```

### Color Contrast Requirements

| Element | Minimum Ratio | Target |
|---------|---------------|--------|
| Body text | 4.5:1 | ✓ `gray-900` on white |
| Secondary text | 4.5:1 | ✓ `gray-600` on white |
| Placeholder text | 3:1 | ⚠️ `gray-400` may need review |
| Button text | 4.5:1 | ✓ white on `primary-600` |

### Keyboard Navigation

- All interactive elements must be reachable via Tab
- Logical tab order follows visual order
- Skip links for main content (planned)
- Escape closes modals/dropdowns

### Screen Reader Support

- Use semantic HTML (`<nav>`, `<main>`, `<button>`)
- Include `aria-label` for icon-only buttons
- Use `aria-live` for dynamic content updates
- Status badges should include hidden text

---

## Browser Support & CSS Strategy

### Baseline Requirements

pullDB targets **modern evergreen browsers** with CSS Custom Properties (CSS Variables) support:

| Browser | Minimum Version | CSS Variables Support |
|---------|-----------------|----------------------|
| Chrome | 49+ | ✅ Native |
| Firefox | 31+ | ✅ Native |
| Safari | 9.1+ | ✅ Native |
| Edge | 15+ | ✅ Native |

### CSS Variable Fallback Strategy

Some CSS files (notably `lazy-tables.css`) include fallback values alongside CSS variables:

```css
/* Pattern with fallback */
background: var(--color-surface-primary, #fff);
```

**Rationale**: Fallbacks provide graceful degradation if design tokens fail to load, but create maintenance overhead. The current approach is:

1. **Keep fallbacks** in complex feature files (tables, dashboards) for resilience
2. **Omit fallbacks** in simple utility classes where failure would be obvious
3. **Document intent** in CSS comments when fallbacks are intentional

### JS-Controlled Visibility Pattern

For elements that need to be hidden on page load and revealed via JavaScript, use the `.js-hidden` utility class instead of inline `style="display: none"`:

```html
<!-- ✅ Correct: Use utility class -->
<div class="modal js-hidden" id="confirm-modal">

<!-- ❌ Avoid: Inline styles -->
<div class="modal" id="confirm-modal" style="display: none;">
```

**Exception**: Jinja conditionals may still use inline styles when the visibility state is server-rendered:
```html
<span {% if count == 0 %}class="js-hidden"{% endif %}>
```

---

## Implementation Status

### Completed ✅

- [x] Design token CSS variables
- [x] Color system
- [x] Typography scale
- [x] Button components
- [x] Card components
- [x] Badge components
- [x] Table styles
- [x] Form inputs
- [x] Alert components
- [x] Navigation patterns
- [x] Toast notifications
- [x] Modal dialogs
- [x] Breadcrumb navigation
- [x] Icon macro system (HCA-compliant)
- [x] Dark mode with CSS variables
- [x] Theme toggle with admin defaults
- [x] Extracted inline CSS from admin templates

### In Progress 🔄

- [ ] Add missing focus states for dark mode

### Planned 📋

- [ ] Skeleton loading states
- [ ] Keyboard shortcuts
- [ ] Skip links for accessibility
- [ ] Component documentation page (live preview)

---

## Changelog

### v1.1.0 (December 15, 2025)
- Added Toast, Modal, and Breadcrumb component documentation
- Added Icon System section with macro usage and available icons
- Added Dark Mode section with activation priority and CSS variables
- Fixed Info color documentation (Cyan, not alias of Primary)
- Fixed role badge class names (`.user` instead of `.developer`)
- Updated manager badge color to Info (was Primary)
- Updated Implementation Status to reflect GUI migration progress

### v1.0.0 (December 4, 2025)
- Initial style guide created
- Documented existing design system
- Established component standards
- Added UX principles reference

---

## References

- [Laws of UX](https://lawsofux.com/)
- [Nielsen's 10 Usability Heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/)
- [WCAG 2.1 Guidelines](https://www.w3.org/WAI/WCAG21/quickref/)
- [Inter Font](https://rsms.me/inter/)
- [JetBrains Mono](https://www.jetbrains.com/lp/mono/)
