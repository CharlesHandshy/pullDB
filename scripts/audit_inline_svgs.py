#!/usr/bin/env python3
"""Extract and catalog all inline SVGs from pullDB web templates.

This script analyzes all HTML templates to:
1. Find inline SVG elements
2. Extract unique SVG paths for deduplication
3. Suggest icon names based on context
4. Generate migration report

Usage:
    python scripts/audit_inline_svgs.py [--output json|markdown]

Output:
    - Total SVG count
    - Unique SVG patterns (deduplicated by path content)
    - Files requiring migration with line numbers
    - Suggested icon macro names
"""

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SVGInstance:
    """A single inline SVG found in a template."""

    file: str
    line: int
    svg_content: str
    context: str  # surrounding text for name suggestion
    path_hash: str = field(init=False)

    def __post_init__(self):
        # Hash the SVG path content for deduplication
        # Normalize whitespace and extract just the path data
        paths = re.findall(r'd="([^"]+)"', self.svg_content)
        normalized = "".join(sorted(paths))
        self.path_hash = hashlib.md5(normalized.encode()).hexdigest()[:8]


@dataclass
class UniqueIcon:
    """A unique icon pattern with all its occurrences."""

    path_hash: str
    representative_svg: str
    suggested_name: str
    occurrences: list[SVGInstance] = field(default_factory=list)
    hca_layer: str = "unknown"


def extract_svgs_from_file(file_path: Path, base_dir: Path) -> list[SVGInstance]:
    """Extract all inline SVGs from a single template file."""
    instances = []
    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Pattern to match inline SVGs (not in <img> tags)
    svg_pattern = re.compile(
        r"<svg[^>]*>.*?</svg>",
        re.DOTALL | re.IGNORECASE,
    )

    for match in svg_pattern.finditer(content):
        svg_content = match.group(0)

        # Skip if it's an empty or trivial SVG
        if "<path" not in svg_content and "<circle" not in svg_content:
            continue

        # Find line number
        char_pos = match.start()
        line_num = content[:char_pos].count("\n") + 1

        # Get context (previous 50 chars for name inference)
        context_start = max(0, char_pos - 100)
        context = content[context_start:char_pos]

        try:
            rel_path = str(file_path.relative_to(base_dir))
        except ValueError:
            rel_path = str(file_path)

        instances.append(
            SVGInstance(
                file=rel_path,
                line=line_num,
                svg_content=svg_content[:500],  # Truncate for readability
                context=context[-100:],
            )
        )

    return instances


def suggest_icon_name(svg: SVGInstance) -> str:
    """Suggest an icon name based on context and SVG content."""
    context_lower = svg.context.lower()
    svg_lower = svg.svg_content.lower()

    # Context-based suggestions
    context_hints = {
        "dashboard": "dashboard",
        "search": "search",
        "user": "user",
        "team": "users-group",
        "admin": "cog",
        "settings": "cog",
        "delete": "trash",
        "remove": "trash",
        "edit": "edit-pen",
        "download": "download",
        "export": "download",
        "database": "database",
        "host": "server",
        "cancel": "x-mark",
        "close": "close",
        "success": "check-circle",
        "error": "warning",
        "warning": "warning",
        "info": "info",
        "chevron": "chevron-down",
        "arrow": "chevron-right",
        "logout": "logout",
        "login": "login",
        "refresh": "refresh",
        "restore": "refresh",
        "eye": "eye",
        "view": "eye",
        "clock": "clock",
        "time": "clock",
        "key": "key",
        "password": "lock",
        "shield": "shield",
        "secure": "shield",
        "folder": "folder",
        "file": "document-stack",
        "document": "document-stack",
        "plus": "plus",
        "add": "plus",
        "minus": "minus",
        "sort": "sort",
        "filter": "filter",
        "menu": "hamburger",
        "external": "external-link",
        "link": "external-link",
        "cloud": "cloud",
        "s3": "cloud",
        "backup": "cloud",
        "sun": "sun",
        "moon": "moon",
        "light": "sun",
        "dark": "moon",
        "globe": "globe",
        "world": "globe",
        "lightning": "lightning",
        "quick": "lightning",
        "activity": "activity",
        "pulse": "activity",
        "check": "check",
        "home": "home",
        "spinner": "spinner",
        "loading": "spinner",
    }

    for hint, name in context_hints.items():
        if hint in context_lower:
            return name

    # SVG content-based suggestions (path patterns from Heroicons/common icon sets)
    svg_hints = {
        # Dashboard/Grid patterns
        "M3 3h7v7H3": "dashboard",
        "M3.375 19.5h17.25m-17.25": "table",  # Table with rows
        # User patterns
        "circle cx": "user",
        # Database patterns
        "ellipse cx": "database",
        "M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125": "database",  # Database cylinder
        # Search patterns
        "M21 21l-6-6": "search",
        "M21 21l-5.197-5.19": "search",  # Heroicons search
        # Filter patterns
        "M12 3c2.755 0 5.455.232 8.083.678": "filter",  # Heroicons filter funnel
        # Navigation chevrons
        "M6 9l6 6 6-6": "chevron-down",
        "M9 18l6-6-6-6": "chevron-right",
        "M15 18l-6-6 6-6": "chevron-left",
        "M4.5 15.75l7.5-7.5 7.5 7.5": "chevron-up",  # Heroicons sort indicator
        "M8.25 4.5l7.5 7.5-7.5 7.5": "chevron-right",  # Heroicons
        "M15.75 19.5L8.25 12l7.5-7.5": "chevron-left",  # Heroicons
        "M18.75 19.5l-7.5-7.5 7.5-7.5m-6 15L5.25 12l7.5-7.5": "chevron-double-left",  # First page
        "M5.25 4.5l7.5 7.5-7.5 7.5m6-15l7.5 7.5-7.5 7.5": "chevron-double-right",  # Last page
        # Close/Cancel patterns
        "M18 6L6 18": "close",
        "M6 18L18 6M6 6l12 12": "close",  # X mark
        "M18.364 18.3": "x-circle",  # X in circle (canceled)
        # Math operators
        "M5 12h14": "minus",
        "M12 5v14": "plus",
        "M12 4.5v15m7.5-7.5h-15": "plus",  # Heroicons plus
        "polyline points=\"20 6 9 17 4 12\"": "check",
        # Status indicators
        "M9 12.75L11.25 15 15 9.75M21 12a9 9 0": "check-circle",  # Success
        "M4.5 12.75l6 6 9-13.5": "check",  # Checkmark
        "M12 9v3.75m-9.303 3.376": "warning-triangle",  # Alert triangle
        "M12 9v3.75m9.303 3.376": "warning-triangle",  # Alert triangle (alt)
        "M22 11.08V12a10 10 0 1 1-5.93-9.14": "check-circle",  # Success circle (Lucide)
        "polyline points=\"22 4 12 14.01 9 11.01\"": "check",  # Success checkmark
        # Actions
        "M5.25 5.653c0-.856.917-1.398 1.667-.986": "play",  # Play button
        "M5.25 7.5A2.25 2.25 0 017.5 5.25h9": "stop",  # Stop button (square)
        # Time/Clock patterns
        "M12 6v6h4.5m4.5 0a9 9 0 11-18 0": "clock",  # Clock with hands
        "polyline points=\"12 6 12 12 16 14\"": "clock",  # Lucide clock
        # Lightning/Quick action
        "M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75": "lightning",  # Bolt
        # Document patterns
        "M4 7V4a2 2 0 0 1 2-2h8.5L20 7.5V20": "document",  # File with fold
        "M19.5 14.25v-2.625a3.375": "document-stack",  # Multiple docs
        # Logo/Brand
        "M2.25 15a4.5 4.5 0 004.5 4.5H18": "pulldb-logo",  # Custom logo
        # Arrow/Back patterns
        "M9 15L3 9m0 0l6-6M3 9h12": "arrow-left",  # Back arrow
        "M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18": "arrow-left-long",  # Long back
        "M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3": "arrow-right",  # Forward arrow
        "m15 18-6-6 6-6": "chevron-left",  # Lucide chevron-left
        # Home
        "M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12": "home",
        # Info circle
        "M11.25 11.25l.041-.02a.75.75 0": "info",
        # External link
        "M13.5 6H5.25A2.25": "external-link",
        # Shield
        "M9 12.75L11.25 15 15 9.75m-3-7.036A11.959": "shield-check",
        # Empty state patterns
        "M20.25 7.5l-.625 10.632": "inbox-empty",  # Empty inbox
        # Chart/Analytics patterns
        "M12 2a10 10 0 1 0 10 10H12V2z": "pie-chart",  # Pie chart
        "M21.18 8.02c-1-2.3-2.85-4.17-5.16-5.18": "pie-chart",  # Pie chart segment
        # Calendar/Grid patterns
        "rect width=\"18\" height=\"18\" x=\"3\" y=\"4\"": "calendar",  # Calendar box
        # Package/Box patterns
        "M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8": "package",  # 3D box
        # Circle clock for summary
        "circle cx=\"12\" cy=\"12\" r=\"10\"": "clock-circle",  # Circle + clock hands
        # Success badge patterns
        "M9 11l3 3L22 4": "check",  # Simple checkmark
        # Logo/Brand patterns
        "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5": "layers",  # Stacked layers logo
        # Lock/Security patterns
        "rect width=\"18\" height=\"11\" x=\"3\" y=\"11\"": "lock",  # Lock body
        "M7 11V7a5 5 0 0 1 10 0v4": "lock",  # Lock shackle
        # Error/Warning patterns
        "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94": "error-triangle",  # Error triangle
        "line x1=\"12\" x2=\"12\" y1=\"9\" y2=\"13\"": "error-triangle",  # Error line
        # Info circle patterns
        "M12 16v-4": "info-circle",  # Info text
        "M12 8h.01": "info-circle",  # Info dot
        # Document/File patterns
        "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12": "document-text",  # Document with lines
        "polyline points=\"14 2 14 8 20 8\"": "document-text",  # Document fold
        # Database with modifier
        "line x1=\"9\" x2=\"15\" y1=\"12\" y2=\"12\"": "database-minus",  # DB with minus
        # Upload patterns
        "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4": "upload",  # Upload base
        "polyline points=\"17 8 12 3 7 8\"": "upload",  # Upload arrow
        "line x1=\"12\" x2=\"12\" y1=\"3\" y2=\"15\"": "upload",  # Upload line
        # Download patterns
        "polyline points=\"7 10 12 15 17 10\"": "download",  # Download arrow
        # Trash/Delete patterns
        "M3 6h18": "trash",  # Trash top
        "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6": "trash",  # Trash body
        # Password/Requirements patterns
        "M22 11.08V12a10 10": "check-requirement",  # Check requirement
        # Briefcase/Role patterns
        "rect width=\"20\" height=\"14\" x=\"2\" y=\"7\"": "briefcase",  # Briefcase body
        "path d=\"M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16\"": "briefcase",  # Briefcase handle
        # Loading/Spinner patterns
        "M21 12a9 9 0 1 1-6.219-8.56": "spinner",  # Partial circle spinner
        # Search clear icon (X)
        "line x1=\"18\" y1=\"6\" x2=\"6\" y2=\"18\"": "close",  # X line 1
        "line x1=\"6\" y1=\"6\" x2=\"18\" y2=\"18\"": "close",  # X line 2
        # Eye/View patterns (Heroicons)
        "M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5": "eye",  # Eye outer
        "M15 12a3 3 0 11-6 0 3 3 0 016 0z": "eye",  # Eye pupil
        # Circle with radius for search
        "circle cx=\"11\" cy=\"11\" r=\"8\"": "search",  # Search circle
        "m21 21-4.35-4.35": "search",  # Search handle
    }

    for hint, name in svg_hints.items():
        if hint in svg.svg_content:
            return name

    return "unknown"


def determine_hca_layer(icon_name: str) -> str:
    """Determine which HCA layer an icon belongs to."""
    layer_mapping = {
        # Shared (Infrastructure)
        "database": "shared",
        "server": "shared",
        "cloud": "shared",
        "folder": "shared",
        "globe": "shared",
        "cog": "shared",
        # Entities (Data models)
        "user": "entities",
        "users-group": "entities",
        "key": "entities",
        "lock": "entities",
        "shield": "entities",
        "shield-check": "entities",
        "layers": "entities",
        "briefcase": "entities",
        # Features (Business logic)
        "search": "features",
        "download": "features",
        "trash": "features",
        "eye": "features",
        "edit-pen": "features",
        "refresh": "features",
        "plus": "features",
        "minus": "features",
        "check": "features",
        "check-requirement": "features",
        "x-mark": "features",
        "x-circle": "features",
        "lightning": "features",
        "clock": "features",
        "clock-circle": "features",
        "activity": "features",
        "filter": "features",
        "play": "features",
        "stop": "features",
        "table": "features",
        "document": "features",
        "document-text": "features",
        "database-minus": "features",
        "upload": "features",
        "arrow-left": "features",
        "arrow-left-long": "features",
        "arrow-right": "features",
        "pie-chart": "features",
        "calendar": "features",
        "package": "features",
        "close": "features",
        # Widgets (UI components)
        "chevron-down": "widgets",
        "chevron-up": "widgets",
        "chevron-right": "widgets",
        "chevron-left": "widgets",
        "chevron-double-left": "widgets",
        "chevron-double-right": "widgets",
        "sort": "widgets",
        "spinner": "widgets",
        "check-circle": "widgets",
        "warning": "widgets",
        "warning-triangle": "widgets",
        "error-triangle": "widgets",
        "info": "widgets",
        "info-circle": "widgets",
        "hamburger": "widgets",
        "dots-vertical": "widgets",
        "inbox-empty": "widgets",
        # Pages (Navigation)
        "dashboard": "pages",
        "document-stack": "pages",
        "home": "pages",
        "logout": "pages",
        "login": "pages",
        "sun": "pages",
        "moon": "pages",
        "external-link": "pages",
        "pulldb-logo": "pages",
    }
    return layer_mapping.get(icon_name, "unknown")


def analyze_templates(template_dir: Path) -> dict:
    """Analyze all templates and return structured results."""
    all_instances: list[SVGInstance] = []
    unique_icons: dict[str, UniqueIcon] = {}

    # Find all HTML templates
    for template_file in template_dir.rglob("*.html"):
        instances = extract_svgs_from_file(template_file, template_dir)
        all_instances.extend(instances)

    # Deduplicate by path hash
    for instance in all_instances:
        suggested_name = suggest_icon_name(instance)

        if instance.path_hash not in unique_icons:
            unique_icons[instance.path_hash] = UniqueIcon(
                path_hash=instance.path_hash,
                representative_svg=instance.svg_content,
                suggested_name=suggested_name,
                hca_layer=determine_hca_layer(suggested_name),
            )

        unique_icons[instance.path_hash].occurrences.append(instance)

    # Organize by HCA layer
    by_layer = defaultdict(list)
    for icon in unique_icons.values():
        by_layer[icon.hca_layer].append(icon)

    return {
        "total_instances": len(all_instances),
        "unique_icons": len(unique_icons),
        "by_layer": dict(by_layer),
        "all_icons": list(unique_icons.values()),
        "files_with_svgs": sorted(
            set(inst.file for inst in all_instances)
        ),
    }


def output_markdown(results: dict) -> str:
    """Generate markdown report."""
    lines = [
        "# Inline SVG Audit Report",
        "",
        f"**Total SVG instances**: {results['total_instances']}",
        f"**Unique icons**: {results['unique_icons']}",
        f"**Files with inline SVGs**: {len(results['files_with_svgs'])}",
        "",
        "## Icons by HCA Layer",
        "",
    ]

    layer_order = ["shared", "entities", "features", "widgets", "pages", "unknown"]
    for layer in layer_order:
        icons = results["by_layer"].get(layer, [])
        if not icons:
            continue

        lines.append(f"### {layer.title()} Layer ({len(icons)} icons)")
        lines.append("")
        lines.append("| Icon Name | Occurrences | Files |")
        lines.append("|-----------|-------------|-------|")

        for icon in sorted(icons, key=lambda x: x.suggested_name):
            files = sorted(set(occ.file for occ in icon.occurrences))
            files_str = ", ".join(f.split("/")[-1] for f in files[:3])
            if len(files) > 3:
                files_str += f" +{len(files) - 3} more"
            lines.append(
                f"| `{icon.suggested_name}` | {len(icon.occurrences)} | {files_str} |"
            )

        lines.append("")

    lines.append("## Files Requiring Migration")
    lines.append("")
    lines.append("| File | SVG Count |")
    lines.append("|------|-----------|")

    file_counts = defaultdict(int)
    for icon in results["all_icons"]:
        for occ in icon.occurrences:
            file_counts[occ.file] += 1

    for file, count in sorted(file_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| `{file}` | {count} |")

    lines.append("")
    lines.append("## Unknown Icons (Need Manual Review)")
    lines.append("")

    unknown = results["by_layer"].get("unknown", [])
    if unknown:
        for icon in unknown:
            lines.append(f"- Hash `{icon.path_hash}`: {len(icon.occurrences)} occurrences")
            lines.append(f"  - First seen in: {icon.occurrences[0].file}:{icon.occurrences[0].line}")
            lines.append(f"  - Context: `{icon.occurrences[0].context[-50:]}`")
    else:
        lines.append("*All icons successfully categorized*")

    return "\n".join(lines)


def output_json(results: dict) -> str:
    """Generate JSON report."""
    serializable = {
        "total_instances": results["total_instances"],
        "unique_icons": results["unique_icons"],
        "files_with_svgs": results["files_with_svgs"],
        "icons": [
            {
                "name": icon.suggested_name,
                "layer": icon.hca_layer,
                "path_hash": icon.path_hash,
                "occurrence_count": len(icon.occurrences),
                "files": sorted(set(occ.file for occ in icon.occurrences)),
            }
            for icon in results["all_icons"]
        ],
    }
    return json.dumps(serializable, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Audit inline SVGs in pullDB templates"
    )
    parser.add_argument(
        "--output",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path("pulldb/web/templates"),
        help="Path to templates directory",
    )
    args = parser.parse_args()

    if not args.template_dir.exists():
        print(f"Error: Template directory not found: {args.template_dir}", file=sys.stderr)
        sys.exit(1)

    results = analyze_templates(args.template_dir)

    if args.output == "json":
        print(output_json(results))
    else:
        print(output_markdown(results))


if __name__ == "__main__":
    main()
