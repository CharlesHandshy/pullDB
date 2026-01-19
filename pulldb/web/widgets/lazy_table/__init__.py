from __future__ import annotations

"""
LazyTable Widget
================
HCA Layer: widgets (Layer 3)

A server-side lazy-loading table with:
- Cache windowing (3x buffer, full cache clear on invalidation)
- Column sort/filter controls in headers
- Fixed header/footer with flex layout (tbody fills space)
- Optional row selection with full-dataset "Select All"
- Selection persistence across filter/sort changes
- Virtual action cell columns for row-level buttons

Files:
- /static/widgets/lazy_table/lazy_table.js  - Main JavaScript class
- /static/widgets/lazy_table/lazy_table.css - Styles  
- /templates/widgets/lazy_table/lazy_table.html - Jinja template

Usage:
    Include in your template:
    ```jinja
    {% include "widgets/lazy_table/lazy_table.html" %}
    ```
    
    Then initialize with JavaScript:
    ```javascript
    const table = new LazyTable({
        container: document.getElementById('my-table'),
        columns: [...],
        fetchUrl: '/api/jobs',
        selectable: true,
        selectionMode: 'multiple'
    });
    ```

See inline documentation for full configuration options.
"""

__all__: list[str] = []  # No Python exports - this is a frontend widget
