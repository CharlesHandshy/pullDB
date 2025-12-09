"""Searchable dropdown widget for type-ahead search/select functionality.

HCA Layer: widgets
Provides a standard, reusable searchable dropdown component for all pages.
Implements the pullDB search pattern:
  1. User types in a text box
  2. After 3-5 characters, fetch and display matching options
  3. User selects an option, which populates the input and closes the dropdown

Usage:
    - Import SearchableDropdownConfig to configure the widget
    - Use the Jinja macro in templates/partials/searchable_dropdown.html
    - Include the CSS/JS via the macro helpers
"""

from dataclasses import dataclass, field
from enum import Enum


class SearchTriggerMode(Enum):
    """When to trigger the search."""

    ON_TYPE = "on_type"  # Search as user types (default)
    ON_ENTER = "on_enter"  # Search only when user presses Enter
    ON_BLUR = "on_blur"  # Search when input loses focus


@dataclass(frozen=True)
class SearchableDropdownOption:
    """Single option in the dropdown list."""

    value: str  # The value to submit
    label: str  # Primary display text
    sublabel: str | None = None  # Secondary text (e.g., "12 backups")
    icon: str | None = None  # Optional icon name
    metadata: dict = field(default_factory=dict)  # Extra data for client-side use


@dataclass
class SearchableDropdownConfig:
    """Configuration for a searchable dropdown widget.

    Attributes:
        input_id: Unique ID for the input element
        input_name: Form field name
        label: Label text displayed above the input
        placeholder: Placeholder text when empty
        min_chars: Minimum characters before search triggers (3-5 recommended)
        debounce_ms: Milliseconds to wait after typing before searching
        api_endpoint: URL to fetch search results (GET with ?q= parameter)
        required: Whether the field is required
        initial_value: Pre-populated value
        initial_label: Pre-populated display label (if different from value)
        hint_text: Help text displayed below the input
        max_results: Maximum number of results to display
        no_results_text: Text shown when no matches found
        loading_text: Text shown while searching
        trigger_mode: When to trigger the search
        allow_custom: Allow values not in the dropdown
    """

    input_id: str
    input_name: str
    label: str
    placeholder: str = "Type to search..."
    min_chars: int = 3
    debounce_ms: int = 300
    api_endpoint: str = ""
    required: bool = False
    initial_value: str = ""
    initial_label: str = ""
    hint_text: str = ""
    max_results: int = 10
    no_results_text: str = "No results found"
    loading_text: str = "Searching..."
    trigger_mode: SearchTriggerMode = SearchTriggerMode.ON_TYPE
    allow_custom: bool = False


# Pre-defined configurations for common use cases
CUSTOMER_SEARCH_CONFIG = SearchableDropdownConfig(
    input_id="customer",
    input_name="customer",
    label="Customer Name",
    placeholder="Type at least 5 characters to search...",
    min_chars=5,
    debounce_ms=300,
    api_endpoint="/api/customers/search",
    hint_text="Type 5+ characters to search customers",
    max_results=10,
)

USER_SEARCH_CONFIG = SearchableDropdownConfig(
    input_id="user",
    input_name="user",
    label="User",
    placeholder="Search by username or name...",
    min_chars=3,
    debounce_ms=300,
    api_endpoint="/api/users/search",
    hint_text="Type 3+ characters to search users",
    max_results=15,
)

HOST_SEARCH_CONFIG = SearchableDropdownConfig(
    input_id="host",
    input_name="host",
    label="Database Host",
    placeholder="Search hosts...",
    min_chars=3,
    debounce_ms=200,
    api_endpoint="/api/hosts/search",
    hint_text="Search available database hosts",
    max_results=10,
)

DATABASE_SEARCH_CONFIG = SearchableDropdownConfig(
    input_id="database",
    input_name="database",
    label="Database",
    placeholder="Search databases...",
    min_chars=3,
    debounce_ms=300,
    api_endpoint="/api/databases/search",
    hint_text="Search by database name",
    max_results=20,
)


def build_dropdown_config(
    input_id: str,
    input_name: str,
    label: str,
    api_endpoint: str,
    **kwargs,
) -> SearchableDropdownConfig:
    """Factory function to build a SearchableDropdownConfig.

    Args:
        input_id: Unique ID for the input element
        input_name: Form field name
        label: Label text displayed above the input
        api_endpoint: URL to fetch search results
        **kwargs: Additional configuration options

    Returns:
        Configured SearchableDropdownConfig instance
    """
    return SearchableDropdownConfig(
        input_id=input_id,
        input_name=input_name,
        label=label,
        api_endpoint=api_endpoint,
        **kwargs,
    )
