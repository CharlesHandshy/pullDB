# Appendix D — Dark Mode Colors

---

## Gray Scale Inversion

| Variable | Light | Dark |
|----------|-------|------|
| `--gray-25` | #fcfcfd | #0a0a0b |
| `--gray-50` | #f9fafb | #111214 |
| `--gray-100` | #f3f4f6 | #1a1c20 |
| `--gray-200` | #e5e7eb | #252830 |
| `--gray-300` | #d1d5db | #3a3f4a |
| `--gray-400` | #9ca3af | #6b7280 |
| `--gray-500` | #6b7280 | #9ca3af |
| `--gray-600` | #4b5563 | #d1d5db |
| `--gray-700` | #374151 | #e5e7eb |
| `--gray-800` | #1f2937 | #f3f4f6 |
| `--gray-900` | #111827 | #f9fafb |
| `--gray-950` | #030712 | #fcfcfd |

---

## Semantic Colors

| Variable | Light | Dark |
|----------|-------|------|
| `--primary-50` | #eff6ff | #172554 |
| `--primary-100` | #dbeafe | #1e3a5f |
| `--primary-600` | #2563eb | #60a5fa |
| `--success-50` | #f0fdf4 | #052e16 |
| `--success-100` | #dcfce7 | #14532d |
| `--success-600` | #16a34a | #4ade80 |
| `--danger-50` | #fef2f2 | #450a0a |
| `--danger-100` | #fee2e2 | #7f1d1d |
| `--danger-600` | #dc2626 | #f87171 |
| `--warning-50` | #fffbeb | #451a03 |
| `--warning-100` | #fef3c7 | #78350f |
| `--warning-600` | #d97706 | #fbbf24 |

---

## dark-mode.css Implementation

```css
/* pulldb/web/static/css/dark-mode.css */

[data-theme="dark"] {
    /* Gray scale inversion */
    --gray-25: #0a0a0b;
    --gray-50: #111214;
    --gray-100: #1a1c20;
    --gray-200: #252830;
    --gray-300: #3a3f4a;
    --gray-400: #6b7280;
    --gray-500: #9ca3af;
    --gray-600: #d1d5db;
    --gray-700: #e5e7eb;
    --gray-800: #f3f4f6;
    --gray-900: #f9fafb;
    --gray-950: #fcfcfd;
    
    /* Semantic backgrounds */
    --primary-50: #172554;
    --primary-100: #1e3a5f;
    --success-50: #052e16;
    --danger-50: #450a0a;
    --warning-50: #451a03;
    
    /* Surfaces */
    --surface-primary: var(--gray-900);
    --surface-secondary: var(--gray-800);
    
    /* Text */
    --text-primary: var(--gray-50);
    --text-secondary: var(--gray-400);
    
    /* Shadows (reduced) */
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
    --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.4);
}
```

---

## Theme Toggle JavaScript

```javascript
// pulldb/web/static/js/theme.js

const STORAGE_KEY = 'pulldb-theme';
const DEFAULT_THEME = document.documentElement.dataset.defaultTheme || 'system';

function getSystemTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getEffectiveTheme(preference) {
    return preference === 'system' ? getSystemTheme() : preference;
}

function setTheme(preference) {
    const effective = getEffectiveTheme(preference);
    document.documentElement.setAttribute('data-theme', effective);
    localStorage.setItem(STORAGE_KEY, preference);
}

function cycleTheme() {
    const current = localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME;
    const next = current === 'light' ? 'dark' : current === 'dark' ? 'system' : 'light';
    setTheme(next);
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setTheme(localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME);
    document.getElementById('theme-toggle')?.addEventListener('click', cycleTheme);
});
```
