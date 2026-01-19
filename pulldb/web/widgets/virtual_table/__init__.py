from __future__ import annotations

"""
VirtualTable Widget
===================
HCA Layer: widgets (Layer 3)

A reusable, high-performance virtual scrolling table with:
- Virtual scrolling for large datasets
- Multi-column sorting
- Status and column filtering
- Filter chips
- Keyboard navigation
- Paging controls

Files:
- virtual_table.js  - Main JavaScript class
- virtual_table.css - Styles
- virtual_table.html - Jinja template for easy inclusion
- README.md - Documentation

Usage:
    Include in your template:
    ```jinja
    {% include "widgets/virtual_table/virtual_table.html" %}
    ```
    
    Or include assets directly:
    ```html
    <link rel="stylesheet" href="/static/widgets/virtual_table/virtual_table.css">
    <script src="/static/widgets/virtual_table/virtual_table.js"></script>
    ```

See README.md for full documentation.
"""

__all__: list[str] = []  # No Python exports - this is a frontend widget
