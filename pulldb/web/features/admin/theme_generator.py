"""Theme CSS Generator - Generates static CSS files from ColorSchemas.

HCA Layer: features (pulldb/web/features/admin/)

This module generates isolated CSS files for light and dark modes,
written to the static directory on theme save. Only one mode's CSS
is loaded at runtime based on user preference.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pulldb.domain.color_schemas import ColorSchema


# Directory where generated theme CSS files are written
GENERATED_CSS_DIR = Path(__file__).parent.parent.parent / "static" / "css" / "generated"


def generate_theme_css(schema: "ColorSchema", mode: str = "light") -> str:
    """Generate CSS custom properties from a ColorSchema.
    
    Outputs all variables under [data-theme] selector for proper specificity.
    This ensures theme values are applied based on the data-theme attribute,
    preventing flash of incorrect theme during page transitions.
    
    Args:
        schema: ColorSchema instance with color values.
        mode: Theme mode ('light' or 'dark') for selector generation.
        
    Returns:
        CSS string with [data-theme="mode"] { --var: value; } declarations.
    """
    css_vars = schema.to_css_variables()
    css_lines = [f"    {name}: {value};" for name, value in css_vars.items()]
    css_content = "\n".join(css_lines)
    
    # Use both :root and [data-theme] for maximum compatibility
    # :root provides defaults, [data-theme] provides specificity
    return f"""/* pullDB Theme - {schema.name} ({mode})
 * Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}
 * This file is auto-generated. Do not edit directly.
 */

/* Base variables - loaded when this file is active */
:root {{
{css_content}
}}

/* Attribute selector for specificity - prevents flash during transitions */
[data-theme="{mode}"] {{
{css_content}
}}
"""


def ensure_generated_dir() -> Path:
    """Ensure the generated CSS directory exists.
    
    Returns:
        Path to the generated CSS directory.
    """
    GENERATED_CSS_DIR.mkdir(parents=True, exist_ok=True)
    return GENERATED_CSS_DIR


def write_theme_files(
    light_schema: "ColorSchema",
    dark_schema: "ColorSchema",
) -> dict:
    """Write light and dark theme CSS files to static directory.
    
    Generates two separate CSS files:
    - manifest-light.css: Light mode variables under :root and [data-theme="light"]
    - manifest-dark.css: Dark mode variables under :root and [data-theme="dark"]
    
    Args:
        light_schema: ColorSchema for light mode.
        dark_schema: ColorSchema for dark mode.
        
    Returns:
        Dict with version timestamp for cache-busting.
    """
    ensure_generated_dir()
    version = int(time.time())
    
    # Generate and write light theme
    light_css = generate_theme_css(light_schema, mode="light")
    light_path = GENERATED_CSS_DIR / "manifest-light.css"
    light_path.write_text(light_css)
    
    # Generate and write dark theme
    dark_css = generate_theme_css(dark_schema, mode="dark")
    dark_path = GENERATED_CSS_DIR / "manifest-dark.css"
    dark_path.write_text(dark_css)
    
    # Write version file for cache-busting reference
    version_path = GENERATED_CSS_DIR / "version.txt"
    version_path.write_text(str(version))
    
    return {"version": version, "light": str(light_path), "dark": str(dark_path)}


def get_theme_version() -> int:
    """Get the current theme version for cache-busting.
    
    Returns:
        Version timestamp, or current time if version file doesn't exist.
    """
    version_path = GENERATED_CSS_DIR / "version.txt"
    if version_path.exists():
        try:
            return int(version_path.read_text().strip())
        except (ValueError, IOError):
            pass
    return int(time.time())


def ensure_theme_files_exist(settings_repo) -> int:
    """Ensure theme CSS files exist, generating defaults if needed.
    
    Called on app startup or first request to guarantee CSS files exist.
    
    Args:
        settings_repo: Settings repository for loading saved schemas.
        
    Returns:
        Version timestamp of the theme files.
    """
    from pulldb.domain.color_schemas import (
        ColorSchema,
        LIGHT_PRESETS,
        DARK_PRESETS,
    )
    
    light_path = GENERATED_CSS_DIR / "manifest-light.css"
    dark_path = GENERATED_CSS_DIR / "manifest-dark.css"
    
    # If both files exist, just return current version
    if light_path.exists() and dark_path.exists():
        return get_theme_version()
    
    # Load schemas from database or use defaults
    light_schema = LIGHT_PRESETS["Default"]
    dark_schema = DARK_PRESETS["Default"]
    
    if settings_repo:
        try:
            light_json = settings_repo.get_setting("light_theme_schema")
            if light_json:
                light_schema = ColorSchema.from_json(light_json)
        except (ValueError, TypeError, KeyError):
            pass
        
        try:
            dark_json = settings_repo.get_setting("dark_theme_schema")
            if dark_json:
                dark_schema = ColorSchema.from_json(dark_json)
        except (ValueError, TypeError, KeyError):
            pass
    
    # Generate the files
    result = write_theme_files(light_schema, dark_schema)
    return result["version"]
