# pullDB Web Layout Architecture

> **Version**: 0.2.0 | **Updated**: January 2026

## Layout Wireframe

```
┌───────────────────────────────────────────────────────────────────┐
│3│               │          PAGE HEADER BAR                        │
│p│  [Video Logo] │ Page Title              │                       │
│x│               │ Subtitle                │           [Login Info]│
│ ├─────┐───────────────────────────────────────────────────────────┤
│ │ S   │                                                           │
│ │ I   │                                                           │
│ │ D   │                                                           │
│ │ E   │                                                           │
│ │ B   │                    WORK AREA                              │
│ │ A   │                  (content-body)                           │
│ │ R   │                                                           │
│ │     │               Scrolls independently                       │
│ │ H   │                                                           │
│ │ O   │                                                           │
│ │ V   ├───────────────────────────────────────────────────────────┤
│ │ E   │ © 2025 pullDB • v0.2.0              Docs    GitHub        │
│ │ R   │ Service Titan / Field Routes  FOOTER                      │
└───────┴───────────────────────────────────────────────────────────┘
```

## Component Hierarchy

```
.app-layout
├── .attention-strip          (3px fixed left, full height)
└── .app-main                 (right of strip)
    ├── .page-header-bar      (full width, sticky top)
    │   ├── .page-header-logo (video: pullDB_logo.mp4)
    │   ├── .page-header-divider
    │   ├── .page-header-content
    │   │   ├── .page-header-titles
    │   │   │   ├── h1.page-title
    │   │   │   └── p.page-subtitle
    │   │   └── .header-actions
    │   └── .header-user      (login info, right side)
    │       ├── .header-user-avatar
    │       ├── username
    │       ├── .role-badge
    │       └── a.header-logout
    └── .app-body             (flex container)
        ├── .sidebar          (hover-reveal, overlays content)
        │   └── .sidebar-inner
        │       ├── .sidebar-header (logo)
        │       ├── .sidebar-nav (navigation links)
        │       └── .sidebar-footer (user menu)
        └── .main-content
            ├── {% block content %}
            └── .app-footer
                ├── .footer-row (copyright, version, links)
                └── .footer-row (Service Titan / Field Routes)
```

## Key CSS Variables

```css
--sidebar-width: 220px;
--sidebar-collapsed: 3px;
--header-height: 56px;
--page-header-height: 52px;
```

## Sidebar Behavior

1. **Default State**: 12px invisible trigger zone overlays content
2. **3px Strip**: Always visible gradient accent on far left
3. **Hover**: Expands to 220px, overlays work area with shadow
4. **Content Fade**: Inner content fades in after expansion starts

```css
.sidebar {
    width: 12px;           /* Hover detection zone */
    background: transparent; /* Invisible until hover */
    position: fixed;
    top: var(--page-header-height);
    left: 3px;
}

.sidebar:hover {
    width: var(--sidebar-width);
    background: var(--gray-900);
    box-shadow: var(--shadow-xl);
}
```

## Template Blocks

Child pages can override these blocks:

```jinja
{% block header_title %}Page Title{% endblock %}
{% block header_subtitle %}<p class="page-subtitle">Description</p>{% endblock %}
{% block header_actions %}<!-- Buttons/controls -->{% endblock %}
{% block content %}<!-- Main page content -->{% endblock %}
```

## Static Assets

| Asset | Path | Purpose |
|-------|------|---------|
| Logo Video | `/static/images/pullDB_logo.mp4` | Animated header logo |
| Logo PNG | `/static/images/pullDB_logo.png` | Fallback logo |
| Favicons | `/static/images/favicon-*.png` | Browser icons |
| ServiceTitan Logo | `/static/images/servicetitan-logo.svg` | Footer branding |
| FieldRoutes Logo | `/static/images/fieldroutes-logo.svg` | Footer branding |

## Responsive Behavior

```css
@media (max-width: 768px) {
    .page-header-bar { padding: 0 var(--space-3); }
    .page-header-logo video { height: 28px; }
    .page-title { font-size: 1rem; }
    .content-body { padding: var(--space-3); }
    .stats-grid { grid-template-columns: 1fr; }
}
```

## Implementation Files

- **Base Template**: `pulldb/web/templates/base.html`
- **Design Tokens**: CSS variables in `<style>` block
- **Static Files**: `pulldb/images/` → served at `/static/images/`
