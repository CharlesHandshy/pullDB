# Theme System

> **Version**: 1.0.1 | **Last Updated**: January 2026

pullDB's theme system provides consistent Light and Dark mode support through semantic CSS variables and automated theme generation.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [CSS Variable System](#css-variable-system)
4. [Theme Switching](#theme-switching)
5. [ColorSchema Python API](#colorschema-python-api)
6. [Adding New Styles](#adding-new-styles)
7. [Theme Compliance](#theme-compliance)
8. [Customization](#customization)

---

## Overview

### Key Features

- **Light/Dark modes**: Full support for both color schemes
- **Semantic variables**: 147+ named design tokens
- **Automatic switching**: Respects system preference
- **User override**: Manual toggle via UI
- **Persistence**: Saves preference to localStorage

### How It Works

1. **ColorSchema** (Python) defines color values for light/dark modes
2. **Theme Generator** produces CSS variable files
3. **Design Tokens** provide the raw palette
4. **Components** use semantic `var(--color-*)` references
5. **Theme Switcher** toggles `data-theme` attribute on `<html>`

---

## Architecture

### File Structure

```
pulldb/web/static/css/
├── shared/
│   ├── design-tokens.css      # Raw color/spacing/font palette (147+ variables)
│   ├── manifest.css           # Import aggregator
│   ├── reset.css              # Browser normalization
│   ├── layout.css             # Layout using variables
│   ├── utilities.css          # Utility classes
│   └── fonts.css              # Font definitions
│
├── generated/
│   ├── manifest-light.css     # Generated light theme
│   ├── manifest-dark.css      # Generated dark theme
│   └── version.txt            # Cache-buster
│
├── features/                  # Feature styles (use variables)
├── widgets/                   # Widget styles (use variables)
├── pages/                     # Page-specific styles
└── entities/                  # Entity-specific styles
```

### Generation Pipeline

```
ColorSchema (Python)
       │
       ▼
theme_generator.py
       │
       ├──► manifest-light.css
       ├──► manifest-dark.css
       └──► version.txt
```

---

## CSS Variable System

### Variable Categories

| Category | Prefix | Examples |
|----------|--------|----------|
| **Surface** | `--color-surface-*` | surface, surface-hover, surface-subtle |
| **Background** | `--color-bg-*` | bg-primary, bg-secondary, bg-tertiary |
| **Text** | `--color-text-*` | text-primary, text-secondary, text-muted |
| **Border** | `--color-border-*` | border, border-light, border-focus |
| **Status** | `--color-{status}` | success, error, warning, info |
| **Interactive** | `--color-{action}` | primary, primary-hover, accent |
| **Input** | `--color-input-*` | input-bg, input-border, input-focus |
| **Link** | `--color-link-*` | link, link-hover, link-visited |
| **Code** | `--color-code-*` | code-bg, code-text, code-border |
| **Table** | `--color-table-*` | table-header-bg, table-row-hover |
| **Scrollbar** | `--color-scrollbar-*` | scrollbar-track, scrollbar-thumb |
| **Shadows** | `--shadow-*` | shadow-sm, shadow-md, shadow-lg |

### Using Variables

**Correct:**
```css
.card {
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  color: var(--color-text-primary);
}
```

**Incorrect (hardcoded):**
```css
/* DON'T DO THIS */
.card {
  background-color: #ffffff;
  border: 1px solid #e5e7eb;
  color: #1f2937;
}
```

### Common Variables Reference

```css
/* Surfaces */
--color-surface          /* Card backgrounds */
--color-surface-hover    /* Hover state */
--color-bg-primary       /* Page background */

/* Text */
--color-text-primary     /* Main text */
--color-text-secondary   /* Labels, hints */
--color-text-muted       /* Disabled, placeholder */

/* Borders */
--color-border           /* Standard borders */
--color-border-light     /* Subtle dividers */
--color-border-focus     /* Focus rings */

/* Status */
--color-success          /* Success text/icons */
--color-success-bg       /* Success backgrounds */
--color-error            /* Error text/icons */
--color-error-bg         /* Error backgrounds */
--color-warning          /* Warning text/icons */
--color-info             /* Info text/icons */

/* Interactive */
--color-primary          /* Primary buttons */
--color-primary-hover    /* Primary hover */
--color-accent           /* Accent color */
```

---

## Theme Switching

### How Theme is Detected

1. **Check localStorage** for `pulldb-theme` preference
2. **Check system preference** via `prefers-color-scheme`
3. **Default to light** if neither set

### Setting Theme Attribute

Theme is set via `data-theme` attribute on `<html>`:

```html
<html data-theme="light">  <!-- Light mode -->
<html data-theme="dark">   <!-- Dark mode -->
```

### JavaScript API

```javascript
// Get current theme
const theme = document.documentElement.getAttribute('data-theme') || 'light';

// Set theme
function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('pulldb-theme', theme);
}

// Toggle theme
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  setTheme(current === 'dark' ? 'light' : 'dark');
}

// Respect system preference
function initTheme() {
  const stored = localStorage.getItem('pulldb-theme');
  if (stored) {
    setTheme(stored);
  } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    setTheme('dark');
  }
}
```

### Theme Toggle Button

Located in the sidebar/header. Implementation:

```html
<button onclick="toggleTheme()" title="Toggle dark mode">
  <span class="theme-icon-light">☀️</span>
  <span class="theme-icon-dark">🌙</span>
</button>
```

---

## ColorSchema Python API

### Location

`pulldb/domain/color_schemas.py`

### Data Classes

```python
@dataclass
class SurfaceColors:
    default: str    # Main surface
    hover: str      # Hover state
    subtle: str     # Subtle backgrounds
    primary: str    # Primary surface
    secondary: str  # Secondary surface

@dataclass
class TextColors:
    primary: str    # Main text
    secondary: str  # Secondary text
    muted: str      # Muted/disabled
    inverse: str    # On dark backgrounds
    base: str       # Base size

@dataclass
class StatusColors:
    success: str
    success_bg: str
    success_border: str
    error: str
    error_bg: str
    error_border: str
    warning: str
    warning_bg: str
    warning_border: str
    info: str
    info_bg: str
    info_border: str

@dataclass
class ColorSchema:
    name: str
    surface: SurfaceColors
    background: BackgroundColors
    text: TextColors
    border: BorderColors
    status: StatusColors
    interactive: InteractiveColors
    input: InputColors
    link: LinkColors
    code: CodeColors
    table: TableColors
    scrollbar: ScrollbarColors
    shadows: ShadowColors
```

### Preset Schemas

Built-in color schemas are defined in `pulldb/domain/color_schemas.py`:

**Light Mode Presets:**
- `Default` - Standard professional light theme
- `Warm` - Warmer color temperature
- `Cool` - Cooler/blue-tinted theme

**Dark Mode Presets:**
- `Default` - Standard dark theme
- `Midnight Blue` - Deep blue dark theme
- `OLED Black` - True black for OLED displays
- `Solarized Dark` - Classic Solarized color scheme

```python
from pulldb.domain.color_schemas import get_preset_names, get_preset

# Get available preset names
light_presets = get_preset_names("light")  # ["Default", "Warm", "Cool"]
dark_presets = get_preset_names("dark")    # ["Default", "Midnight Blue", ...]

# Get a specific preset
schema = get_preset("dark", "OLED Black")
```

---

## Adding New Styles

### Step-by-Step

1. **Never use hardcoded colors**
2. **Find appropriate semantic variable** (or request new one)
3. **Use `var()` syntax**
4. **Test both light and dark modes**

### Example: New Component

```css
/* ✅ CORRECT */
.my-widget {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  color: var(--color-text-primary);
  box-shadow: var(--shadow-md);
}

.my-widget:hover {
  background: var(--color-surface-hover);
  border-color: var(--color-border-hover);
}

.my-widget-title {
  color: var(--color-text-primary);
}

.my-widget-subtitle {
  color: var(--color-text-secondary);
}
```

### Adding Dark Mode Override (Avoid if Possible)

If you must add mode-specific styles (prefer semantic variables):

```css
/* Last resort - prefer semantic variables */
[data-theme="dark"] .special-case {
  background: linear-gradient(var(--gray-900), var(--gray-800));
}
```

---

## Theme Compliance

### Compliance Levels

| Status | Meaning |
|--------|---------|
| ✅ | Fully compliant - uses only `var(--color-*)` |
| ⚠️ | Partial - has `[data-theme]` overrides |
| ❌ | Non-compliant - hardcoded hex colors |
| 🔧 | Acceptable - design tokens (source of truth) |

### Pre-Commit Validation

The `audit_theme_conformity.py` script runs on commit:

```bash
# Manual check
python scripts/audit_theme_conformity.py
```

**What it checks:**
1. No hardcoded hex colors in CSS (except design-tokens.css)
2. No hardcoded hex colors in HTML templates
3. Warnings for `[data-theme]` selectors

### Tracking Document

See [THEME-CONFORMITY-INDEX.md](../../docs/THEME-CONFORMITY-INDEX.md) for:
- Full file compliance inventory
- Remediation queue
- ColorSchema variable coverage

---

## Customization

### Admin Theme Settings

Administrators can customize theme colors via:
**Admin → Settings → Appearance**

Available customizations:
- Surface colors (3 tokens)
- Background colors (3 tokens)
- Text colors (3 tokens)
- Border colors (3 tokens)
- Status colors (4 tokens)
- Interactive colors (3 tokens)

### Applying Custom Schema

Custom schemas are stored in settings and applied via:

```javascript
// Load custom schema
fetch('/api/settings/theme')
  .then(r => r.json())
  .then(schema => applyCustomTheme(schema));

function applyCustomTheme(schema) {
  const root = document.documentElement;
  for (const [key, value] of Object.entries(schema)) {
    root.style.setProperty(`--color-${key}`, value);
  }
}
```

---

## Troubleshooting

### Theme Not Switching

1. Check `data-theme` attribute on `<html>`
2. Clear localStorage: `localStorage.removeItem('pulldb-theme')`
3. Hard refresh (Ctrl+Shift+R)

### Hardcoded Colors Appearing

1. Run compliance audit: `python scripts/audit_theme_conformity.py`
2. Check for inline styles in templates
3. Search for hex values: `grep -rn "#[0-9a-f]{6}" pulldb/web`

### Variable Not Applied

1. Check variable name spelling
2. Ensure CSS file is imported in manifest
3. Check browser DevTools for computed value

---

## See Also

- [THEME-CONFORMITY-INDEX.md](../../docs/THEME-CONFORMITY-INDEX.md) - Compliance tracking
- [STYLE-GUIDE.md](../../docs/STYLE-GUIDE.md) - CSS conventions
- [LazyTable](lazy-table.md) - Widget theme integration
