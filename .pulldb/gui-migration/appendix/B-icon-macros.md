# Appendix B — Icon Macro Implementation

---

## Master Import (_index.html)

```jinja
{# partials/icons/_index.html #}
{% from 'partials/icons/shared.html' import icon_shared %}
{% from 'partials/icons/entities.html' import icon_entities %}
{% from 'partials/icons/features.html' import icon_features %}
{% from 'partials/icons/widgets.html' import icon_widgets %}
{% from 'partials/icons/pages.html' import icon_pages %}

{% macro icon(name, size='md', class='') %}
{%- set sizes = {'sm': '16', 'md': '20', 'lg': '24', 'xl': '32'} -%}
{%- set px = sizes.get(size, '20') -%}
{%- set result = none -%}

{# Try each category in order #}
{%- set result = icon_shared(name) -%}
{%- if not result -%}{%- set result = icon_entities(name) -%}{%- endif -%}
{%- if not result -%}{%- set result = icon_features(name) -%}{%- endif -%}
{%- if not result -%}{%- set result = icon_widgets(name) -%}{%- endif -%}
{%- if not result -%}{%- set result = icon_pages(name) -%}{%- endif -%}

{%- if result -%}
<svg class="icon icon-{{ size }} {{ class }}" width="{{ px }}" height="{{ px }}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
{{ result }}
</svg>
{%- else -%}
<!-- Icon not found: {{ name }} -->
{%- endif -%}
{% endmacro %}
```

---

## Shared Layer (shared.html)

```jinja
{# partials/icons/shared.html #}
{% macro icon_shared(name) %}
{%- if name == 'database' -%}
<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>
{%- elif name == 'server' -%}
<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>
{%- elif name == 'cloud' -%}
<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>
{%- elif name == 'folder' -%}
<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>
{%- elif name == 'globe' -%}
<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>
{%- elif name == 'cog' -%}
<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>
{%- endif -%}
{% endmacro %}
```

---

## Usage Example

```jinja
{% from 'partials/icons/_index.html' import icon %}

<div class="stat-card">
    <div class="stat-icon stat-icon-primary">
        {{ icon('database', size='lg') }}
    </div>
    <div class="stat-content">
        <div class="stat-value">42</div>
        <div class="stat-label">Databases</div>
    </div>
</div>
```

---

## Creating Additional Layer Files

Follow same pattern for `entities.html`, `features.html`, `widgets.html`, `pages.html`.

See `appendix/C-icon-inventory.md` for complete list of icons per layer.
