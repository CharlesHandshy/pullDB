# 02 — Architecture Decisions

> These decisions are FINAL. Do not revisit during implementation.

---

## Decision 1: Icon System — HCA Layer Organization

**Decision**: Organize icons by HCA layer, not by visual category.

```
templates/partials/icons/
├── _index.html       # Master import with icon() macro
├── shared.html       # Infrastructure: database, server, cloud (~15)
├── entities.html     # Data models: user, key, lock, shield (~16)
├── features.html     # Business logic: search, download, trash (~18)
├── widgets.html      # UI components: chevrons, spinner (~20)
└── pages.html        # Navigation: dashboard, home, logout (~12)
```

**Usage**:
```jinja
{% from 'partials/icons/_index.html' import icon %}
{{ icon('database', size='md', class='text-primary') }}
```

**Rationale**: Follows existing HCA project architecture, intuitive discovery.

---

## Decision 2: Theme Storage — Global Admin Settings

**Decision**: Store in `SETTING_REGISTRY` with `SettingCategory.APPEARANCE`.

**New Settings**:
| Key | Type | Default |
|-----|------|---------|
| `theme_mode` | STRING | `"system"` |
| `primary_color_hue` | INTEGER | `217` (blue) |
| `accent_color_hue` | INTEGER | `142` (green) |

**Rationale**: Single source of truth, admin control, integrates with existing infrastructure.

---

## Decision 3: CSS Variables — Generated Endpoint

**Decision**: Dynamic `/web/theme.css` endpoint over inline injection.

| Factor | Inline | Generated Endpoint ✓ |
|--------|--------|---------------------|
| Browser Caching | ❌ | ✅ |
| HTML Payload | ❌ Larger | ✅ Separate |
| Cache Invalidation | ❌ Manual | ✅ ETag |
| CDN Compatible | ❌ | ✅ |

**Implementation**:
- Route: `GET /web/theme.css`
- Content-Type: `text/css`
- Cache-Control: `public, max-age=3600`
- ETag: SHA256 of settings values

**Rationale**: Long-term scalability, browser caching reduces load.

---

## Decision 4: Dark Mode — CSS Custom Properties

**Decision**: Use `[data-theme="dark"]` selector with inverted variables.

```css
[data-theme="dark"] {
    --gray-50: #111214;  /* Was #f9fafb */
    --gray-900: #f9fafb; /* Was #111827 */
    /* ... full inversion ... */
}
```

**Toggle**: localStorage + system preference detection.

**Rationale**: No JavaScript required for colors, respects user preference.

---

## Decision 5: Template Migration — Direct Delete

**Decision**: Delete duplicate templates immediately after migration.

- No deprecation warnings
- No sunset period
- No redirects

**Rationale**: Pre-release software, no external users to accommodate.

---

## Decision 6: Audit Scripts

**Created scripts** for ongoing validation:

| Script | Purpose |
|--------|---------|
| `audit_inline_svgs.py` | Find all inline SVGs |
| `audit_inline_css.py` | Find `<style>` blocks |
| `validate_template_paths.py` | Enforce HCA paths |

Run these before/after each PR.
