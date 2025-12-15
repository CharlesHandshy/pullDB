# 04 — Implementation Instructions

> Step-by-step instructions for each PR. Follow exactly.

---

## PR 0: Tooling & Baseline

### Step 1: Verify audit scripts
```bash
python3 scripts/audit_inline_svgs.py --output json > /tmp/svg-audit.json
python3 scripts/audit_inline_css.py --output json > /tmp/css-audit.json
python3 scripts/validate_template_paths.py --json > /tmp/path-violations.json
```

### Step 2: Categorize unknown icons
```bash
python3 scripts/audit_inline_svgs.py | grep -A5 "Unknown Layer"
```
For each unknown: find in template, identify purpose, add to appropriate category.

### Step 3: Add E2E tests to CI
Edit `.github/workflows/release-build.yml`:
```yaml
- name: E2E Tests
  run: |
    pip install playwright
    playwright install chromium
    pytest tests/e2e/ -v
```

### Step 4: Capture baseline
```bash
python3 scripts/capture_styleguide.py
```

**Validation**: All 101 icons categorized, E2E passes, CI updated.

---

## PR 1: Foundation

### Step 1: Create icon structure
```bash
mkdir -p pulldb/web/templates/partials/icons
```

### Step 2: Create icon files
Create `_index.html`, `shared.html`, `entities.html`, `features.html`, `widgets.html`, `pages.html` with macros from appendix/B-icon-macros.md.

### Step 3: Add CSS to design-system.css
```css
/* Utility classes */
.w-100 { width: 100%; }
.h-100 { height: 100%; }
.opacity-75 { opacity: 0.75; }

/* Accessibility */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        transition-duration: 0.01ms !important;
    }
}

.skip-link {
    position: absolute;
    top: -40px;
    left: 0;
    padding: var(--space-2) var(--space-4);
    background: var(--primary-600);
    color: white;
    z-index: 100;
}
.skip-link:focus { top: 0; }
```

### Step 4: Add CSS to components.css
```css
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--space-4); }
.stat-card { background: white; border: 1px solid var(--gray-200); border-radius: var(--radius-lg); padding: var(--space-4); display: flex; align-items: center; gap: var(--space-4); }
.stat-icon { width: 48px; height: 48px; border-radius: var(--radius-lg); display: flex; align-items: center; justify-content: center; }
.stat-icon-primary { background: var(--primary-50); color: var(--primary-600); }
.stat-icon-success { background: var(--success-50); color: var(--success-600); }

.alert { padding: var(--space-3) var(--space-4); border-radius: var(--radius-lg); display: flex; gap: var(--space-3); }
.alert-error { background: var(--danger-50); border: 1px solid var(--danger-100); color: var(--danger-700); }
.alert-success { background: var(--success-50); border: 1px solid var(--success-100); color: var(--success-700); }
```

### Step 5: Create dark-mode.css
See appendix/D-dark-mode-colors.md for full content.

### Step 6: Update base.html
```html
<html lang="en" data-theme="light">
<head>
    <link rel="stylesheet" href="/static/css/dark-mode.css">
</head>
<body>
    <a href="#main-content" class="skip-link">Skip to main content</a>
    <main id="main-content">{% block content %}{% endblock %}</main>
</body>
```

**Validation**: `{{ icon('database') }}` renders, skip link works, stat cards display.

---

## PR 2: Auth Feature

### Step 1: Enhance login template
Edit `features/auth/login.html` — use CSS Grid, remove Bootstrap.

### Step 2: Delete Bootstrap login
```bash
rm pulldb/web/templates/login.html
```

### Step 3: Replace inline SVGs with `{{ icon('...') }}`

**Validation**: Login works, no Bootstrap CDN, redirects work.

---

## PR 3: Dashboard Feature

### Step 1: Extract CSS from dashboards
Copy `<style>` from `_admin_dashboard.html` to `components.css`, delete inline.

### Step 2: Convert to stat cards
```html
<div class="stats-grid">
    <div class="stat-card">
        <div class="stat-icon stat-icon-primary">{{ icon('users-group') }}</div>
        <div class="stat-content">
            <div class="stat-value">{{ stats.active_users }}</div>
            <div class="stat-label">Active Users</div>
        </div>
    </div>
</div>
```

### Step 3: Repeat for manager and user dashboards

**Validation**: All dashboards display, stat cards have icons.

---

## PR 4: Jobs Feature

### Step 1: Move templates
```bash
mv pulldb/web/templates/my_job.html pulldb/web/templates/features/jobs/detail.html
mv pulldb/web/templates/my_jobs.html pulldb/web/templates/features/jobs/my_jobs.html
mv pulldb/web/templates/job_profile.html pulldb/web/templates/features/jobs/profile.html
mv pulldb/web/templates/job_history.html pulldb/web/templates/features/jobs/history.html
```

### Step 2: Update routes
Change all `TemplateResponse` paths in `features/jobs/routes.py`.

### Step 3: Extract CSS, replace icons

**Validation**: All job pages load, cancel works, no 404s.

---

## PR 5: Restore + QA Template ⚠️

### Step 1: Find QA Template code
```bash
grep -n "qatemplate" pulldb/web/templates/restore.html
```

### Step 2: Port to features/restore/restore.html

**Add tab button**:
```html
<button type="button" class="form-tab" data-tab="qatemplate">
    {{ icon('database') }} QA Template
</button>
```

**Add tab content**:
```html
<div class="tab-content" id="tab-qatemplate">
    <div class="form-group">
        <label class="form-label">QA Extension (3 letters)</label>
        <input type="text" name="qa_extension" maxlength="3" pattern="[a-zA-Z]{3}">
        <p class="form-hint" id="qa-extension-hint">Target: {user_code}_qatemplate_XXX</p>
    </div>
</div>
```

**Add hidden input**:
```html
<input type="hidden" name="qatemplate" value="false" id="qatemplate-input">
```

**Add JavaScript**:
```javascript
document.querySelectorAll('.form-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        const tabId = tab.dataset.tab;
        document.getElementById('qatemplate-input').value = tabId === 'qatemplate' ? 'true' : 'false';
        if (tabId === 'qatemplate') {
            selectedCustomer = { id: 'qatemplate', name: 'QA Template', isQaTemplate: true };
            loadBackups({ id: 'qatemplate', name: 'QA Template' });
        }
    });
});
```

### Step 3: Delete root restore.html
```bash
rm pulldb/web/templates/restore.html
```

**Validation**: Customer restore works, **QA Template restore works** (CRITICAL).

---

## PR 6-13: See original document

Remaining PRs follow same pattern:
1. Move templates to `features/`
2. Update routes
3. Extract inline CSS
4. Replace inline SVGs with `{{ icon() }}`
5. Delete old files
6. Validate functionality
