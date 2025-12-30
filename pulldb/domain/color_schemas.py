"""Color schema definitions for pullDB theming.

This module defines the data structures and preset color schemas for
light and dark mode theming. All color values are stored as CSS-compatible
strings and can be serialized to JSON for database storage.

HCA Layer: entities (pulldb/domain/)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SurfaceColors:
    """Surface/card colors."""

    base: str = "#ffffff"
    hover: str = "#f9fafb"
    active: str = "#f3f4f6"
    subtle: str = "#fcfcfd"
    primary: str = "#ffffff"  # Widget compatibility
    secondary: str = "#f3f4f6"  # Widget compatibility


@dataclass
class BackgroundColors:
    """Page/section background colors."""

    primary: str = "#f9fafb"
    secondary: str = "#f3f4f6"
    tertiary: str = "#e5e7eb"
    elevated: str = "#ffffff"
    hover: str = "#f3f4f6"
    subtle: str = "#f3f4f6"
    muted: str = "#e5e7eb"


@dataclass
class TextColors:
    """Text colors."""

    primary: str = "#111827"
    secondary: str = "#4b5563"
    muted: str = "#6b7280"
    inverse: str = "#ffffff"
    base: str = "#111827"  # Alias for primary


@dataclass
class BorderColors:
    """Border colors."""

    default: str = "#e5e7eb"
    light: str = "#f3f4f6"
    hover: str = "#d1d5db"
    focus: str = "#3b82f6"
    primary: str = "#e5e7eb"  # Widget compatibility
    secondary: str = "#d1d5db"  # Widget compatibility


@dataclass
class StatusColors:
    """Status indicator colors with backgrounds."""

    success: str = "#16a34a"
    success_bg: str = "rgba(22, 163, 74, 0.1)"
    success_border: str = "rgba(22, 163, 74, 0.2)"
    warning: str = "#d97706"
    warning_bg: str = "rgba(217, 119, 6, 0.1)"
    warning_border: str = "rgba(217, 119, 6, 0.2)"
    error: str = "#dc2626"
    error_bg: str = "rgba(220, 38, 38, 0.1)"
    error_border: str = "rgba(220, 38, 38, 0.2)"
    info: str = "#0891b2"
    info_bg: str = "rgba(8, 145, 178, 0.1)"
    info_border: str = "rgba(8, 145, 178, 0.2)"


@dataclass
class InteractiveColors:
    """Interactive element colors (buttons, links)."""

    primary: str = "#2563eb"
    primary_hover: str = "#1d4ed8"
    primary_active: str = "#1e40af"
    accent: str = "#7c3aed"
    accent_hover: str = "#6d28d9"
    danger: str = "#dc2626"
    danger_hover: str = "#b91c1c"


@dataclass
class InputColors:
    """Form input colors."""

    bg: str = "#ffffff"
    border: str = "#d1d5db"
    focus: str = "#3b82f6"
    focus_ring: str = "rgba(59, 130, 246, 0.2)"
    placeholder: str = "#9ca3af"


@dataclass
class LinkColors:
    """Link colors."""

    default: str = "#2563eb"
    hover: str = "#1d4ed8"
    visited: str = "#7c3aed"


@dataclass
class CodeColors:
    """Code block colors."""

    bg: str = "#f3f4f6"
    text: str = "#1f2937"
    border: str = "#e5e7eb"


@dataclass
class TableColors:
    """Table colors."""

    header_bg: str = "#f9fafb"
    row_hover: str = "#f3f4f6"
    row_stripe: str = "rgba(0, 0, 0, 0.02)"


@dataclass
class ScrollbarColors:
    """Scrollbar colors (WebKit)."""

    track: str = "#f3f4f6"
    thumb: str = "#d1d5db"
    thumb_hover: str = "#9ca3af"


@dataclass
class Shadows:
    """Shadow definitions."""

    sm: str = "0 1px 2px 0 rgb(0 0 0 / 0.05)"
    md: str = "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)"
    lg: str = "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)"
    xl: str = "0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)"


@dataclass
class ColorSchema:
    """Complete color schema for a theme mode.

    Contains all semantic color tokens organized by category.
    Can be serialized to JSON for database storage.
    """

    name: str = "Default"
    version: int = 1
    surface: SurfaceColors = field(default_factory=SurfaceColors)
    background: BackgroundColors = field(default_factory=BackgroundColors)
    text: TextColors = field(default_factory=TextColors)
    border: BorderColors = field(default_factory=BorderColors)
    status: StatusColors = field(default_factory=StatusColors)
    interactive: InteractiveColors = field(default_factory=InteractiveColors)
    input: InputColors = field(default_factory=InputColors)
    link: LinkColors = field(default_factory=LinkColors)
    code: CodeColors = field(default_factory=CodeColors)
    table: TableColors = field(default_factory=TableColors)
    scrollbar: ScrollbarColors = field(default_factory=ScrollbarColors)
    shadows: Shadows = field(default_factory=Shadows)

    def to_dict(self) -> dict[str, Any]:
        """Convert schema to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize schema to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ColorSchema":
        """Create schema from dictionary."""
        return cls(
            name=data.get("name", "Custom"),
            version=data.get("version", 1),
            surface=SurfaceColors(**data.get("surface", {})),
            background=BackgroundColors(**data.get("background", {})),
            text=TextColors(**data.get("text", {})),
            border=BorderColors(**data.get("border", {})),
            status=StatusColors(**data.get("status", {})),
            interactive=InteractiveColors(**data.get("interactive", {})),
            input=InputColors(**data.get("input", {})),
            link=LinkColors(**data.get("link", {})),
            code=CodeColors(**data.get("code", {})),
            table=TableColors(**data.get("table", {})),
            scrollbar=ScrollbarColors(**data.get("scrollbar", {})),
            shadows=Shadows(**data.get("shadows", {})),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "ColorSchema":
        """Deserialize schema from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_json_with_defaults(
        cls, json_str: str, defaults: "ColorSchema"
    ) -> "ColorSchema":
        """Deserialize schema from JSON, filling missing values from defaults.
        
        This is critical for mode-specific schemas (dark vs light) where
        the dataclass defaults are light-mode values. When loading a saved
        dark schema, missing fields should come from the dark defaults,
        not light defaults.
        
        Args:
            json_str: JSON string with partial schema data.
            defaults: Default ColorSchema to fill missing values from.
            
        Returns:
            Complete ColorSchema with saved values + defaults for missing.
        """
        data = json.loads(json_str)
        defaults_dict = defaults.to_dict()
        
        # Deep merge: data overwrites defaults
        def deep_merge(base: dict, override: dict) -> dict:
            result = base.copy()
            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result
        
        merged = deep_merge(defaults_dict, data)
        return cls.from_dict(merged)

    def to_css_variables(self, prefix: str = "") -> dict[str, str]:
        """Convert schema to CSS custom property name→value mapping.

        Args:
            prefix: Optional prefix for variable names (e.g., 'dark-')

        Returns:
            Dict mapping CSS variable names to values.
        """
        p = f"-{prefix}" if prefix else ""
        return {
            # Surface
            f"--color{p}-surface": self.surface.base,
            f"--color{p}-surface-hover": self.surface.hover,
            f"--color{p}-surface-active": self.surface.active,
            f"--color{p}-surface-subtle": self.surface.subtle,
            f"--color{p}-surface-primary": self.surface.primary,
            f"--color{p}-surface-secondary": self.surface.secondary,
            # Background
            f"--color{p}-bg-primary": self.background.primary,
            f"--color{p}-bg-secondary": self.background.secondary,
            f"--color{p}-bg-tertiary": self.background.tertiary,
            f"--color{p}-bg-elevated": self.background.elevated,
            f"--color{p}-bg-hover": self.background.hover,
            f"--color{p}-bg-subtle": self.background.subtle,
            f"--color{p}-bg-muted": self.background.muted,
            # Text
            f"--color{p}-text-primary": self.text.primary,
            f"--color{p}-text-secondary": self.text.secondary,
            f"--color{p}-text-muted": self.text.muted,
            f"--color{p}-text-inverse": self.text.inverse,
            f"--color{p}-text-base": self.text.base,
            # Border
            f"--color{p}-border": self.border.default,
            f"--color{p}-border-light": self.border.light,
            f"--color{p}-border-hover": self.border.hover,
            f"--color{p}-border-focus": self.border.focus,
            f"--color{p}-border-primary": self.border.primary,
            f"--color{p}-border-secondary": self.border.secondary,
            # Status
            f"--color{p}-success": self.status.success,
            f"--color{p}-success-bg": self.status.success_bg,
            f"--color{p}-success-border": self.status.success_border,
            f"--color{p}-warning": self.status.warning,
            f"--color{p}-warning-bg": self.status.warning_bg,
            f"--color{p}-warning-border": self.status.warning_border,
            f"--color{p}-error": self.status.error,
            f"--color{p}-error-bg": self.status.error_bg,
            f"--color{p}-error-border": self.status.error_border,
            f"--color{p}-info": self.status.info,
            f"--color{p}-info-bg": self.status.info_bg,
            f"--color{p}-info-border": self.status.info_border,
            # Interactive
            f"--color{p}-primary": self.interactive.primary,
            f"--color{p}-primary-hover": self.interactive.primary_hover,
            f"--color{p}-primary-active": self.interactive.primary_active,
            f"--color{p}-accent": self.interactive.accent,
            f"--color{p}-accent-hover": self.interactive.accent_hover,
            f"--color{p}-danger": self.interactive.danger,
            f"--color{p}-danger-hover": self.interactive.danger_hover,
            # Input
            f"--color{p}-input-bg": self.input.bg,
            f"--color{p}-input-border": self.input.border,
            f"--color{p}-input-focus": self.input.focus,
            f"--color{p}-input-focus-ring": self.input.focus_ring,
            f"--color{p}-input-placeholder": self.input.placeholder,
            # Link
            f"--color{p}-link": self.link.default,
            f"--color{p}-link-hover": self.link.hover,
            f"--color{p}-link-visited": self.link.visited,
            # Code
            f"--color{p}-code-bg": self.code.bg,
            f"--color{p}-code-text": self.code.text,
            f"--color{p}-code-border": self.code.border,
            # Table
            f"--color{p}-table-header-bg": self.table.header_bg,
            f"--color{p}-table-row-hover": self.table.row_hover,
            f"--color{p}-table-row-stripe": self.table.row_stripe,
            # Scrollbar
            f"--color{p}-scrollbar-track": self.scrollbar.track,
            f"--color{p}-scrollbar-thumb": self.scrollbar.thumb,
            f"--color{p}-scrollbar-thumb-hover": self.scrollbar.thumb_hover,
            # Shadows
            f"--shadow{p}-sm": self.shadows.sm,
            f"--shadow{p}-md": self.shadows.md,
            f"--shadow{p}-lg": self.shadows.lg,
            f"--shadow{p}-xl": self.shadows.xl,
        }


# =============================================================================
# LIGHT MODE PRESETS
# =============================================================================

LIGHT_PRESETS: dict[str, ColorSchema] = {
    "Default": ColorSchema(
        name="Default",
        surface=SurfaceColors(
            base="#ffffff",
            hover="#f9fafb",
            active="#f3f4f6",
            subtle="#fcfcfd",
            primary="#ffffff",
            secondary="#f3f4f6",
        ),
        background=BackgroundColors(
            primary="#f9fafb",
            secondary="#f3f4f6",
            tertiary="#e5e7eb",
            elevated="#ffffff",
            hover="#f3f4f6",
            subtle="#f3f4f6",
            muted="#e5e7eb",
        ),
        text=TextColors(
            primary="#111827",
            secondary="#4b5563",
            muted="#6b7280",
            inverse="#ffffff",
            base="#111827",
        ),
        border=BorderColors(
            default="#e5e7eb",
            light="#f3f4f6",
            hover="#d1d5db",
            focus="#3b82f6",
            primary="#e5e7eb",
            secondary="#d1d5db",
        ),
        status=StatusColors(
            success="#16a34a",
            success_bg="rgba(22, 163, 74, 0.1)",
            success_border="rgba(22, 163, 74, 0.2)",
            warning="#d97706",
            warning_bg="rgba(217, 119, 6, 0.1)",
            warning_border="rgba(217, 119, 6, 0.2)",
            error="#dc2626",
            error_bg="rgba(220, 38, 38, 0.1)",
            error_border="rgba(220, 38, 38, 0.2)",
            info="#0891b2",
            info_bg="rgba(8, 145, 178, 0.1)",
            info_border="rgba(8, 145, 178, 0.2)",
        ),
        interactive=InteractiveColors(
            primary="#2563eb",
            primary_hover="#1d4ed8",
            primary_active="#1e40af",
            accent="#7c3aed",
            accent_hover="#6d28d9",
            danger="#dc2626",
            danger_hover="#b91c1c",
        ),
        input=InputColors(
            bg="#ffffff",
            border="#d1d5db",
            focus="#3b82f6",
            focus_ring="rgba(59, 130, 246, 0.2)",
            placeholder="#9ca3af",
        ),
        link=LinkColors(
            default="#2563eb",
            hover="#1d4ed8",
            visited="#7c3aed",
        ),
        code=CodeColors(
            bg="#f3f4f6",
            text="#1f2937",
            border="#e5e7eb",
        ),
        table=TableColors(
            header_bg="#f9fafb",
            row_hover="#f3f4f6",
            row_stripe="rgba(0, 0, 0, 0.02)",
        ),
        scrollbar=ScrollbarColors(
            track="#f3f4f6",
            thumb="#d1d5db",
            thumb_hover="#9ca3af",
        ),
        shadows=Shadows(
            sm="0 1px 2px 0 rgb(0 0 0 / 0.05)",
            md="0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
            lg="0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
            xl="0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)",
        ),
    ),
    "Warm": ColorSchema(
        name="Warm",
        surface=SurfaceColors(
            base="#fffbf5",
            hover="#fef7ed",
            active="#fef3e2",
            subtle="#fffdfb",
            primary="#fffbf5",
            secondary="#fef7ed",
        ),
        background=BackgroundColors(
            primary="#fef7ed",
            secondary="#fef3e2",
            tertiary="#fde9d0",
            elevated="#fffbf5",
            hover="#fef3e2",
            subtle="#fef3e2",
            muted="#fde9d0",
        ),
        text=TextColors(
            primary="#1c1917",
            secondary="#57534e",
            muted="#78716c",
            inverse="#fffbf5",
            base="#1c1917",
        ),
        border=BorderColors(
            default="#e7e5e4",
            light="#f5f5f4",
            hover="#d6d3d1",
            focus="#ea580c",
            primary="#e7e5e4",
            secondary="#d6d3d1",
        ),
        status=StatusColors(
            success="#15803d",
            success_bg="rgba(21, 128, 61, 0.1)",
            success_border="rgba(21, 128, 61, 0.2)",
            warning="#c2410c",
            warning_bg="rgba(194, 65, 12, 0.1)",
            warning_border="rgba(194, 65, 12, 0.2)",
            error="#b91c1c",
            error_bg="rgba(185, 28, 28, 0.1)",
            error_border="rgba(185, 28, 28, 0.2)",
            info="#0369a1",
            info_bg="rgba(3, 105, 161, 0.1)",
            info_border="rgba(3, 105, 161, 0.2)",
        ),
        interactive=InteractiveColors(
            primary="#ea580c",
            primary_hover="#c2410c",
            primary_active="#9a3412",
            accent="#a21caf",
            accent_hover="#86198f",
            danger="#b91c1c",
            danger_hover="#991b1b",
        ),
        input=InputColors(
            bg="#fffbf5",
            border="#d6d3d1",
            focus="#ea580c",
            focus_ring="rgba(234, 88, 12, 0.2)",
            placeholder="#a8a29e",
        ),
        link=LinkColors(
            default="#ea580c",
            hover="#c2410c",
            visited="#a21caf",
        ),
        code=CodeColors(
            bg="#fef3e2",
            text="#1c1917",
            border="#e7e5e4",
        ),
        table=TableColors(
            header_bg="#fef7ed",
            row_hover="#fef3e2",
            row_stripe="rgba(0, 0, 0, 0.02)",
        ),
        scrollbar=ScrollbarColors(
            track="#fef3e2",
            thumb="#d6d3d1",
            thumb_hover="#a8a29e",
        ),
    ),
    "Cool": ColorSchema(
        name="Cool",
        surface=SurfaceColors(
            base="#f8fafc",
            hover="#f1f5f9",
            active="#e2e8f0",
            subtle="#fafbfc",
            primary="#f8fafc",
            secondary="#f1f5f9",
        ),
        background=BackgroundColors(
            primary="#f1f5f9",
            secondary="#e2e8f0",
            tertiary="#cbd5e1",
            elevated="#f8fafc",
            hover="#e2e8f0",
            subtle="#e2e8f0",
            muted="#cbd5e1",
        ),
        text=TextColors(
            primary="#0f172a",
            secondary="#475569",
            muted="#64748b",
            inverse="#f8fafc",
            base="#0f172a",
        ),
        border=BorderColors(
            default="#e2e8f0",
            light="#f1f5f9",
            hover="#cbd5e1",
            focus="#0ea5e9",
            primary="#e2e8f0",
            secondary="#cbd5e1",
        ),
        status=StatusColors(
            success="#059669",
            success_bg="rgba(5, 150, 105, 0.1)",
            success_border="rgba(5, 150, 105, 0.2)",
            warning="#d97706",
            warning_bg="rgba(217, 119, 6, 0.1)",
            warning_border="rgba(217, 119, 6, 0.2)",
            error="#dc2626",
            error_bg="rgba(220, 38, 38, 0.1)",
            error_border="rgba(220, 38, 38, 0.2)",
            info="#0284c7",
            info_bg="rgba(2, 132, 199, 0.1)",
            info_border="rgba(2, 132, 199, 0.2)",
        ),
        interactive=InteractiveColors(
            primary="#0ea5e9",
            primary_hover="#0284c7",
            primary_active="#0369a1",
            accent="#8b5cf6",
            accent_hover="#7c3aed",
            danger="#dc2626",
            danger_hover="#b91c1c",
        ),
        input=InputColors(
            bg="#f8fafc",
            border="#cbd5e1",
            focus="#0ea5e9",
            focus_ring="rgba(14, 165, 233, 0.2)",
            placeholder="#94a3b8",
        ),
        link=LinkColors(
            default="#0ea5e9",
            hover="#0284c7",
            visited="#8b5cf6",
        ),
        code=CodeColors(
            bg="#e2e8f0",
            text="#0f172a",
            border="#e2e8f0",
        ),
        table=TableColors(
            header_bg="#f1f5f9",
            row_hover="#e2e8f0",
            row_stripe="rgba(0, 0, 0, 0.02)",
        ),
        scrollbar=ScrollbarColors(
            track="#e2e8f0",
            thumb="#cbd5e1",
            thumb_hover="#94a3b8",
        ),
    ),
}


# =============================================================================
# DARK MODE PRESETS
# =============================================================================

DARK_PRESETS: dict[str, ColorSchema] = {
    "Default": ColorSchema(
        name="Default",
        surface=SurfaceColors(
            base="#1e293b",
            hover="#334155",
            active="#475569",
            subtle="#0f172a",
            primary="#1e293b",
            secondary="#334155",
        ),
        background=BackgroundColors(
            primary="#0f172a",
            secondary="#1e293b",
            tertiary="#334155",
            elevated="#1e293b",
            hover="#334155",
            subtle="#1e293b",
            muted="#334155",
        ),
        text=TextColors(
            primary="#f1f5f9",
            secondary="#94a3b8",
            muted="#64748b",
            inverse="#0f172a",
            base="#f1f5f9",
        ),
        border=BorderColors(
            default="#334155",
            light="#475569",
            hover="#475569",
            focus="#60a5fa",
            primary="#334155",
            secondary="#475569",
        ),
        status=StatusColors(
            success="#4ade80",
            success_bg="rgba(74, 222, 128, 0.15)",
            success_border="rgba(74, 222, 128, 0.3)",
            warning="#fbbf24",
            warning_bg="rgba(251, 191, 36, 0.15)",
            warning_border="rgba(251, 191, 36, 0.3)",
            error="#f87171",
            error_bg="rgba(248, 113, 113, 0.15)",
            error_border="rgba(248, 113, 113, 0.3)",
            info="#60a5fa",
            info_bg="rgba(96, 165, 250, 0.15)",
            info_border="rgba(96, 165, 250, 0.3)",
        ),
        interactive=InteractiveColors(
            primary="#60a5fa",
            primary_hover="#3b82f6",
            primary_active="#2563eb",
            accent="#a78bfa",
            accent_hover="#8b5cf6",
            danger="#f87171",
            danger_hover="#ef4444",
        ),
        input=InputColors(
            bg="#1e293b",
            border="#475569",
            focus="#60a5fa",
            focus_ring="rgba(96, 165, 250, 0.3)",
            placeholder="#64748b",
        ),
        link=LinkColors(
            default="#60a5fa",
            hover="#93c5fd",
            visited="#a78bfa",
        ),
        code=CodeColors(
            bg="#1e293b",
            text="#e2e8f0",
            border="#334155",
        ),
        table=TableColors(
            header_bg="#1e293b",
            row_hover="#334155",
            row_stripe="rgba(255, 255, 255, 0.02)",
        ),
        scrollbar=ScrollbarColors(
            track="#1e293b",
            thumb="#475569",
            thumb_hover="#64748b",
        ),
        shadows=Shadows(
            sm="0 1px 2px 0 rgba(0, 0, 0, 0.3)",
            md="0 4px 6px -1px rgba(0, 0, 0, 0.4), 0 2px 4px -2px rgba(0, 0, 0, 0.3)",
            lg="0 10px 15px -3px rgba(0, 0, 0, 0.4), 0 4px 6px -4px rgba(0, 0, 0, 0.3)",
            xl="0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.4)",
        ),
    ),
    "Midnight Blue": ColorSchema(
        name="Midnight Blue",
        surface=SurfaceColors(
            base="#1e3a5f",
            hover="#234b7a",
            active="#2d5a8a",
            subtle="#0d1f33",
            primary="#1e3a5f",
            secondary="#234b7a",
        ),
        background=BackgroundColors(
            primary="#0d1f33",
            secondary="#1e3a5f",
            tertiary="#234b7a",
            elevated="#1e3a5f",
            hover="#234b7a",
            subtle="#1e3a5f",
            muted="#234b7a",
        ),
        text=TextColors(
            primary="#e0f2fe",
            secondary="#7dd3fc",
            muted="#38bdf8",
            inverse="#0d1f33",
            base="#e0f2fe",
        ),
        border=BorderColors(
            default="#234b7a",
            light="#2d5a8a",
            hover="#2d5a8a",
            focus="#38bdf8",
            primary="#234b7a",
            secondary="#2d5a8a",
        ),
        status=StatusColors(
            success="#34d399",
            success_bg="rgba(52, 211, 153, 0.15)",
            success_border="rgba(52, 211, 153, 0.3)",
            warning="#fcd34d",
            warning_bg="rgba(252, 211, 77, 0.15)",
            warning_border="rgba(252, 211, 77, 0.3)",
            error="#fb7185",
            error_bg="rgba(251, 113, 133, 0.15)",
            error_border="rgba(251, 113, 133, 0.3)",
            info="#38bdf8",
            info_bg="rgba(56, 189, 248, 0.15)",
            info_border="rgba(56, 189, 248, 0.3)",
        ),
        interactive=InteractiveColors(
            primary="#38bdf8",
            primary_hover="#0ea5e9",
            primary_active="#0284c7",
            accent="#c4b5fd",
            accent_hover="#a78bfa",
            danger="#fb7185",
            danger_hover="#f43f5e",
        ),
        input=InputColors(
            bg="#1e3a5f",
            border="#2d5a8a",
            focus="#38bdf8",
            focus_ring="rgba(56, 189, 248, 0.3)",
            placeholder="#38bdf8",
        ),
        link=LinkColors(
            default="#38bdf8",
            hover="#7dd3fc",
            visited="#c4b5fd",
        ),
        code=CodeColors(
            bg="#1e3a5f",
            text="#e0f2fe",
            border="#234b7a",
        ),
        table=TableColors(
            header_bg="#1e3a5f",
            row_hover="#234b7a",
            row_stripe="rgba(255, 255, 255, 0.02)",
        ),
        scrollbar=ScrollbarColors(
            track="#1e3a5f",
            thumb="#2d5a8a",
            thumb_hover="#38bdf8",
        ),
        shadows=Shadows(
            sm="0 1px 2px 0 rgba(0, 0, 0, 0.4)",
            md="0 4px 6px -1px rgba(0, 0, 0, 0.5), 0 2px 4px -2px rgba(0, 0, 0, 0.4)",
            lg="0 10px 15px -3px rgba(0, 0, 0, 0.5), 0 4px 6px -4px rgba(0, 0, 0, 0.4)",
            xl="0 20px 25px -5px rgba(0, 0, 0, 0.6), 0 8px 10px -6px rgba(0, 0, 0, 0.5)",
        ),
    ),
    "OLED Black": ColorSchema(
        name="OLED Black",
        surface=SurfaceColors(
            base="#0a0a0a",
            hover="#171717",
            active="#262626",
            subtle="#000000",
            primary="#0a0a0a",
            secondary="#171717",
        ),
        background=BackgroundColors(
            primary="#000000",
            secondary="#0a0a0a",
            tertiary="#171717",
            elevated="#0a0a0a",
            hover="#171717",
            subtle="#0a0a0a",
            muted="#171717",
        ),
        text=TextColors(
            primary="#fafafa",
            secondary="#a1a1aa",
            muted="#71717a",
            inverse="#000000",
            base="#fafafa",
        ),
        border=BorderColors(
            default="#27272a",
            light="#3f3f46",
            hover="#3f3f46",
            focus="#a78bfa",
            primary="#27272a",
            secondary="#3f3f46",
        ),
        status=StatusColors(
            success="#4ade80",
            success_bg="rgba(74, 222, 128, 0.12)",
            success_border="rgba(74, 222, 128, 0.25)",
            warning="#facc15",
            warning_bg="rgba(250, 204, 21, 0.12)",
            warning_border="rgba(250, 204, 21, 0.25)",
            error="#f87171",
            error_bg="rgba(248, 113, 113, 0.12)",
            error_border="rgba(248, 113, 113, 0.25)",
            info="#60a5fa",
            info_bg="rgba(96, 165, 250, 0.12)",
            info_border="rgba(96, 165, 250, 0.25)",
        ),
        interactive=InteractiveColors(
            primary="#a78bfa",
            primary_hover="#8b5cf6",
            primary_active="#7c3aed",
            accent="#f472b6",
            accent_hover="#ec4899",
            danger="#f87171",
            danger_hover="#ef4444",
        ),
        input=InputColors(
            bg="#0a0a0a",
            border="#3f3f46",
            focus="#a78bfa",
            focus_ring="rgba(167, 139, 250, 0.3)",
            placeholder="#71717a",
        ),
        link=LinkColors(
            default="#a78bfa",
            hover="#c4b5fd",
            visited="#f472b6",
        ),
        code=CodeColors(
            bg="#0a0a0a",
            text="#fafafa",
            border="#27272a",
        ),
        table=TableColors(
            header_bg="#0a0a0a",
            row_hover="#171717",
            row_stripe="rgba(255, 255, 255, 0.02)",
        ),
        scrollbar=ScrollbarColors(
            track="#0a0a0a",
            thumb="#3f3f46",
            thumb_hover="#71717a",
        ),
        shadows=Shadows(
            sm="0 1px 2px 0 rgba(0, 0, 0, 0.5)",
            md="0 4px 6px -1px rgba(0, 0, 0, 0.6), 0 2px 4px -2px rgba(0, 0, 0, 0.5)",
            lg="0 10px 15px -3px rgba(0, 0, 0, 0.6), 0 4px 6px -4px rgba(0, 0, 0, 0.5)",
            xl="0 20px 25px -5px rgba(0, 0, 0, 0.7), 0 8px 10px -6px rgba(0, 0, 0, 0.6)",
        ),
    ),
    "Solarized Dark": ColorSchema(
        name="Solarized Dark",
        surface=SurfaceColors(
            base="#073642",
            hover="#094050",
            active="#0b4d5e",
            subtle="#002b36",
            primary="#073642",
            secondary="#094050",
        ),
        background=BackgroundColors(
            primary="#002b36",
            secondary="#073642",
            tertiary="#094050",
            elevated="#073642",
            hover="#094050",
            subtle="#073642",
            muted="#094050",
        ),
        text=TextColors(
            primary="#93a1a1",
            secondary="#839496",
            muted="#657b83",
            inverse="#002b36",
            base="#93a1a1",
        ),
        border=BorderColors(
            default="#094050",
            light="#0b4d5e",
            hover="#0b4d5e",
            focus="#268bd2",
            primary="#094050",
            secondary="#0b4d5e",
        ),
        status=StatusColors(
            success="#859900",
            success_bg="rgba(133, 153, 0, 0.15)",
            success_border="rgba(133, 153, 0, 0.3)",
            warning="#b58900",
            warning_bg="rgba(181, 137, 0, 0.15)",
            warning_border="rgba(181, 137, 0, 0.3)",
            error="#dc322f",
            error_bg="rgba(220, 50, 47, 0.15)",
            error_border="rgba(220, 50, 47, 0.3)",
            info="#268bd2",
            info_bg="rgba(38, 139, 210, 0.15)",
            info_border="rgba(38, 139, 210, 0.3)",
        ),
        interactive=InteractiveColors(
            primary="#268bd2",
            primary_hover="#2aa198",
            primary_active="#859900",
            accent="#d33682",
            accent_hover="#cb4b16",
            danger="#dc322f",
            danger_hover="#cb4b16",
        ),
        input=InputColors(
            bg="#073642",
            border="#0b4d5e",
            focus="#268bd2",
            focus_ring="rgba(38, 139, 210, 0.3)",
            placeholder="#657b83",
        ),
        link=LinkColors(
            default="#268bd2",
            hover="#2aa198",
            visited="#d33682",
        ),
        code=CodeColors(
            bg="#073642",
            text="#93a1a1",
            border="#094050",
        ),
        table=TableColors(
            header_bg="#073642",
            row_hover="#094050",
            row_stripe="rgba(255, 255, 255, 0.02)",
        ),
        scrollbar=ScrollbarColors(
            track="#073642",
            thumb="#0b4d5e",
            thumb_hover="#657b83",
        ),
        shadows=Shadows(
            sm="0 1px 2px 0 rgba(0, 0, 0, 0.35)",
            md="0 4px 6px -1px rgba(0, 0, 0, 0.45), 0 2px 4px -2px rgba(0, 0, 0, 0.35)",
            lg="0 10px 15px -3px rgba(0, 0, 0, 0.45), 0 4px 6px -4px rgba(0, 0, 0, 0.35)",
            xl="0 20px 25px -5px rgba(0, 0, 0, 0.55), 0 8px 10px -6px rgba(0, 0, 0, 0.45)",
        ),
    ),
}


def get_preset_names(mode: str) -> list[str]:
    """Get list of available preset names for a mode.

    Args:
        mode: 'light' or 'dark'

    Returns:
        List of preset names.
    """
    presets = LIGHT_PRESETS if mode == "light" else DARK_PRESETS
    return list(presets.keys())


def get_preset(mode: str, name: str) -> ColorSchema | None:
    """Get a preset schema by mode and name.

    Args:
        mode: 'light' or 'dark'
        name: Preset name

    Returns:
        ColorSchema if found, None otherwise.
    """
    presets = LIGHT_PRESETS if mode == "light" else DARK_PRESETS
    return presets.get(name)


def get_default_schema_json(mode: str) -> str:
    """Get the default schema JSON for a mode.

    Args:
        mode: 'light' or 'dark'

    Returns:
        JSON string of the default schema.
    """
    presets = LIGHT_PRESETS if mode == "light" else DARK_PRESETS
    return presets["Default"].to_json()
