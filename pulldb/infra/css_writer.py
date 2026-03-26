"""CSS file writer utility for design tokens.

This module provides atomic file writing for CSS design tokens,
ensuring design-tokens.css stays synchronized with database settings.

HCA Layer: shared (pulldb/infra/)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pulldb.domain.color_schemas import ColorSchema


# Default path to design-tokens.css (relative to project structure)
DEFAULT_CSS_PATH = Path(__file__).parent.parent / "web" / "shared" / "css" / "design-tokens.css"


def generate_semantic_tokens_css(light_schema: "ColorSchema", dark_schema: "ColorSchema") -> str:
    """Generate the semantic color tokens section of CSS.
    
    Args:
        light_schema: Light mode color schema
        dark_schema: Dark mode color schema
        
    Returns:
        CSS string for the semantic tokens section.
    """
    light_vars = light_schema.to_css_variables()
    dark_vars = dark_schema.to_css_variables()
    
    # Build light mode section
    light_lines = []
    for name, value in sorted(light_vars.items()):
        light_lines.append(f"    {name}: {value};")
    
    # Build dark mode section
    dark_lines = []
    for name, value in sorted(dark_vars.items()):
        dark_lines.append(f"    {name}: {value};")
    
    return f"""/* ===========================================
   SEMANTIC COLOR TOKENS (Database-Synced)
   Light Theme: {light_schema.name}
   Dark Theme: {dark_schema.name}
   Last Updated: Auto-generated on save
   =========================================== */

:root {{
{chr(10).join(light_lines)}
}}

[data-theme="dark"],
.dark {{
{chr(10).join(dark_lines)}
}}
"""


def write_design_tokens(
    light_schema: "ColorSchema",
    dark_schema: "ColorSchema",
    css_path: Path | None = None,
) -> None:
    """Atomically update design-tokens.css with current schema values.
    
    This function reads the existing design-tokens.css, replaces the
    semantic tokens section with values from the provided schemas,
    and writes back atomically using a temporary file + rename.
    
    Args:
        light_schema: Light mode color schema
        dark_schema: Dark mode color schema
        css_path: Path to design-tokens.css (uses default if None)
        
    Raises:
        FileNotFoundError: If the CSS file doesn't exist
        IOError: If file operations fail
    """
    if css_path is None:
        css_path = DEFAULT_CSS_PATH
    
    css_path = Path(css_path)
    
    if not css_path.exists():
        raise FileNotFoundError(f"Design tokens CSS not found: {css_path}")
    
    # Read existing content
    content = css_path.read_text(encoding="utf-8")
    
    # Find the semantic tokens section markers
    # We'll replace everything between SEMANTIC COLOR TOKENS and DARK MODE OVERRIDES
    # or if using the new format, replace the semantic section entirely
    
    # Pattern 1: Look for the old format sections
    semantic_start_marker = "/* ===========================================\n       SEMANTIC COLOR TOKENS"
    dark_mode_marker = "/* ===========================================\n   DARK MODE OVERRIDES"
    
    # Pattern 2: Look for database-synced marker
    db_synced_marker = "/* ===========================================\n   SEMANTIC COLOR TOKENS (Database-Synced)"
    
    # Generate new semantic tokens CSS
    new_tokens_css = generate_semantic_tokens_css(light_schema, dark_schema)
    
    # Check if we have the database-synced format already
    if db_synced_marker in content:
        # Find and replace the database-synced section
        start_idx = content.find(db_synced_marker)
        # Find the end (next major section or end of file)
        remaining = content[start_idx:]
        # Look for next section marker after this one
        next_section_patterns = [
            "\n/* ===========================================\n       TYPOGRAPHY",
            "\n/* ===========================================\n   TYPOGRAPHY",
        ]
        end_idx = len(content)
        for pattern in next_section_patterns:
            idx = remaining.find(pattern)
            if idx > 0:
                end_idx = start_idx + idx
                break
        
        content = content[:start_idx] + new_tokens_css + "\n" + content[end_idx:]
    elif semantic_start_marker in content and dark_mode_marker in content:
        # Old format: replace semantic tokens through dark mode overrides
        start_idx = content.find(semantic_start_marker)
        # Find end of dark mode section (start of next major section)
        dark_start = content.find(dark_mode_marker)
        remaining_after_dark = content[dark_start:]
        
        # Find end of dark mode section - look for closing brace and next section
        # The dark mode section ends with } and then whitespace before next section
        end_of_dark = remaining_after_dark.find("\n\n/*") 
        if end_of_dark == -1:
            end_of_dark = len(remaining_after_dark)
        
        end_idx = dark_start + end_of_dark
        
        # Replace the whole semantic + dark mode section
        content = content[:start_idx] + new_tokens_css + content[end_idx:]
    else:
        # Neither marker format found — FAIL HARD rather than silently corrupting the CSS.
        # The file must contain exactly one of the two known section marker formats:
        #   - "SEMANTIC COLOR TOKENS (Database-Synced)" (current format)
        #   - "SEMANTIC COLOR TOKENS" + "DARK MODE OVERRIDES" (legacy format)
        # If neither is present the CSS has been manually edited or is from an
        # unexpected version; raise so the caller can surface this to the admin.
        raise ValueError(
            f"design-tokens.css at {css_path} does not contain a recognised "
            "semantic-tokens section marker. Expected one of:\n"
            f"  - {db_synced_marker!r}\n"
            f"  - {semantic_start_marker!r} (legacy)\n"
            "Inspect the file and ensure it matches the expected format."
        )
    
    # Write atomically using temp file + rename
    fd, temp_path = tempfile.mkstemp(
        suffix=".css",
        prefix="design-tokens-",
        dir=css_path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        # Atomic rename
        os.replace(temp_path, css_path)
    except Exception:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def sync_design_tokens_from_settings(settings_repo: object, css_path: Path | None = None) -> bool:
    """Sync design-tokens.css from database settings.
    
    Convenience function that loads schemas from a settings repository
    and writes them to the CSS file.
    
    Args:
        settings_repo: Repository with get() method for settings
        css_path: Path to design-tokens.css (uses default if None)
        
    Returns:
        True if sync was successful, False otherwise
    """
    from pulldb.domain.color_schemas import (
        ColorSchema,
        LIGHT_PRESETS,
        DARK_PRESETS,
    )
    
    # Load schemas from settings
    light_schema = LIGHT_PRESETS["Default"]
    dark_schema = DARK_PRESETS["Default"]
    
    try:
        light_json = settings_repo.get("light_theme_schema")  # type: ignore[union-attr]
        if light_json:
            light_schema = ColorSchema.from_json(light_json)
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    
    try:
        dark_json = settings_repo.get("dark_theme_schema")  # type: ignore[union-attr]
        if dark_json:
            dark_schema = ColorSchema.from_json(dark_json)
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    
    try:
        write_design_tokens(light_schema, dark_schema, css_path)
        return True
    except (FileNotFoundError, IOError, ValueError):
        return False
