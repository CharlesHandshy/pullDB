"""Cascading Filter Utilities for LazyTable Endpoints.

HCA Layer: shared (Layer 0) - Infrastructure

Provides order-aware cascading filter logic for distinct value endpoints.
When fetching distinct values for column X, only filters from columns that
were selected BEFORE X in the filter order are applied. This creates a
hierarchical filtering experience where:
  1. First-selected column shows ALL its values
  2. Second-selected column shows values filtered by first
  3. Third-selected column shows values filtered by first AND second
  ...and so on.
"""

from __future__ import annotations

from typing import Any


def parse_multi_value_filter(filter_value: str | None) -> list[str]:
    """Parse comma-separated filter value into list of lowercase values.

    Args:
        filter_value: Comma-separated filter string or None

    Returns:
        List of lowercase stripped values, empty list if None/empty
    """
    if not filter_value:
        return []
    return [v.strip().lower() for v in filter_value.split(",") if v.strip()]


def extract_filter_params(
    query_params: dict[str, Any] | Any,
    exclude_columns: set[str] | None = None,
) -> tuple[dict[str, list[str]], list[str]]:
    """Extract filter parameters and filter order from request query params.

    Looks for query params matching:
      - filter_<column>=value1,value2  (comma-separated multi-value)
      - filter_order=col1,col2,col3    (ordered column list)

    Args:
        query_params: Dict-like object with query parameters
        exclude_columns: Set of column names to exclude from filters

    Returns:
        Tuple of (filters_dict, filter_order_list)
        - filters_dict: {column: [lowercase_values]}
        - filter_order_list: [column_names] in selection order
    """
    exclude = exclude_columns or set()
    filters: dict[str, list[str]] = {}
    filter_order: list[str] = []

    # Handle both dict and Starlette QueryParams
    items: list[tuple[str, str]] = []
    if hasattr(query_params, "items"):
        items = list(query_params.items())

    for key, value in items:
        if key == "filter_order" and value:
            cols = [c.strip() for c in str(value).split(",") if c.strip()]
            filter_order = cols[:32]  # cap: no table has more than 32 filterable columns
        elif key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            # Skip date range suffixes
            if col_key.endswith("_after") or col_key.endswith("_before"):
                continue
            if col_key in exclude:
                continue
            filters[col_key] = parse_multi_value_filter(str(value))

    return filters, filter_order
