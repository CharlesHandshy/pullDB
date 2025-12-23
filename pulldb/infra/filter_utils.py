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

from collections.abc import Callable
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


def apply_cascading_filters(
    items: list[dict[str, Any]],
    filters: dict[str, list[str]],
    filter_order: list[str],
    queried_column: str,
    column_getter: Callable[[dict[str, Any], str], str] | None = None,
) -> list[dict[str, Any]]:
    """Apply filters in order-aware cascading fashion.

    Only filters from columns that appear BEFORE queried_column in filter_order
    are applied. This enables hierarchical/cascading filter dropdowns.

    Args:
        items: List of row dicts to filter
        filters: Dict of {column_key: [filter_values]} - values should be lowercase
        filter_order: List of column keys in the order they were selected
        queried_column: The column we're getting distinct values for
        column_getter: Optional custom function (item, col) -> str to get column value
                      Defaults to str(item.get(col, "")).lower()

    Returns:
        Filtered list where items match ALL applicable filters (AND logic between
        columns that precede queried_column in the order)

    Example:
        # User selected filters in this order: status, dbhost, user
        filter_order = ["status", "dbhost", "user"]

        # Getting distinct values for "user" column:
        # Only status and dbhost filters apply (they come before "user")
        apply_cascading_filters(items, filters, filter_order, "user")

        # Getting distinct values for "status" column:
        # No filters apply (status is first in order)
        apply_cascading_filters(items, filters, filter_order, "status")
    """
    if not filters or not filter_order:
        return items

    # Find which filters should apply (only those BEFORE queried_column in order)
    applicable_columns: list[str] = []
    for col in filter_order:
        if col == queried_column:
            break  # Stop at the queried column
        if filters.get(col):
            applicable_columns.append(col)

    if not applicable_columns:
        return items

    def get_value(item: dict[str, Any], col: str) -> str:
        if column_getter:
            return column_getter(item, col)
        return str(item.get(col, "")).lower()

    filtered: list[dict[str, Any]] = []
    for item in items:
        match = True
        for col in applicable_columns:
            cell = get_value(item, col)
            filter_vals = filters[col]
            # OR logic within column: match if ANY filter value is found
            if not any(fv in cell for fv in filter_vals):
                match = False
                break  # AND logic between columns: fail fast
        if match:
            filtered.append(item)

    return filtered


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
            filter_order = [c.strip() for c in str(value).split(",") if c.strip()]
        elif key.startswith("filter_") and value:
            col_key = key[7:]  # Remove "filter_" prefix
            # Skip date range suffixes
            if col_key.endswith("_after") or col_key.endswith("_before"):
                continue
            if col_key in exclude:
                continue
            filters[col_key] = parse_multi_value_filter(str(value))

    return filters, filter_order
