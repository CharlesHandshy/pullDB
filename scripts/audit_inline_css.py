#!/usr/bin/env python3
"""
Audit inline CSS in pullDB web templates.

This script finds all <style> blocks in HTML templates and reports:
1. Files with inline CSS
2. Line counts per block
3. Priority ranking by total CSS lines
4. Selector patterns for extraction candidates

Usage:
    python scripts/audit_inline_css.py [--min-lines 10] [--output json|markdown]

Output:
    - Files sorted by inline CSS line count
    - Extraction priority recommendations
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StyleBlock:
    """A single <style> block found in a template."""

    file: str
    start_line: int
    end_line: int
    line_count: int
    content: str
    selectors: list[str]


def extract_selectors(css_content: str) -> list[str]:
    """Extract CSS selectors from a style block."""
    # Pattern to match selectors (before {)
    selector_pattern = re.compile(
        r"^\s*([.#@\[\w][^{]+?)\s*\{",
        re.MULTILINE,
    )
    selectors = selector_pattern.findall(css_content)
    # Clean and dedupe
    cleaned = []
    for sel in selectors:
        sel = sel.strip()
        if sel and sel not in cleaned:
            cleaned.append(sel)
    return cleaned[:20]  # Limit to first 20


def extract_style_blocks(file_path: Path, base_dir: Path) -> list[StyleBlock]:
    """Extract all <style> blocks from a template."""
    blocks = []
    content = file_path.read_text(encoding="utf-8")

    # Pattern to match <style> blocks
    style_pattern = re.compile(
        r"<style[^>]*>(.*?)</style>",
        re.DOTALL | re.IGNORECASE,
    )

    for match in style_pattern.finditer(content):
        css_content = match.group(1)

        # Skip empty or trivial blocks
        css_lines = [l for l in css_content.split("\n") if l.strip()]
        if len(css_lines) < 3:
            continue

        # Find line numbers
        start_pos = match.start()
        end_pos = match.end()
        start_line = content[:start_pos].count("\n") + 1
        end_line = content[:end_pos].count("\n") + 1

        try:
            rel_path = str(file_path.relative_to(base_dir))
        except ValueError:
            rel_path = str(file_path)

        blocks.append(
            StyleBlock(
                file=rel_path,
                start_line=start_line,
                end_line=end_line,
                line_count=len(css_lines),
                content=css_content,
                selectors=extract_selectors(css_content),
            )
        )

    return blocks


def categorize_selector(selector: str) -> str:
    """Categorize a selector for component extraction."""
    selector_lower = selector.lower()

    categories = {
        "stat": "stat-cards",
        "card": "cards",
        "btn": "buttons",
        "button": "buttons",
        "form": "forms",
        "input": "forms",
        "select": "forms",
        "table": "tables",
        "modal": "modals",
        "dropdown": "dropdowns",
        "nav": "navigation",
        "sidebar": "navigation",
        "breadcrumb": "navigation",
        "tab": "tabs",
        "alert": "alerts",
        "badge": "badges",
        "status": "badges",
        "toast": "toasts",
        "grid": "layout",
        "container": "layout",
        "section": "layout",
        "page": "layout",
        "header": "layout",
        "footer": "layout",
        "search": "widgets",
        "filter": "widgets",
        "env-": "widgets",
        "customer-": "widgets",
        "backup-": "widgets",
    }

    for pattern, category in categories.items():
        if pattern in selector_lower:
            return category

    return "other"


def analyze_templates(template_dir: Path, min_lines: int) -> dict:
    """Analyze all templates for inline CSS."""
    all_blocks: list[StyleBlock] = []

    for template_file in template_dir.rglob("*.html"):
        blocks = extract_style_blocks(template_file, template_dir)
        all_blocks.extend(blocks)

    # Filter by minimum lines
    significant_blocks = [b for b in all_blocks if b.line_count >= min_lines]

    # Aggregate by file
    by_file = defaultdict(list)
    for block in significant_blocks:
        by_file[block.file].append(block)

    # Sort files by total CSS lines
    file_totals = {
        file: sum(b.line_count for b in blocks)
        for file, blocks in by_file.items()
    }

    # Categorize selectors
    selector_categories = defaultdict(set)
    for block in significant_blocks:
        for selector in block.selectors:
            category = categorize_selector(selector)
            selector_categories[category].add(selector)

    return {
        "total_blocks": len(all_blocks),
        "significant_blocks": len(significant_blocks),
        "total_inline_css_lines": sum(b.line_count for b in all_blocks),
        "files_by_priority": sorted(
            file_totals.items(),
            key=lambda x: -x[1],
        ),
        "by_file": dict(by_file),
        "selector_categories": {
            k: sorted(v) for k, v in selector_categories.items()
        },
    }


def output_markdown(results: dict, min_lines: int) -> str:
    """Generate markdown report."""
    lines = [
        "# Inline CSS Audit Report",
        "",
        f"**Total `<style>` blocks**: {results['total_blocks']}",
        f"**Blocks ≥{min_lines} lines**: {results['significant_blocks']}",
        f"**Total inline CSS lines**: {results['total_inline_css_lines']}",
        "",
        "## Files by Priority (Most CSS First)",
        "",
        "| Priority | File | CSS Lines | Blocks | Action |",
        "|----------|------|-----------|--------|--------|",
    ]

    priority_labels = ["🔴 Critical", "🟠 High", "🟡 Medium", "🟢 Low"]
    for i, (file, total_lines) in enumerate(results["files_by_priority"]):
        priority = priority_labels[min(i // 3, 3)]
        blocks = results["by_file"][file]
        action = "Extract to components.css" if total_lines > 100 else "Extract to feature CSS"
        lines.append(
            f"| {priority} | `{file.split('/')[-1]}` | {total_lines} | {len(blocks)} | {action} |"
        )

    lines.extend([
        "",
        "## Selector Categories (Extraction Candidates)",
        "",
    ])

    for category, selectors in sorted(results["selector_categories"].items()):
        lines.append(f"### {category.title()} ({len(selectors)} selectors)")
        lines.append("")
        for sel in selectors[:10]:
            lines.append(f"- `{sel}`")
        if len(selectors) > 10:
            lines.append(f"- ... and {len(selectors) - 10} more")
        lines.append("")

    lines.extend([
        "## Detailed Breakdown",
        "",
    ])

    for file, total_lines in results["files_by_priority"][:10]:
        blocks = results["by_file"][file]
        lines.append(f"### {file}")
        lines.append("")
        for block in blocks:
            lines.append(f"**Lines {block.start_line}-{block.end_line}** ({block.line_count} lines)")
            if block.selectors:
                lines.append(f"- Key selectors: `{', '.join(block.selectors[:5])}`")
            lines.append("")

    return "\n".join(lines)


def output_json(results: dict) -> str:
    """Generate JSON report."""
    serializable = {
        "total_blocks": results["total_blocks"],
        "significant_blocks": results["significant_blocks"],
        "total_inline_css_lines": results["total_inline_css_lines"],
        "files": [
            {
                "file": file,
                "total_lines": total,
                "blocks": [
                    {
                        "start_line": b.start_line,
                        "end_line": b.end_line,
                        "line_count": b.line_count,
                        "selectors": b.selectors,
                    }
                    for b in results["by_file"][file]
                ],
            }
            for file, total in results["files_by_priority"]
        ],
        "selector_categories": results["selector_categories"],
    }
    return json.dumps(serializable, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Audit inline CSS in pullDB templates"
    )
    parser.add_argument(
        "--output",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=10,
        help="Minimum lines to consider significant (default: 10)",
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

    results = analyze_templates(args.template_dir, args.min_lines)

    if args.output == "json":
        print(output_json(results))
    else:
        print(output_markdown(results, args.min_lines))


if __name__ == "__main__":
    main()
