# pullDB Design & Development Encyclopedia

> **Version**: 1.5.0  
> **Last Updated**: January 22, 2026  
> **Status**: Active  
> **Audience**: All developers working on pullDB

This document is the **single source of truth** for pullDB design and development standards. It unifies visual design, architecture, security, and coding standards into one comprehensive reference.

---

## Table of Contents

### Part I: Philosophy & Principles
1. [Core Philosophy](#part-i-core-philosophy)
2. [Design Principles](#design-principles)
3. [UX Laws Applied](#ux-laws-applied)

### Part II: Architecture (HCA)
4. [Hierarchical Containment Architecture](#part-ii-hierarchical-containment-architecture)
5. [Layer Model](#layer-model)
6. [Import Rules](#import-rules)
7. [File Placement](#file-placement)

### Part III: Security
8. [Security Model](#part-iii-security)
9. [Authentication](#authentication)
10. [Authorization](#authorization)
11. [Input Validation](#input-validation)
12. [Security Checklist](#security-checklist)

### Part IV: Visual Design System
13. [Design Tokens](#part-iv-visual-design-system)
14. [Color System](#color-system)
15. [Typography](#typography)
16. [Spacing System](#spacing-system)
17. [Component Library](#component-library)
18. [Form Components](#form-components)
19. [Modal Components](#modal-components)
20. [Table Components](#table-components)
21. [Button Reference](#button-reference)
22. [Icon System](#icon-system)
23. [Dark Mode & Theme System](#dark-mode--theme-system)

### Part V: Coding Standards
24. [Python Standards](#part-v-coding-standards)
25. [JavaScript Standards](#javascript-standards)
26. [CSS Standards](#css-standards)
27. [HTMX Integration](#htmx-integration)
28. [Error Handling (FAIL HARD)](#error-handling-fail-hard)
29. [Global JavaScript Functions](#global-javascript-functions)
30. [Data Formatting](#data-formatting)

### Part VI: Page Development
31. [Page Template](#part-vi-page-development)
32. [Breadcrumbs](#breadcrumbs)
33. [Utility Classes](#utility-classes)
34. [Component Patterns](#component-patterns)
35. [State Patterns](#state-patterns)
36. [Navigation Patterns](#navigation-patterns)
37. [Pre-Commit Checklist](#pre-commit-checklist)

### Part VII: Quality & Testing
38. [Testing Standards](#part-vii-quality--testing)
39. [Accessibility (a11y)](#accessibility)
40. [Animations & Transitions](#animations--transitions)
41. [Layout Architecture](#layout-architecture)
42. [Performance](#performance)

---

# Part I: Core Philosophy

## Mission Statement

pullDB is an **internal operations tool** for database restore management. Every design and development decision must serve this mission: **enabling database engineers to safely and efficiently restore databases**.

## Guiding Principles

| Principle | Rationale | Application |
|-----------|-----------|-------------|
| **Clarity over Cleverness** | Users need fast, accurate information | Clear status badges, readable tables, explicit labels |
| **Efficiency over Aesthetics** | Power users need speed | Keyboard shortcuts, minimal clicks, dense information |
| **Consistency over Creativity** | Reduce cognitive load | Same patterns everywhere, predictable behavior |
| **Safety over Speed** | Database operations are destructive | Confirmation dialogs, clear warnings, audit trails |
| **FAIL HARD** | Silent failures cause data loss | Explicit errors, comprehensive diagnostics, no degradation |

## Design Principles

### 1. Progressive Disclosure
Show essential information first, reveal complexity on demand.

```
┌─────────────────────────────────────────┐
│ Level 1: Dashboard Overview             │  ← What users see first
│   4 stat cards, active jobs list        │
├─────────────────────────────────────────┤
│ Level 2: Job Details                    │  ← On click/expand
│   Full job info, logs, timeline         │
├─────────────────────────────────────────┤
│ Level 3: Advanced Options               │  ← "Show Advanced" toggle
│   Raw JSON, debug info, admin controls  │
└─────────────────────────────────────────┘
```

### 2. Information Hierarchy
Visual weight guides user attention.

```
HIGHEST ATTENTION
    ↓ Status badges (colored, prominent)
    ↓ Job ID / Database name (monospace, bold)
    ↓ Primary actions (blue buttons)
    ↓ Secondary info (muted text)
    ↓ Timestamps (smallest, lightest)
LOWEST ATTENTION
```

### 3. Error States are First-Class
Never hide errors. Make them visible, actionable, and complete.

```html
<!-- ✅ GOOD: Complete error state -->
<div class="alert alert-error mb-4">
    <svg class="icon-md"><!-- alert-circle --></svg>
    <div>
        <strong>Restore failed:</strong> Target database "customer_prod" 
        already exists and is not empty.
        <div class="mt-2">
            <a href="/web/admin/hosts/customer_prod" class="text-primary">
                View database status →
            </a>
        </div>
    </div>
</div>

<!-- ❌ BAD: Vague, no action -->
<div class="alert alert-error">
    An error occurred.
</div>
```

## UX Laws Applied

Based on [Laws of UX](https://lawsofux.com/) and [Nielsen's Heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/):

| Law | Implementation |
|-----|----------------|
| **Visibility of System Status** | Live update indicators, status badges, progress bars |
| **Doherty Threshold** (<400ms) | All transitions 150-300ms, HTMX for instant updates |
| **Hick's Law** | Max 4 stat cards, 7±2 nav items per section |
| **Fitts's Law** | Min 32px buttons, adequate spacing between clickables |
| **Jakob's Law** | Standard sidebar nav, conventional form patterns |
| **Von Restorff Effect** | Distinct colors per status, animated running indicator |
| **Law of Common Region** | Cards for grouping, bordered form sections |

---

# Part II: Hierarchical Containment Architecture

## Overview

All code follows **HCA (Hierarchical Containment Architecture)** - a six-law system ensuring code organization, maintainability, and clear dependencies.

```
LAW 1: Flat Locality      → No deeply nested folders (max 2 levels)
LAW 2: Explicit Naming    → Names include parent context  
LAW 3: Single Parent      → Each file has ONE owner directory
LAW 4: Layer Isolation    → Layers only import DOWNWARD
LAW 5: Cross-Layer Bridge → widgets/ bridges features
LAW 6: Plugin Escape      → External code in plugins/
```

## Layer Model

```
┌─────────────────────────────────────────────────────────────┐
│                     plugins/                                │ External tools (myloader)
│                     pulldb/binaries/                        │
├─────────────────────────────────────────────────────────────┤
│                      pages/                                 │ Entry points
│     pulldb/cli/, pulldb/web/, pulldb/api/                   │ (CLI, Web, API routes)
├─────────────────────────────────────────────────────────────┤
│                     widgets/                                │ Orchestration
│                     pulldb/worker/service.py                │ (combines features)
├─────────────────────────────────────────────────────────────┤
│                    features/                                │ Business logic
│                    pulldb/worker/*.py                       │ (restore, download, stage)
├─────────────────────────────────────────────────────────────┤
│                    entities/                                │ Data models
│                    pulldb/domain/                           │ (Job, Config, Backup)
├─────────────────────────────────────────────────────────────┤
│                     shared/                                 │ Infrastructure
│                     pulldb/infra/                           │ (mysql, s3, secrets, logging)
└─────────────────────────────────────────────────────────────┘
```

## Import Rules

**Critical: Layers can only import from same level or BELOW.**

```python
# ✅ ALLOWED - importing from lower layer
from pulldb.infra.mysql import MySQLClient      # shared → feature
from pulldb.domain.models import Job            # entities → feature
from pulldb.worker.restore_job import RestoreJob # features → widget

# ❌ FORBIDDEN - importing from higher layer
from pulldb.cli.commands import restore_cmd     # pages → feature (VIOLATION)
from pulldb.worker.service import WorkerService # widgets → feature (VIOLATION)
```

## File Placement Decision Tree

```
Question                                          │ Layer      │ Directory
──────────────────────────────────────────────────┼────────────┼──────────────────────
Does it interact with external systems (S3, MySQL)?│ shared     │ pulldb/infra/
Is it a data model, config, or error definition? │ entities   │ pulldb/domain/
Is it a single business operation?               │ features   │ pulldb/worker/*.py
Does it orchestrate multiple features?           │ widgets    │ pulldb/worker/service.py
Is it a user entry point (CLI, API, web)?        │ pages      │ pulldb/cli/, api/, web/
Is it an external binary?                        │ plugins    │ pulldb/binaries/
```

## Web Package HCA

The web UI has its own internal HCA structure:

```
pulldb/web/
├── shared/          # CSS tokens, layouts, base utilities
│   ├── css/         # design-tokens.css, layout.css, utilities.css
│   └── layouts/     # Base templates
├── entities/        # Domain-specific HTML components
│   ├── job/         # Job-related partials
│   └── user/        # User-related partials  
├── features/        # Feature routes and logic
│   ├── auth/        # Authentication feature
│   ├── admin/       # Admin feature
│   └── dashboard/   # Dashboard feature
├── widgets/         # Composed UI components
│   ├── sidebar/     # Navigation sidebar
│   └── lazy_table/  # Virtualized table widget
└── templates/       # Page templates
    └── features/    # Feature-specific pages
```

---

# Part III: Security

## Security Model Overview

pullDB handles sensitive database operations. Security is non-negotiable.

```
┌─────────────────────────────────────────────────────────────┐
│                    SECURITY LAYERS                          │
├─────────────────────────────────────────────────────────────┤
│ 1. Authentication   │ Who are you?    │ Session tokens      │
│ 2. Authorization    │ What can you do?│ Role-based (RBAC)   │
│ 3. Input Validation │ Is input safe?  │ Schema validation   │
│ 4. Audit Trail      │ What happened?  │ All actions logged  │
│ 5. Secrets Mgmt     │ Credential safety│ AWS Secrets Manager │
└─────────────────────────────────────────────────────────────┘
```

## Authentication

### Session Management

```python
# Sessions use cryptographically secure tokens
TOKEN_BYTES = 32  # Generates 64 hex characters
DEFAULT_SESSION_TTL_HOURS = 24

# Token storage: NEVER store raw tokens
# Session tokens use SHA256 hashing (fast validation)
token_hash = hashlib.sha256(token.encode()).hexdigest()

# Passwords use bcrypt (slow, resistant to brute force)
password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
```

### Login Flow

```
1. User submits username + password
2. Server validates credentials against bcrypt hash
3. Server creates session with secure random token
4. Token set in HTTP-only, Secure cookie
5. Session expires after 24 hours OR explicit logout
```

### Protected Routes

All routes except `/login` and static assets require authentication:

```python
# Route protection pattern
@router.get("/web/admin/users")
async def admin_users(
    request: Request,
    admin: User = Depends(require_admin),    # ← Validates admin role (includes login check)
):
    ...
```

### Authentication Dependencies

```python
from pulldb.web.dependencies import (
    get_session_user,        # Returns User | None (no exception)
    require_login,           # Raises SessionExpiredError if not logged in
    require_admin,           # Requires admin role (calls require_login)
    require_manager_or_above, # Requires manager or admin role
)

# Optional auth - check if logged in without requiring it
@router.get("/web/public-page")
async def public_page(
    user: User | None = Depends(get_session_user),  # ← None if not logged in
):
    ...
```

## Authorization (RBAC)

### Role Hierarchy

```
SERVICE (system accounts - locked)
  └── Same permissions as ADMIN but cannot login interactively

ADMIN
  ├── Can manage users, hosts, settings
  ├── Can view all jobs
  └── Can perform destructive operations

MANAGER
  ├── Can view all jobs
  ├── Can create/cancel any job
  └── Cannot manage users or system settings

USER
  ├── Can view own jobs
  ├── Can create jobs
  └── Cannot cancel others' jobs or access admin
```

### Role Enum (Python)

```python
from pulldb.domain.models import UserRole

class UserRole(Enum):
    USER = "user"       # Standard user
    MANAGER = "manager" # Operational oversight  
    ADMIN = "admin"     # Full system access
    SERVICE = "service" # System account (locked)
```

### Permission Checks

```python
# Always check permissions server-side, never trust client
def require_admin(
    user: Annotated[User, Depends(require_login)],
) -> User:
    """Require authenticated admin user."""
    if not user.is_admin:  # User model has is_admin property
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user

def require_manager_or_above(
    user: Annotated[User, Depends(require_login)],
) -> User:
    """Require authenticated manager or admin user."""
    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager or admin access required",
        )
    return user

# Use in routes
@router.delete("/api/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: User = Depends(require_admin),  # ← Enforces admin-only
):
    ...
```

## Web Exceptions

Custom exceptions provide consistent error handling:

```python
from pulldb.web.exceptions import (
    SessionExpiredError,        # Session invalid/expired → redirect to login
    PasswordResetRequiredError, # User must change password → redirect to change-password
    MaintenanceRequiredError,   # User must acknowledge maintenance → redirect to maintenance
    PermissionDeniedError,      # User lacks permission → 403 error
    ResourceNotFoundError,      # Resource not found → 404 error
)

# Example: Raise in dependency
if not user:
    raise SessionExpiredError(is_htmx=request.headers.get("HX-Request") == "true")

# HTMX-aware: Uses HX-Redirect header for HTMX requests, HTTP 303 for regular
```

## Input Validation

### Never Trust User Input

```python
# ❌ BAD: SQL injection vulnerability
cursor.execute(f"SELECT * FROM users WHERE username = '{username}'")

# ✅ GOOD: Parameterized query
cursor.execute("SELECT * FROM users WHERE username = %s", (username,))

# ❌ BAD: XSS vulnerability in templates
return f"<div>Hello {user_input}</div>"

# ✅ GOOD: Jinja2 auto-escaping (enabled by default)
# template: <div>Hello {{ user_input }}</div>
```

### Form Validation

```python
# Pydantic models for input validation
class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-z0-9_]+$")
    email: EmailStr
    role: Literal["admin", "manager", "user"]
    
    @validator("username")
    def username_lowercase(cls, v):
        return v.lower()
```

### Dangerous Operations Require Confirmation

```javascript
// Destructive actions MUST have confirmation
async function deleteUser(userId) {
    const confirmed = await showConfirmModal({
        title: 'Delete User',
        message: `Are you sure you want to delete this user? This cannot be undone.`,
        confirmText: 'Delete',
        confirmClass: 'btn-danger'
    });
    
    if (!confirmed) return;
    
    // Proceed with deletion
}
```

## Security Checklist

Before committing code, verify:

- [ ] **Authentication**: All non-public routes check session
- [ ] **Authorization**: Role-based checks on sensitive operations
- [ ] **SQL Injection**: All queries use parameterized statements
- [ ] **XSS**: All user content rendered through Jinja2 escaping
- [ ] **CSRF**: State-changing operations use CSRF tokens (if applicable)
- [ ] **Secrets**: No credentials in code, use AWS Secrets Manager
- [ ] **Logging**: Sensitive data not logged (passwords, tokens, PII)
- [ ] **Validation**: All input validated with Pydantic schemas
- [ ] **Confirmation**: Destructive actions require user confirmation

---

# Part IV: Visual Design System

## Design Tokens

All visual values are defined as CSS custom properties in `design-tokens.css`. **Never use hardcoded values.**

```css
/* ✅ GOOD: Use design tokens */
.card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: var(--space-6);
}

/* ❌ BAD: Hardcoded values */
.card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 24px;
}
```

## Color System

### Brand Colors

```css
/* Primary (Blue) - Actions, links, focus states */
--primary-500: #3b82f6;    /* Main brand */
--primary-600: #2563eb;    /* Buttons */
--primary-700: #1d4ed8;    /* Hover */

/* Success (Green) - Completed, enabled, positive */
--success-500: #22c55e;
--success-600: #16a34a;

/* Warning (Amber) - Caution, canceled, pending */
--warning-500: #f59e0b;
--warning-600: #d97706;

/* Danger (Red) - Errors, failed, destructive */
--danger-500: #ef4444;
--danger-600: #dc2626;
```

### Status Color Mapping

| Status | Background | Text | Indicator |
|--------|------------|------|-----------|
| **Queued** | `gray-100` | `gray-700` | `gray-500` |
| **Running** | `primary-100` | `primary-700` | `primary-500` (animated) |
| **Complete** | `success-100` | `success-700` | `success-500` |
| **Failed** | `danger-100` | `danger-700` | `danger-500` |
| **Canceled** | `warning-100` | `warning-700` | `warning-500` |

### Color Rules

1. **Never use color alone** to convey meaning (accessibility)
2. **Pair color with icons** for status indication
3. **100-level backgrounds** for badges and callouts
4. **600-700 level text** on light backgrounds
5. **4.5:1 contrast minimum** for body text

## Typography

### Font Stack

```css
/* UI Text */
--font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;

/* Technical Values (Job IDs, database names, codes) */
--font-mono: 'JetBrains Mono', ui-monospace, 'Cascadia Code', monospace;
```

### Type Scale

| Token | Size | Usage |
|-------|------|-------|
| `--text-2xs` | 10px (0.625rem) | Micro labels |
| `--text-xs` | 12px (0.75rem) | Badges, timestamps |
| `--text-sm` | 14px (0.875rem) | Secondary text |
| `--text-base` | 15px (0.9375rem) | Body text |
| `--text-md` | 16px (1rem) | Card titles |
| `--text-lg` | 18px (1.125rem) | Page headers |
| `--text-xl` | 20px (1.25rem) | Section titles |
| `--text-2xl` | 24px (1.5rem) | Large headings |

### Typography Rules

1. Use **Inter** for all UI text
2. Use **JetBrains Mono** for: Job IDs, database names, user codes, technical values
3. Maximum **3 heading levels**: page, card, section
4. Avoid bold for emphasis in body text - use color or icons instead

## Spacing System

Based on 4px increments (using rem for accessibility):

```css
--space-1:  0.25rem;   /*  4px */
--space-2:  0.5rem;    /*  8px */
--space-3:  0.75rem;   /* 12px */
--space-4:  1rem;      /* 16px - Default */
--space-5:  1.25rem;   /* 20px */
--space-6:  1.5rem;    /* 24px - Card padding */
--space-8:  2rem;      /* 32px - Section margin */
--space-10: 2.5rem;    /* 40px */
--space-12: 3rem;      /* 48px */
```

### Spacing Application

| Context | Token | Pixels |
|---------|-------|--------|
| Button padding (y) | `space-2` to `space-3` | 8-12px |
| Button padding (x) | `space-4` | 16px |
| Card padding | `space-6` | 24px |
| Section margin | `space-8` | 32px |
| Gap between cards | `space-4` | 16px |
| Alert margin-bottom | `space-4` | 16px |

## Component Library

### Buttons

```html
<!-- Primary (main actions) -->
<button class="btn btn-primary">{{ icon('plus', size='18') }} Create</button>

<!-- Secondary -->
<button class="btn btn-secondary">{{ icon('x', size='18') }} Cancel</button>

<!-- Danger (destructive) -->
<button class="btn btn-danger">{{ icon('trash-2', size='18') }} Delete</button>

<!-- Ghost (subtle) -->
<button class="btn btn-ghost">{{ icon('refresh-cw', size='18') }} Refresh</button>

<!-- Icon-only (MUST have title AND aria-label) -->
<button class="btn-icon" title="Settings" aria-label="Settings">
    {{ icon('settings', size='18') }}
</button>
```

### Cards

```html
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
        Content
    </div>
</div>
```

### Alerts

```html
<div class="alert alert-error mb-4">
    {{ icon('alert-circle', size='20') }}
    <div>Error message with context and action</div>
</div>

<div class="alert alert-success mb-4">
    {{ icon('check-circle', size='20') }}
    <div>Success message</div>
</div>

<div class="alert alert-warning mb-4">
    {{ icon('alert-triangle', size='20') }}
    <div>Warning message</div>
</div>

<div class="alert alert-info mb-4">
    {{ icon('info', size='20') }}
    <div>Info message</div>
</div>
```

### Badges

```html
<span class="badge badge-complete">
    <span class="badge-dot"></span>
    Complete
</span>

<span class="badge badge-failed">
    <span class="badge-dot"></span>
    Failed
</span>

<span class="badge badge-running">
    <span class="badge-dot"></span>  <!-- Animated -->
    Running
</span>
```

### Forms

```html
<div class="form-group">
    <label for="database" class="form-label">Database Name</label>
    <input type="text" id="database" name="database" 
           class="form-input" placeholder="e.g., customer_prod">
    <p class="form-hint">Target database for restore operation</p>
</div>

<div class="form-actions">
    <button type="submit" class="btn btn-primary">Save</button>
    <button type="button" class="btn btn-ghost">Cancel</button>
</div>
```

## Form Components

### BEM Structure

Form components use BEM naming with legacy compatibility:

| BEM Class | Legacy Class | Purpose |
|-----------|--------------|---------|
| `.form` | - | Form container |
| `.form__group` | `.form-group` | Input wrapper |
| `.form__label` | `.form-label` | Input label |
| `.form__input` | `.form-input` | Text input |
| `.form__select` | `.form-select` | Select dropdown |
| `.form__textarea` | `.form-textarea` | Text area |
| `.form__hint` | `.form-hint` | Help text |
| `.form__error` | `.form-error` | Error message |

### Complete Form Example

```html
<form id="restore-form" class="form">
    <div class="form-section">
        <h4 class="form-section-title">Database Settings</h4>
        
        <div class="form-row">
            <div class="form-group form-group-wide">
                <label for="db_name" class="form-label required">Database Name</label>
                <input type="text" id="db_name" name="db_name" 
                       class="form-input" 
                       placeholder="customer_staging"
                       required maxlength="64">
                <p class="form-hint">Target database for restore</p>
            </div>
            
            <div class="form-group form-group-narrow">
                <label for="db_port" class="form-label">Port</label>
                <input type="number" id="db_port" name="db_port" 
                       class="form-input" 
                       value="3306" min="1" max="65535">
            </div>
        </div>
        
        <div class="form-group">
            <label for="options" class="form-label">Restore Options</label>
            <select id="options" name="options" class="form-select">
                <option value="full">Full Restore</option>
                <option value="schema">Schema Only</option>
                <option value="data">Data Only</option>
            </select>
        </div>
    </div>
    
    <div class="form-actions">
        <button type="submit" class="btn btn-primary">
            {{ icon('play', size='18') }}
            Start Restore
        </button>
        <button type="button" class="btn btn-ghost" onclick="closeModal()">
            Cancel
        </button>
    </div>
</form>
```

### Form Validation States

```html
<!-- Valid state -->
<div class="form-group">
    <label for="email" class="form-label">Email</label>
    <input type="email" id="email" class="form-input is-valid" value="user@example.com">
    <p class="validation-message success">Email is valid</p>
</div>

<!-- Invalid state -->
<div class="form-group">
    <label for="password" class="form-label">Password</label>
    <input type="password" id="password" class="form-input is-invalid">
    <p class="validation-message error">Password must be at least 8 characters</p>
</div>
```

### Form Layouts

```html
<!-- Grid layout (2 columns) -->
<div class="form__grid">
    <div class="form-group">...</div>
    <div class="form-group">...</div>
</div>

<!-- Row layout (flexible widths) -->
<div class="form-row">
    <div class="form-group form-group-wide">...</div>   <!-- Takes more space -->
    <div class="form-group form-group-narrow">...</div> <!-- Takes less space -->
</div>

<!-- Small row (for compact inputs) -->
<div class="form-row form-row-small">
    <div class="form-group">...</div>
    <div class="form-group">...</div>
</div>
```

### Input with Status (HTMX Validation)

```html
<div class="form-group">
    <label for="alias" class="form-label required">Host Alias</label>
    <div class="input-with-status">
        <input type="text" id="alias" name="alias" class="form-input"
               hx-post="/web/admin/hosts/check-alias"
               hx-trigger="blur changed delay:300ms"
               hx-target="#alias-status"
               hx-swap="innerHTML">
        <span id="alias-status" class="input-status"></span>
    </div>
</div>
```

## Modal Components

### BEM Structure

| BEM Class | Legacy Class | Purpose |
|-----------|--------------|---------|
| `.modal` | - | Modal backdrop |
| `.modal__content` | `.modal-content` | Modal container |
| `.modal__header` | `.modal-header` | Header section |
| `.modal__title` | `.modal-title` | Title text |
| `.modal__close` | `.modal-close` | Close button |
| `.modal__body` | `.modal-body` | Content area |
| `.modal__footer` | `.modal-footer` | Action buttons |

### Size Variants

```css
.modal__content--sm   /* max-width: 400px - Simple confirmations */
.modal__content       /* max-width: 500px - Default */
.modal__content--wide /* max-width: 600px - Forms with more fields */
.modal__content--lg   /* max-width: 700px - Complex forms */
```

### Complete Modal Template

```html
<!-- In {% block modals %} -->
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
        
        <form id="add-item-form" onsubmit="handleSubmit(event)">
            <div class="modal-body">
                <!-- Form content -->
                <div class="form-group">
                    <label for="name" class="form-label required">Name</label>
                    <input type="text" id="name" name="name" 
                           class="form-input" required>
                </div>
            </div>
            
            <div class="modal-footer">
                <button type="button" class="btn btn-ghost" 
                        onclick="closeModal('add-item-modal')">
                    Cancel
                </button>
                <button type="submit" class="btn btn-primary">
                    {{ icon('check', size='18') }}
                    Save
                </button>
            </div>
        </form>
    </div>
</div>
```

### Modal JavaScript Patterns

```javascript
// Open modal
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    modal.classList.remove('modal-hidden');
    modal.classList.add('modal-visible');
    // Focus first input
    const firstInput = modal.querySelector('input, select, textarea');
    if (firstInput) firstInput.focus();
}

// Close modal
function closeModal(modalId) {
    const modal = document.getElementById(modalId || 'modal');
    modal.classList.add('modal-hidden');
    modal.classList.remove('modal-visible');
    // Reset form if exists
    const form = modal.querySelector('form');
    if (form) form.reset();
}

// Close on backdrop click
document.querySelectorAll('.modal').forEach(modal => {
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal(modal.id);
        }
    });
});

// Close on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const visibleModal = document.querySelector('.modal-visible');
        if (visibleModal) closeModal(visibleModal.id);
    }
});
```

### Danger Modal (Red Header)

```html
<div id="delete-modal" class="modal modal-hidden">
    <div class="modal-content modal__content--sm">
        <div class="modal-header modal-header-danger">
            <h3 class="modal-title">
                {{ icon('alert-triangle', size='20') }}
                Delete Item
            </h3>
            <button type="button" class="modal-close" 
                    onclick="closeModal('delete-modal')">
                {{ icon('x', size='20') }}
            </button>
        </div>
        
        <div class="modal-body">
            <p>Are you sure you want to delete this item? This action cannot be undone.</p>
        </div>
        
        <div class="modal-footer">
            <button type="button" class="btn btn-ghost" 
                    onclick="closeModal('delete-modal')">
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

## Table Components

### BEM Structure

| BEM Class | Legacy Class | Purpose |
|-----------|--------------|---------|
| `.table` | `.data-table` | Table element |
| `.table__header` | - | Header row container |
| `.table__row` | - | Table row |
| `.table__cell` | - | Table cell |
| `.table--data` | `.data-table` | Data table variant |
| `.table--compact` | - | Compact padding |

### Row States

```css
.table__row.is-selected  /* Selected row (light blue background) */
.table__row.is-excluded  /* Excluded row (faded, strikethrough) */
.table__row:hover        /* Hover state (light gray) */
```

### Cell Utilities

```html
<!-- Primary cell (emphasized) -->
<td class="cell-primary">Important Value</td>

<!-- Secondary cell (muted) -->
<td class="cell-secondary">2024-01-15</td>

<!-- Monospace cell -->
<td class="cell-mono-sm">job_abc123</td>

<!-- Alignment -->
<td class="text-right">$1,234.56</td>
<td class="text-center">✓</td>
```

### Complete Table Example

```html
<div class="table-container">
    <table class="table data-table">
        <thead>
            <tr class="table__header">
                <th>Name</th>
                <th>Status</th>
                <th class="text-right">Actions</th>
            </tr>
        </thead>
        <tbody>
            <tr class="table__row">
                <td class="cell-primary">Production DB</td>
                <td>
                    <span class="badge badge-complete">
                        <span class="badge-dot"></span>
                        Complete
                    </span>
                </td>
                <td class="text-right">
                    <button class="action-btn" title="View details" aria-label="View details">
                        {{ icon('eye', size='16') }}
                    </button>
                    <button class="action-btn" title="Delete" aria-label="Delete">
                        {{ icon('trash-2', size='16') }}
                    </button>
                </td>
            </tr>
        </tbody>
    </table>
</div>
```

### LazyTable Widget

For large datasets, use the `LazyTable` widget with server-side lazy loading:

```python
# In route
from pulldb.web.widgets.lazy_table import LazyTable

lazy_table = LazyTable(
    table_id="jobs-table",
    columns=[
        {"key": "job_id", "label": "Job ID", "sortable": True},
        {"key": "status", "label": "Status", "sortable": True},
        {"key": "created_at", "label": "Created", "sortable": True},
    ],
    data_url="/api/jobs",
    row_height=48,
    page_size=50,
)
```

```html
<!-- In template -->
{{ lazy_table.render() }}
```

## Button Reference

### Color Variants

| Class | Use Case | Example |
|-------|----------|---------|
| `.btn-primary` | Main actions | Create, Save, Submit |
| `.btn-secondary` | Alternative actions | Export, Import |
| `.btn-danger` | Destructive actions | Delete, Remove |
| `.btn-ghost` | Subtle/cancel actions | Cancel, Close |
| `.btn-success` | Positive confirmations | Approve, Accept |
| `.btn-warning` | Caution actions | Force restart |
| `.btn-outline` | Neutral outline button | Secondary options |
| `.btn--link` | Link-styled button | "Learn more" |

### Size Variants

| Class | Height | Use Case |
|-------|--------|----------|
| `.btn-xs` | 28px | Inline/table actions |
| `.btn-sm` | 32px | Card actions |
| (default) | 36px | Standard buttons |
| `.btn-lg` | 44px | Primary page actions |

### Icon Buttons

```html
<!-- Icon-only (transparent) -->
<button class="btn-icon" title="Settings" aria-label="Settings">
    {{ icon('settings', size='18') }}
</button>

<!-- Icon with primary background -->
<button class="btn-icon-primary" title="Add" aria-label="Add new item">
    {{ icon('plus', size='18') }}
</button>

<!-- Action button (table row) -->
<button class="action-btn" title="Edit" aria-label="Edit item">
    {{ icon('edit', size='16') }}
</button>
```

### Button with Icon

```html
<button class="btn btn-primary">
    {{ icon('plus', size='18') }}
    Add Item
</button>

<button class="btn btn-danger btn-sm">
    {{ icon('trash-2', size='16') }}
    Delete
</button>
```

### Disabled State

```html
<button class="btn btn-primary" disabled>
    {{ icon('loader', size='18', class='animate-spin') }}
    Processing...
</button>
```

## Icon System

pullDB uses an HCA-layered Jinja macro system for SVG icons.

### Usage

```html
{% from "partials/icons/_index.html" import icon %}

<!-- Basic usage -->
{{ icon('database', size='20') }}

<!-- With additional classes -->
{{ icon('check', size='16', class='text-success icon-sm') }}

<!-- With custom stroke width -->
{{ icon('alert-triangle', size='24', stroke_width='2') }}
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | string | required | Icon name (e.g., 'database', 'user', 'check') |
| `size` | string | '20' | Width/height in pixels |
| `class` | string | '' | Additional CSS classes |
| `stroke_width` | string | '1.5' | SVG stroke width |

### Size Guidelines

| Size | Use Case | Class |
|------|----------|-------|
| 12px | Micro icons, badges | `icon-xs` |
| 16px | Inline text, table cells | `icon-sm` |
| 18px | Button icons | - |
| 20px | Default, card titles | `icon-md` |
| 24px | Page titles, stat cards | `icon-lg` |
| 32px | Empty states | `icon-xl` |

### Icon + Text Inline Pattern (REQUIRED)

**Icons MUST always remain on the same line as their associated label/data.** Use `inline-flex` with `items-center` and `gap-1` or `gap-2` to prevent wrapping.

```html
<!-- ✅ CORRECT: Icon and text stay together -->
<span class="inline-flex items-center gap-1 text-muted text-sm">
    {{ icon('database', size='16', aria_hidden='true') }}
    <span>42 records</span>
</span>

<!-- ❌ WRONG: No flex wrapper - icon may wrap to separate line -->
<span class="text-muted text-sm">
    {{ icon('database', size='16', aria_hidden='true') }}
    <span>42 records</span>
</span>
```

| Pattern | Classes | Use Case |
|---------|---------|----------|
| Inline stat | `inline-flex items-center gap-1` | Status badges, counts |
| Button content | `flex items-center gap-2` | Button with icon |
| Card title | `flex items-center gap-2` | Headers with icon |

### Icon Layers (HCA)

Icons are organized by HCA layer:

| File | Layer | Icons |
|------|-------|-------|
| `shared.html` | Infrastructure | database, server, cloud, cog, folder, globe |
| `entities.html` | Data Models | user, users, shield, key, lock |
| `features.html` | Business Logic | play, pause, check, x, alert, clock |
| `widgets.html` | Orchestration | menu, chevron, arrow, refresh |
| `pages.html` | Entry Points | home, layout-grid, settings |

### Unknown Icon Fallback

If an icon name is not found, a question mark placeholder is rendered:

```html
<!-- data-icon="unknown:invalid-name" attribute helps debugging -->
```

## Dark Mode & Theme System

Theme switching is handled by `theme-toggle.js` with the following priority:

### Theme Resolution Order

1. **localStorage** - User's explicit preference override
2. **Admin default** - `data-admin-theme-default` attribute on `<html>`
3. **System preference** - `prefers-color-scheme: dark` media query
4. **Fallback** - Light mode

### Implementation

```javascript
// theme-toggle.js manages theme state
// Stores preference in localStorage as 'pulldb-theme'
// Also sets cookie 'pulldb_theme' for server-side awareness

// Toggle theme programmatically
document.getElementById('theme-toggle').click();
```

### CSS Architecture

```
static/css/generated/
├── manifest-light.css  ← Loaded by default
└── manifest-dark.css   ← Swapped in for dark mode
```

The theme CSS files are **dynamically generated** and contain all `--color-*` semantic tokens. This approach:
- Provides complete isolation between themes
- Enables admin-configurable colors
- Prevents CSS cascade conflicts

### Testing Both Themes

```javascript
// Force dark mode in browser console
document.documentElement.setAttribute('data-theme', 'dark');

// Force light mode
document.documentElement.setAttribute('data-theme', 'light');
```

### Rules

1. **Never hardcode colors** - always use `var(--color-*)` tokens
2. **Test in both themes** before committing
3. **No flash on load** - theme detection runs synchronously in `<head>`
4. **Use semantic tokens** - `--color-text-primary` not `--gray-900`

---

# Part V: Coding Standards

## Python Standards

### Tools

- **Linter**: Ruff (replaces Flake8, isort, pydocstyle)
- **Formatter**: Ruff format (Black-compatible)
- **Type Checker**: Mypy (strict mode)
- **Test Framework**: pytest

### Style

```python
# Line length: 88 characters (Ruff/Black default)

# Import order:
# 1. Future imports
from __future__ import annotations

# 2. Standard library
import os
from typing import Any

# 3. Third-party
import boto3

# 4. Local
from pulldb.domain import models
from pulldb.infra import mysql
```

### Naming

```python
# Functions/variables: snake_case
def process_backup(backup_path: str) -> BackupResult:
    pass

# Classes: PascalCase
class BackupProcessor:
    pass

# Constants: UPPER_CASE
MAX_RETRY_ATTEMPTS = 3

# Private: _leading_underscore
def _internal_helper():
    pass
```

### Type Hints (Required)

```python
# ✅ GOOD: Complete type hints
def process_backup(
    backup_path: str,
    target_db: str,
    timeout_seconds: int = 300,
) -> BackupResult:
    """Process backup and restore to target."""
    pass

# Use modern syntax (Python 3.9+)
def process(items: list[str]) -> dict[str, int] | None:
    pass
```

### Docstrings (Google Style)

```python
def restore_database(
    job_id: str,
    backup_key: str,
    target_host: str,
) -> RestoreResult:
    """Restore database from S3 backup.

    Downloads backup, validates schema, executes myloader restore,
    and applies post-restore SQL scripts.

    Args:
        job_id: Unique job identifier for tracking.
        backup_key: S3 key path to backup archive.
        target_host: MySQL host for restore target.

    Returns:
        RestoreResult with status, duration, and error details.

    Raises:
        BackupValidationError: When backup is missing required files.
        RestoreError: When myloader execution fails.
    """
    pass
```

## JavaScript Standards

### ES6+ Syntax

```javascript
// Use const/let, never var
const MAX_RETRIES = 3;
let currentPage = 1;

// Arrow functions for callbacks
items.map(item => item.name);

// Template literals
const message = `Job ${jobId} completed in ${duration}ms`;

// Destructuring
const { id, status, created_at } = job;

// Async/await over promises
async function fetchJobs() {
    const response = await fetch('/api/jobs');
    return response.json();
}
```

### DOM Interaction

```javascript
// Wait for DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initializePage();
});

// Use getElementById for single elements
const modal = document.getElementById('confirm-modal');

// Use querySelectorAll for multiple elements
const buttons = document.querySelectorAll('.btn-delete');

// Event delegation for dynamic content
document.addEventListener('click', (e) => {
    if (e.target.matches('.delete-btn')) {
        handleDelete(e.target.dataset.id);
    }
});
```

## CSS Standards

### BEM Naming

```css
/* Block */
.card { }

/* Element */
.card__header { }
.card__body { }
.card__title { }

/* Modifier */
.card--highlighted { }
.card--compact { }
```

### Utility Classes

Use existing utilities over custom CSS:

```html
<!-- ✅ GOOD: Use utilities -->
<div class="flex items-center gap-4 mb-4">

<!-- ❌ BAD: Custom CSS for common patterns -->
<div style="display: flex; align-items: center; gap: 16px; margin-bottom: 16px;">
```

### CSS Organization (HCA)

```
shared/css/
├── design-tokens.css    # Variables first
├── reset.css            # Browser normalization
├── layout.css           # App structure
├── utilities.css        # Single-purpose utilities
└── base.css             # Default element styles

features/css/
├── buttons.css          # Button component
├── cards.css            # Card component
├── forms.css            # Form elements
├── tables.css           # Table styles
└── badges.css           # Status badges

pages/css/
├── admin.css            # Admin section
├── dashboard.css        # Dashboard page
└── jobs.css             # Jobs page
```

## HTMX Integration

pullDB uses HTMX for dynamic page updates without full reloads.

### Common Attributes

| Attribute | Purpose | Example |
|-----------|---------|---------|
| `hx-get` | GET request to URL | `hx-get="/api/stats"` |
| `hx-post` | POST request to URL | `hx-post="/api/validate"` |
| `hx-target` | Element to update | `hx-target="#result"` |
| `hx-swap` | How to swap content | `hx-swap="innerHTML"` |
| `hx-trigger` | When to fire request | `hx-trigger="every 5s"` |
| `hx-select` | Select subset of response | `hx-select=".container"` |
| `hx-indicator` | Loading indicator | `hx-indicator=".spinner"` |

### Pattern: Auto-Refresh Dashboard

```html
<div class="dashboard-container" 
     hx-get="{{ request.url }}" 
     hx-trigger="every {{ refresh_interval }}s" 
     hx-select=".dashboard-container" 
     hx-swap="outerHTML">
    <!-- Dashboard content - auto-refreshes every N seconds -->
</div>
```

### Pattern: Polling for Running Jobs

```html
<div id="job-details-container" 
     hx-get="{{ request.url.path }}" 
     {% if job.status.value in ['running', 'queued'] %}
     hx-trigger="every 5s"
     {% endif %}
     hx-select="#job-details-content" 
     hx-swap="innerHTML" 
     hx-target="#job-details-content">
    <div id="job-details-content">
        <!-- Only refreshes while job is active -->
    </div>
</div>
```

### Pattern: Inline Validation

```html
<input type="text" id="alias" name="alias" class="form-input"
       hx-post="/web/admin/hosts/check-alias"
       hx-trigger="blur changed delay:300ms"
       hx-target="#alias-status"
       hx-swap="innerHTML">
<span id="alias-status" class="input-status">
    <!-- Updated with validation result -->
</span>
```

### Pattern: Load More Pagination

```html
<button class="btn btn-secondary load-more-btn"
        hx-get="/api/items?page={{ next_page }}"
        hx-target="#items-container"
        hx-swap="beforeend"
        hx-indicator=".load-more-btn">
    Load More
</button>
```

### Swap Methods

| Method | Behavior |
|--------|----------|
| `innerHTML` | Replace inner content (default) |
| `outerHTML` | Replace entire element |
| `beforeend` | Append inside target |
| `afterbegin` | Prepend inside target |
| `beforebegin` | Insert before target |
| `afterend` | Insert after target |
| `delete` | Remove target element |

### Best Practices

1. **Use `hx-select`** to extract only needed content from response
2. **Set appropriate polling intervals** (5s for active jobs, 30s for dashboards)
3. **Disable polling when not needed** (e.g., completed jobs)
4. **Use `hx-indicator`** to show loading state during requests
5. **Prefer partial updates** over full page replacements

## Error Handling (FAIL HARD)

### Philosophy

When operations fail, **fail immediately with comprehensive diagnostics**. Never silently degrade.

### Diagnostic Structure

Every failure must provide:

```
1. GOAL: What was the intended outcome?
2. PROBLEM: What actually happened? (full error, not truncated)
3. ROOT CAUSE: Why did it fail? (validated, not speculation)
4. SOLUTIONS: Ranked options with pros/cons
```

### Python Example

```python
# ❌ BAD: Vague, swallows error
try:
    operation()
except Exception:
    raise ValueError("Something went wrong")

# ✅ GOOD: Specific, contextualized, actionable
try:
    client.describe_secret(SecretId=secret_id)
except ClientError as e:
    if e.response["Error"]["Code"] == "ResourceNotFoundException":
        raise SecretNotFoundError(
            f"Secret '{secret_id}' does not exist in AWS Secrets Manager. "
            f"Create with: aws secretsmanager create-secret "
            f"--name {secret_id} --secret-string '{{...}}'"
        ) from e  # ← Preserve traceback with 'from e'
    raise
```

### JavaScript Example

```javascript
// ❌ BAD: Silent failure
async function fetchData() {
    try {
        return await fetch('/api/data');
    } catch (e) {
        return null;  // Hides failure!
    }
}

// ✅ GOOD: Visible failure with context
async function fetchData() {
    try {
        const response = await fetch('/api/data');
        if (!response.ok) {
            throw new Error(`API error: ${response.status} ${response.statusText}`);
        }
        return response.json();
    } catch (e) {
        console.error('Failed to fetch data:', e);
        showToast(`Failed to load data: ${e.message}`, 'error');
        throw e;  // Re-throw for caller to handle
    }
}
```

## Global JavaScript Functions

These functions are available globally (defined in `static/js/main.js`):

### showToast()

Display toast notifications for user feedback:

```javascript
// Signature
showToast(message, type = 'info')

// Types: 'info', 'success', 'warning', 'error'
// Auto-dismiss times: info=5s, success=4s, warning=10s, error=60s

// Examples
showToast('Settings saved successfully', 'success');
showToast('Please check your input', 'warning');
showToast(`Error: ${error.message}`, 'error');

// Server-side flash messages (in template)
{% if flash_message %}
<script>
    showToast({{ flash_message|tojson }}, {{ flash_type|tojson }});
</script>
{% endif %}
```

### showConfirm()

Themed replacement for native `confirm()` dialog:

```javascript
// Signature
showConfirm(message, options = {}) → Promise<boolean>

// Options:
// - title: Modal title (default: 'Confirm')
// - okText: OK button text (default: 'OK')
// - type: 'default', 'danger', 'warning' (affects header/button colors)

// Example: Basic confirmation
const confirmed = await showConfirm('Are you sure?');
if (!confirmed) return;

// Example: Danger confirmation (red header, red button)
const confirmed = await showConfirm(
    'Delete this user? This cannot be undone.',
    {
        title: 'Delete User',
        okText: 'Delete',
        type: 'danger'
    }
);

// Example: Warning confirmation
const confirmed = await showConfirm(
    'This will cancel all running jobs.',
    {
        title: 'Cancel Jobs',
        okText: 'Cancel All',
        type: 'warning'
    }
);
```

### showValidationSummary()

Display multiple validation errors in a structured format:

```javascript
// Signature
showValidationSummary(errors, title = 'Please fix the following issues:')

// Example
const errors = [
    'Username is required',
    'Password must be at least 8 characters',
    'Email format is invalid'
];
showValidationSummary(errors);
```

## Data Formatting Utilities

### Local DateTime Conversion

pullDB stores all timestamps in UTC. The `local-datetime.js` utility converts and formats them for display.

#### HTML Usage

```html
<!-- UTC to local (auto-converts on page load) -->
<time data-utc="{{ job.created_at.isoformat() }}"></time>

<!-- With specific format -->
<time data-utc="{{ job.created_at.isoformat() }}" data-format="short"></time>

<!-- Relative time (e.g., "2 hours ago") -->
<time data-utc="{{ job.created_at.isoformat() }}" data-format="relative"></time>
```

#### Available Formats

| Format | Example Output | Use Case |
|--------|---------------|----------|
| `datetime` (default) | "Jan 15, 2026 3:45 PM" | General timestamps |
| `date` | "Jan 15, 2026" | Date-only columns |
| `time` | "3:45:32 PM" | Time-only display |
| `short` | "Jan 15, 3:45 PM" | Compact display |
| `relative` | "2 hours ago" | Activity feeds |

#### JavaScript API

```javascript
// Manual conversion
const element = document.querySelector('time[data-utc]');
LocalDateTime.convert(element);

// Format a date object
const formatted = LocalDateTime.format(new Date(), 'relative');

// Calculate relative time
const ago = LocalDateTime.relative(new Date('2026-01-15T12:00:00Z'));
```

#### Auto-initialization

- **DOM Ready**: All `[data-utc]` elements are converted automatically
- **HTMX Swaps**: Re-runs after `htmx:afterSwap` events
- **Manual Trigger**: Call `LocalDateTime.initAll()` after dynamic content

### File Size Formatting

```javascript
// formatBytes() - available in page-specific JS
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i];
}

// Usage
formatBytes(1536)      // "1.5 KB"
formatBytes(1048576)   // "1 MB"
```

---

# Part VI: Page Development

## Page Template

Copy this template for new pages:

```html
{% extends "base.html" %}

{% block title %}Page Title - Section - pullDB{% endblock %}

{% block page_id %}section-page-name{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', path='css/pages/section.css') }}">
{% endblock %}

{# Note: header_title/header_subtitle blocks exist but are not yet rendered in base.html #}
{# They're defined in shared/layouts/app_layout.html for future use #}
{% block header_title %}Page Title{% endblock %}
{% block header_subtitle %}Brief description{% endblock %}

{% block content %}
{% from "partials/icons/_index.html" import icon %}
<div class="feature-page">
    <!-- Page Header -->
    <div class="page-header-row mb-4">
        <div class="page-header-left">
            <h1 class="page-title">
                {{ icon('layout-grid', size='20', class='icon-sm') }}
                Page Title
            </h1>
        </div>
        <div class="status-bar">
            <span class="status-item" title="Total Items">
                {{ icon('database', size='16') }}
                <span class="status-count">{{ stats.total }}</span>
                <span class="status-label">total</span>
            </span>
        </div>
    </div>

    <!-- Flash Messages -->
    {% if flash_message %}
    <div class="alert alert-{{ flash_type }} mb-4">
        {{ flash_message }}
    </div>
    {% endif %}

    <!-- Content -->
    <div class="card">
        <div class="card-header">
            <div class="card-header-left">
                <h3 class="card-title">
                    {{ icon('list', size='18', class='icon-sm') }}
                    Section Title
                </h3>
            </div>
            <div class="card-actions">
                <button class="btn btn-ghost btn-sm">Action</button>
            </div>
        </div>
        <div class="card-body">
            <!-- Content here -->
        </div>
    </div>
</div>
{% endblock %}

{% block modals %}
<!-- Modals outside content for proper fixed positioning -->
{% endblock %}

{% block extra_js %}
<script>
document.addEventListener('DOMContentLoaded', function() {
    // Page initialization
});
</script>
{% endblock %}
```

## Minimalist Page Pattern (Canonical)

> **Reference Implementation**: [jobs.html](pulldb/web/templates/features/jobs/jobs.html)

The canonical pattern for data-centric pages follows **minimalist design**. Do NOT add separate filter forms or stat cards when LazyTable provides built-in column filtering.

### Pattern Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Page Header Row                                          │
│    - Title with icon (left)                                 │
│    - Primary action button (right) - e.g., "New Restore"    │
├─────────────────────────────────────────────────────────────┤
│ 2. [Optional] Tabs                                          │
│    - View switching (Active/History)                        │
│    - Use when same data has distinct view modes             │
├─────────────────────────────────────────────────────────────┤
│ 3. Card with LazyTable                                      │
│    - LazyTable handles ALL filtering via column headers     │
│    - filterable: true on columns enables inline filtering   │
│    - Actions in table rows or header (bulk actions)         │
│    - footerSlot for navigation ("Back to X")                │
└─────────────────────────────────────────────────────────────┘
```

### ✅ DO: Minimalist Structure

```html
<div class="feature-page">
    <!-- 1. Simple header with action -->
    <div class="page-header-row mb-4">
        <div class="page-header-left">
            <h1 class="page-title">
                {{ icon('briefcase', size='20', class='icon-sm') }}
                Jobs
            </h1>
        </div>
        <div class="flex gap-4 items-center">
            <a href="/web/restore" class="btn btn-primary">New Restore Job</a>
        </div>
    </div>

    <!-- 2. Optional tabs for view modes -->
    <div class="tabs mb-4">
        <button type="button" class="tab tab-active" data-view="active">Active</button>
        <button type="button" class="tab" data-view="history">History</button>
    </div>

    <!-- 3. Direct to LazyTable - filtering is IN the table -->
    <div class="card lazy-table-height-viewport">
        <div id="table-container"></div>
    </div>
</div>
```

### ❌ DON'T: Redundant Filter Cards

```html
<!-- WRONG: Separate filter form when LazyTable can filter -->
<div class="card card-padding mb-4">
    <div class="card-section-title">Filter & Manage</div>
    <form class="filter-grid">
        <input type="text" name="username">  <!-- Duplicate of LazyTable column filter -->
        <select name="status">...</select>   <!-- Duplicate of LazyTable column filter -->
        <button>Search</button>              <!-- Unnecessary - LazyTable filters live -->
    </form>
</div>
```

### LazyTable Column Filtering

Use the `filterable` property on columns instead of external forms:

```javascript
const columns = [
    { key: 'id', label: 'Job ID', sortable: true, filterable: true, filterType: 'text', filterPlaceholder: 'b875*' },
    { key: 'owner_user_code', label: 'User', sortable: true, filterable: true },
    { key: 'status', label: 'Status', sortable: true, filterable: true },
    { key: 'submitted_at', label: 'Date', sortable: true, filterable: true, filterType: 'dateRange' },
];
```

| Filter Type | Use Case |
|-------------|----------|
| `filterable: true` (default) | Dropdown of unique values from column |
| `filterType: 'text'` | Free-text with wildcard support (`*`) |
| `filterType: 'dateRange'` | Date picker for range filtering |

### When Separate Controls ARE Appropriate

| Scenario | Pattern |
|----------|---------|
| **Bulk destructive action** (prune all before date) | Modal confirmation with typed safety phrase |
| **Non-filterable global actions** (toggle view mode) | Tabs at top, not in table |
| **Export/Import** | Header action button opening modal |
| **Stats summary** | Dashboard page only, not list pages |

### Summary: Minimalism Checklist

- [ ] Header has only: title + primary action (no stats)
- [ ] No separate "Filter" card for LazyTable pages
- [ ] Column filtering via `filterable: true` in LazyTable config
- [ ] Tabs for view modes (if needed), not filter states
- [ ] Bulk actions via table selection + modal confirmation
- [ ] Footer slot for navigation, not filter submission

## Breadcrumbs

Navigation context is provided via the `get_breadcrumbs()` function in routes:

### Route Setup

```python
from pulldb.web.widgets.breadcrumbs import get_breadcrumbs

@router.get("/web/admin/users")
async def admin_users(request: Request, ...):
    return templates.TemplateResponse(
        "features/admin/users.html",
        {
            "request": request,
            "breadcrumbs": get_breadcrumbs("admin_users"),  # ← Provides nav context
            ...
        }
    )
```

### Pre-defined Breadcrumb Paths

```python
# Common paths (from pulldb/web/widgets/breadcrumbs/__init__.py)
"dashboard"           # Dashboard
"my_jobs"            # Dashboard → My Jobs
"admin"              # Dashboard → Administration
"admin_users"        # Dashboard → Administration → Users
"admin_job_history"  # Dashboard → Administration → Job History
"manager"            # Dashboard → Team Management
```

### Custom Breadcrumbs

```python
# Dynamic breadcrumb (e.g., job detail page)
get_breadcrumbs("job_detail", job=job_id[:8])  # Shows truncated job ID

# Custom path
from pulldb.web.widgets.breadcrumbs import build_breadcrumbs

breadcrumbs = build_breadcrumbs(
    ("Dashboard", "/web/dashboard"),
    ("Custom Section", "/web/custom"),
    ("Current Page", None),  # Last item has url=None
)
```

## Utility Classes

### Spacing

```html
<div class="mb-4">   <!-- margin-bottom: 16px -->
<div class="mt-4">   <!-- margin-top: 16px -->
<div class="ml-2">   <!-- margin-left: 8px -->
<div class="mr-2">   <!-- margin-right: 8px -->
<div class="gap-4">  <!-- gap: 16px (in flex/grid) -->
<div class="p-4">    <!-- padding: 16px -->
```

### Flexbox

```html
<div class="flex">                    <!-- display: flex -->
<div class="flex items-center">       <!-- align-items: center -->
<div class="flex justify-between">    <!-- justify-content: space-between -->
<div class="flex flex-col">           <!-- flex-direction: column -->
<div class="flex gap-4">              <!-- gap: 16px -->
```

### Typography

```html
<span class="text-sm">      <!-- 14px -->
<span class="text-muted">   <!-- gray/muted color -->
<span class="font-mono">    <!-- monospace font -->
<span class="font-semibold"><!-- font-weight: 600 -->
```

### Icons

```html
{{ icon('check', size='16', class='icon-sm') }}   <!-- 16x16 -->
{{ icon('check', size='18') }}                     <!-- 18x18 (buttons) -->
{{ icon('check', size='20', class='icon-md') }}   <!-- 20x20 -->
{{ icon('check', size='24', class='icon-lg') }}   <!-- 24x24 -->
```

## Inline Style Rules

### ✅ ALLOWED

- Dynamic JavaScript values: `element.style.cursor = condition ? 'pointer' : 'default'`
- Style guide demos: Color swatches in documentation

### ❌ FORBIDDEN

| Inline Style | Use Instead |
|-------------|-------------|
| `style="display: flex"` | `class="flex"` |
| `style="margin-bottom: 16px"` | `class="mb-4"` |
| `style="color: var(--gray-500)"` | `class="text-muted"` |
| `style="width: 16px"` on SVG | `class="icon-sm"` |
| `style="max-width: 100px"` | `class="max-w-input-sm"` |
| `style="display: none"` (JS toggle) | `class="js-hidden"` |

## Pre-Commit Checklist

### Structure
- [ ] Extends `base.html`
- [ ] Has `{% block title %}` with convention: `Page - Section - pullDB`
- [ ] Has `{% block page_id %}`
- [ ] Modals in `{% block modals %}` (outside content)

### Security
- [ ] No hardcoded credentials
- [ ] All user input validated
- [ ] Destructive actions have confirmation

### Styling
- [ ] No inline styles where utilities exist
- [ ] Uses design tokens, not hardcoded colors
- [ ] Tested in light AND dark mode

### Accessibility
- [ ] Icon-only buttons have `title` AND `aria-label`
- [ ] Form inputs have `<label>` elements
- [ ] Color not sole indicator of state
- [ ] Images have `alt` text

### HCA
- [ ] File in correct layer directory
- [ ] Imports only from same or lower layers
- [ ] File name includes layer context

## State Patterns

### Empty State

When a list, table, or container has no data:

```html
<div class="empty-state">
    <div class="empty-state-icon">
        {{ icon('inbox', size='48', class='icon-muted') }}
    </div>
    <h3 class="empty-state-title">No jobs found</h3>
    <p class="empty-state-description">
        Create your first restore job to get started.
    </p>
    <div class="empty-state-action">
        <button class="btn btn-primary">
            {{ icon('plus', size='18') }} Create Job
        </button>
    </div>
</div>
```

#### Guidelines
- Use **descriptive title** explaining what's missing
- Add **helpful description** with next steps
- Include **CTA button** when appropriate
- Use **muted icon** (48px) to fill visual space

### Loading State

For async data fetching:

```html
<!-- Spinner overlay -->
<div class="loading-overlay">
    <div class="loading-spinner"></div>
    <span class="loading-text">Loading jobs...</span>
</div>

<!-- Inline spinner (buttons) -->
<button class="btn btn-primary" disabled>
    {{ icon('loader', size='18', class='animate-spin') }}
    Processing...
</button>

<!-- Skeleton loading (future) -->
<div class="skeleton skeleton-text"></div>
<div class="skeleton skeleton-rect"></div>
```

### Error State

Display errors clearly with recovery options:

```html
<div class="error-state">
    <div class="error-state-icon">
        {{ icon('alert-circle', size='48', class='text-error') }}
    </div>
    <h3 class="error-state-title">Failed to load data</h3>
    <p class="error-state-description">
        {{ error_message }}
    </p>
    <div class="error-state-action">
        <button class="btn btn-primary" onclick="location.reload()">
            {{ icon('refresh', size='18') }} Try Again
        </button>
    </div>
</div>
```

## Navigation Patterns

### Sidebar Navigation

The sidebar uses a **slide-out overlay** pattern:

```css
/* Trigger strip on left edge */
.sidebar-trigger {
    position: fixed;
    left: 0;
    width: 5px;
    height: calc(100vh - 60px - 40px); /* Between header/footer */
    background: linear-gradient(...); /* Animated gradient */
}

/* Slide-out panel */
.sidebar-nav {
    position: fixed;
    left: -240px;
    width: 240px;
    transition: left 0.3s ease;
}

.sidebar-nav.open {
    left: 0;
}
```

### Navigation Links

```html
<!-- Standard nav link -->
<a href="/admin/users" class="nav-link">
    {{ icon('users', size='18') }}
    <span class="nav-text">Users</span>
</a>

<!-- Active state (set by template or JS) -->
<a href="/admin/users" class="nav-link active">
    {{ icon('users', size='18') }}
    <span class="nav-text">Users</span>
</a>

<!-- With badge -->
<a href="/admin/jobs" class="nav-link">
    {{ icon('briefcase', size='18') }}
    <span class="nav-text">Jobs</span>
    <span class="nav-badge">5</span>
</a>
```

### Navigation Sections

```html
<nav class="sidebar-nav">
    <div class="nav-section">
        <h4 class="nav-section-title">Administration</h4>
        <a href="..." class="nav-link">...</a>
        <a href="..." class="nav-link">...</a>
    </div>
    <div class="nav-section">
        <h4 class="nav-section-title">Settings</h4>
        <a href="..." class="nav-link">...</a>
    </div>
</nav>
```

### Breadcrumbs

For hierarchical navigation:

```html
<nav class="breadcrumbs" aria-label="Breadcrumb">
    <ol class="breadcrumb-list">
        <li><a href="/admin">Admin</a></li>
        <li><a href="/admin/users">Users</a></li>
        <li aria-current="page">Edit User</li>
    </ol>
</nav>
```

---

# Part VII: Quality & Testing

## Testing Standards

### Test Organization

```
tests/
├── unit/           # Fast, isolated tests
│   ├── domain/     # Model/config tests
│   └── infra/      # Infrastructure mocks
├── integration/    # Tests with real DB/S3
│   ├── mysql/      # MySQL integration
│   └── s3/         # S3 integration
└── e2e/            # End-to-end workflows
```

### Test Naming

```python
def test_restore_job_completes_with_valid_backup():
    """Descriptive name indicating scenario and expected outcome."""
    pass

def test_restore_job_fails_when_backup_not_found():
    """Test failure scenarios explicitly."""
    pass
```

### Assertions

```python
# ✅ GOOD: Specific assertions with context
assert result.status == "complete", f"Expected complete, got {result.status}"
assert len(errors) == 0, f"Unexpected errors: {errors}"

# ❌ BAD: Bare assertions
assert result.status == "complete"
assert not errors
```

## Accessibility (a11y)

### Requirements

1. **Keyboard Navigation**: All interactive elements reachable via Tab
2. **Focus Indicators**: Visible focus states on all focusable elements
3. **Screen Readers**: Meaningful labels for all controls
4. **Color Contrast**: 4.5:1 minimum for text
5. **No Color-Only Indicators**: Always pair color with text/icons
6. **Reduced Motion**: Respect `prefers-reduced-motion`

### Focus Styles

```css
/* Global focus style (from reset.css) */
:focus-visible {
    outline: 2px solid var(--color-border-focus);
    outline-offset: 2px;
}

/* Remove focus outline when not keyboard-navigating */
:focus:not(:focus-visible) {
    outline: none;
}
```

### Reduced Motion Support

```css
/* From reset.css - disables animations for users who prefer reduced motion */
@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
    }
}
```

### Screen Reader Utilities

```html
<!-- Hide visually but keep accessible to screen readers -->
<span class="sr-only">Additional context for screen readers</span>

<!-- Skip link for keyboard users -->
<a href="#main-content" class="skip-link">Skip to main content</a>
```

### Implementation Examples

```html
<!-- ✅ GOOD: Accessible button -->
<button class="btn-icon" title="Delete job" aria-label="Delete job">
    {{ icon('trash-2', size='18') }}
</button>

<!-- ✅ GOOD: Accessible form with description -->
<label for="database-name" class="form-label">Database Name</label>
<input type="text" id="database-name" name="database_name" 
       aria-describedby="database-hint">
<p id="database-hint" class="form-hint">Target database for restore</p>

<!-- ✅ GOOD: Status with text, not just color -->
<span class="badge badge-failed">
    <span class="badge-dot"></span>
    Failed  <!-- Text label, not just red color -->
</span>

<!-- ✅ GOOD: Toast with role for screen readers -->
<div class="toast toast-success" role="alert">
    Settings saved successfully
</div>
```

### Accessibility Checklist

- [ ] All `<img>` elements have `alt` attributes
- [ ] All icon-only buttons have `title` AND `aria-label`
- [ ] Form inputs have associated `<label>` elements
- [ ] Color is never the sole indicator of state
- [ ] Interactive elements are keyboard accessible
- [ ] Focus states are visible
- [ ] Modals trap focus when open
- [ ] Links have descriptive text (not "click here")

## Animations & Transitions

### Transition Tokens

All transitions follow the **Doherty Threshold** (<400ms for perceived responsiveness):

| Token | Duration | Use Case |
|-------|----------|----------|
| `--transition-fast` | 150ms | Hovers, small state changes |
| `--transition-base` | 200ms | Default transitions |
| `--transition-slow` | 300ms | Page elements, larger changes |
| `--transition-slower` | 400ms | Maximum (complex animations) |

### Easing Curves

| Token | Curve | Use Case |
|-------|-------|----------|
| `--ease-in` | cubic-bezier(0.4, 0, 1, 1) | Elements exiting |
| `--ease-out` | cubic-bezier(0, 0, 0.2, 1) | Elements entering |
| `--ease-in-out` | cubic-bezier(0.4, 0, 0.2, 1) | Default (most natural) |
| `--ease-bounce` | cubic-bezier(0.68, -0.55, 0.265, 1.55) | Playful interactions |

### Built-in Animations

```css
/* From utilities.css */
.animate-spin    /* Continuous rotation (loading spinners) */
.animate-pulse   /* Opacity fade in/out (loading states) */
.animate-fade-in /* Fade in on mount */
```

### Loading Spinner

```html
<!-- Default size (14px) -->
<span class="loading-spinner"></span>

<!-- Small size (12px) - for buttons -->
<span class="loading-spinner loading-spinner--sm"></span>

<!-- Large size (20px) -->
<span class="loading-spinner loading-spinner--lg"></span>

<!-- Button with loading state -->
<button class="btn btn-primary" disabled>
    <span class="loading-spinner loading-spinner--sm"></span>
    Saving...
</button>
```

### Transition Utility Classes

```html
<div class="transition">         <!-- all var(--transition-base) -->
<div class="transition-fast">    <!-- all var(--transition-fast) -->
<div class="transition-slow">    <!-- all var(--transition-slow) -->
<div class="transition-none">    <!-- Disable transitions -->
```

## Layout Architecture

### CSS Grid App Shell

pullDB uses a CSS Grid "Pancake Stack" pattern for the main app layout:

```
┌─────────────────────────────────────────────────────┐
│                   .app-header                       │ auto
├──────┬──────────────────────────────────────────────┤
│      │           .page-header-bar                   │ auto
│      ├──────────────────────────────────────────────┤
│ 5px  │                                              │
│      │              .main-content                   │ 1fr
│      │                                              │
├──────┴──────────────────────────────────────────────┤
│                   .app-footer                       │ auto
└─────────────────────────────────────────────────────┘
```

### Layout Dimensions

| Token | Value | Element |
|-------|-------|---------|
| `--sidebar-width` | 220px | Full sidebar |
| `--sidebar-collapsed` | 3px | Collapsed accent bar |
| `--header-height` | 56px | App header |
| `--page-header-height` | 52px | Page header bar |
| `--footer-height` | 36px | Footer |

### Content Container Classes

```html
<!-- Main content area (from base.html) -->
<main class="main-content">
    <div class="content-body">
        {% block content %}{% endblock %}
    </div>
</main>

<!-- Feature page wrapper -->
<div class="feature-page">
    <!-- Page content -->
</div>
```

### Page Header Pattern

```html
<div class="page-header-row mb-4">
    <div class="page-header-left">
        <h1 class="page-title">
            {{ icon('layout-grid', size='20', class='icon-sm') }}
            Page Title
        </h1>
    </div>
    <div class="status-bar">
        <!-- Stats here -->
    </div>
</div>
```

### Z-Index Scale

| Token | Value | Use Case |
|-------|-------|----------|
| `--z-base` | 0 | Default content |
| `--z-dropdown` | 50 | Dropdown menus |
| `--z-sticky` | 100 | Sticky headers |
| `--z-fixed` | 200 | Fixed elements |
| `--z-modal-backdrop` | 400 | Modal backdrop |
| `--z-modal` | 500 | Modal content |
| `--z-popover` | 600 | Popovers |
| `--z-tooltip` | 700 | Tooltips |
| `--z-toast` | 800 | Toast notifications |

## Performance

### Frontend

1. **HTMX for Updates**: Avoid full page reloads
2. **Lazy Loading**: Virtualize long lists (`lazy_table` widget)
3. **Transitions**: 150-300ms maximum
4. **Asset Optimization**: CSS minified in production

### Backend

1. **Database Queries**: Use indexes, avoid N+1 queries
2. **Connection Pooling**: Reuse MySQL connections
3. **Async Operations**: Use `async/await` for I/O operations
4. **Caching**: Cache expensive computations (stats, counts)

---

# Quick Reference Card

```
SPACING            ICONS                TEXT                COLORS
──────────────     ──────────────────   ──────────────      ──────────────
mb-2 = 0.5rem     size='16' (inline)   text-2xs = 10px     primary-600
mb-4 = 1rem       size='18' (button)   text-xs = 12px      success-600  
mb-6 = 1.5rem     size='20' (default)  text-sm = 14px      warning-600
gap-4 = 1rem      size='24' (large)    text-base = 15px    danger-600
p-6 = 1.5rem      size='48' (empty)    text-muted          info-600

BUTTONS            BUTTON SIZES         ALERTS              AUTH DEPS
──────────────     ──────────────────   ──────────────      ──────────────
btn-primary       btn-xs (28px)        alert-error         get_session_user
btn-secondary     btn-sm (32px)        alert-success       require_login
btn-danger        (default 36px)       alert-warning       require_admin
btn-ghost         btn-lg (44px)        alert-info          require_manager_or_above
btn-icon
btn-icon-primary

CARDS              FORMS                MODALS              TABLES
──────────────     ──────────────────   ──────────────      ──────────────
card-header-left  form-group           modal-hidden        table / data-table
card-title        form-label           modal-visible       cell-primary
card-body         form-input           modal-content       cell-secondary
card-actions      form-select          modal-header        cell-mono-sm
no-padding        form-hint            modal-body          action-btn
                  is-valid             modal-footer        is-selected
                  is-invalid           modal-close         is-excluded

TRANSITIONS        ANIMATIONS           Z-INDEX             ACCESSIBILITY
──────────────     ──────────────────   ──────────────      ──────────────
transition-fast   animate-spin         z-dropdown (50)     sr-only
transition-base   animate-pulse        z-modal (500)       skip-link
transition-slow   animate-fade-in      z-toast (800)       aria-label
transition-none   loading-spinner                          aria-describedby

HCA LAYERS         USER ROLES           STATUS BADGES       HTMX
──────────────     ──────────────────   ──────────────      ──────────────
shared/           UserRole.USER        badge-queued        hx-get
entities/         UserRole.MANAGER     badge-running       hx-post
features/         UserRole.ADMIN       badge-complete      hx-target
widgets/          UserRole.SERVICE     badge-failed        hx-swap
pages/                                 badge-canceled      hx-trigger

STATE PATTERNS     DATE FORMATS         THEME               NAV
──────────────     ──────────────────   ──────────────      ──────────────
empty-state       data-format="datetime"  data-theme="dark"   nav-link
empty-state-icon  data-format="date"      data-theme="light"  nav-link.active
empty-state-title data-format="time"      theme-toggle        nav-section
error-state       data-format="short"                         nav-badge
loading-overlay   data-format="relative"                      breadcrumbs
```

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [STYLE-GUIDE.md](STYLE-GUIDE.md) | Complete visual design reference |
| [NEW-PAGE-TEMPLATE.md](NEW-PAGE-TEMPLATE.md) | Copy-paste page template |
| [hca.md](../.pulldb/standards/hca.md) | Full HCA specification |
| [python.md](../engineering-dna/standards/python.md) | Python coding standards |
| [fail-hard.md](../engineering-dna/protocols/fail-hard.md) | Error handling protocol |
| [KNOWLEDGE-POOL.md](KNOWLEDGE-POOL.md) | AWS/infra operational facts |

---

*pullDB Design Encyclopedia v1.5.0 | January 2026*
