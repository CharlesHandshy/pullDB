#!/usr/bin/env python3
"""
Extract and catalog all inline SVGs from pullDB web templates.

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

    # SVG content-based suggestions
    svg_hints = {
        "M3 3h7v7H3": "dashboard",  # Grid pattern
        "circle cx": "user",  # Head circle
        "ellipse cx": "database",  # Database ellipse
        "M21 21l-6-6": "search",  # Search diagonal
        "M6 9l6 6 6-6": "chevron-down",
        "M9 18l6-6-6-6": "chevron-right",
        "M15 18l-6-6 6-6": "chevron-left",
        "M18 6L6 18": "close",  # X pattern
        "M5 12h14": "minus",
        "M12 5v14": "plus",  # Plus vertical
        "polyline points=\"20 6 9 17 4 12\"": "check",
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
        "layers": "entities",
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
        "x-mark": "features",
        "lightning": "features",
        "clock": "features",
        "activity": "features",
        "filter": "features",
        # Widgets (UI components)
        "chevron-down": "widgets",
        "chevron-up": "widgets",
        "chevron-right": "widgets",
        "chevron-left": "widgets",
        "sort": "widgets",
        "close": "widgets",
        "spinner": "widgets",
        "check-circle": "widgets",
        "warning": "widgets",
        "info": "widgets",
        "hamburger": "widgets",
        "dots-vertical": "widgets",
        # Pages (Navigation)
        "dashboard": "pages",
        "document-stack": "pages",
        "home": "pages",
        "logout": "pages",
        "login": "pages",
        "sun": "pages",
        "moon": "pages",
        "external-link": "pages",
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
