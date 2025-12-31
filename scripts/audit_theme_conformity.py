#!/usr/bin/env python3
"""Theme Conformity Audit Script - Pre-commit hook for theme compliance.

HCA Layer: scripts (project root)

This script enforces theme variable usage standards:
1. No hardcoded hex colors in CSS (except design-tokens.css)
2. No hardcoded hex colors in HTML templates (except fallbacks in var())
3. No new [data-theme] selectors outside generated files
4. Inline styles must use var() for color values

Usage:
    python scripts/audit_theme_conformity.py [--fix] [--verbose]
    
Exit Codes:
    0 - All files compliant
    1 - Violations found
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple


# Paths relative to project root
WEB_DIR = Path("pulldb/web")
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_CSS_DIR = WEB_DIR / "static" / "css"
SHARED_CSS_DIR = WEB_DIR / "shared" / "css"
WIDGETS_CSS_DIR = WEB_DIR / "widgets" / "css"

# Files/patterns to exclude from checks
EXCLUDED_PATTERNS = [
    "_archived",
    "design-tokens.css",  # Raw palette definitions are allowed
    "generated/",  # Generated theme files
    "node_modules",
]

# Regex patterns
HEX_COLOR_PATTERN = re.compile(r"(?<!var\([^)]*?)#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])")
HEX_IN_VAR_FALLBACK = re.compile(r"var\([^,]+,\s*#[0-9a-fA-F]{3,8}\)")
DATA_THEME_PATTERN = re.compile(r"\[data-theme[=\"\']")
INLINE_COLOR_PATTERN = re.compile(r'style="[^"]*(?:color|background):\s*#[0-9a-fA-F]{3,8}')
RGB_RGBA_PATTERN = re.compile(r"(?<!var\()rgba?\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+")


class Violation(NamedTuple):
    """Represents a theme conformity violation."""
    file: Path
    line: int
    column: int
    message: str
    severity: str  # "error" or "warning"
    code: str


def is_excluded(path: Path) -> bool:
    """Check if path should be excluded from audit."""
    path_str = str(path)
    return any(pattern in path_str for pattern in EXCLUDED_PATTERNS)


def audit_css_file(file_path: Path) -> list[Violation]:
    """Audit a CSS file for theme violations."""
    violations = []
    
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return [Violation(file_path, 0, 0, f"Failed to read file: {e}", "error", "E001")]
    
    lines = content.split("\n")
    
    for line_num, line in enumerate(lines, 1):
        # Skip comments
        if line.strip().startswith("/*") or line.strip().startswith("*"):
            continue
            
        # Check for hardcoded hex colors (not in var() fallback)
        # First, remove valid fallback patterns to avoid false positives
        clean_line = HEX_IN_VAR_FALLBACK.sub("", line)
        
        for match in HEX_COLOR_PATTERN.finditer(clean_line):
            violations.append(Violation(
                file=file_path,
                line=line_num,
                column=match.start() + 1,
                message=f"Hardcoded hex color '{match.group()}' - use semantic variable instead",
                severity="error",
                code="E100",
            ))
        
        # Check for rgb/rgba colors (not in var())
        for match in RGB_RGBA_PATTERN.finditer(clean_line):
            # Allow rgba in status color definitions (like success_bg)
            if "rgba(" in line and ("success" in line.lower() or "warning" in line.lower() 
                                    or "error" in line.lower() or "info" in line.lower()):
                continue
            violations.append(Violation(
                file=file_path,
                line=line_num,
                column=match.start() + 1,
                message=f"Hardcoded rgb/rgba color - use semantic variable instead",
                severity="warning",
                code="W100",
            ))
        
        # Check for [data-theme] selectors (warning, not error)
        for match in DATA_THEME_PATTERN.finditer(line):
            violations.append(Violation(
                file=file_path,
                line=line_num,
                column=match.start() + 1,
                message="[data-theme] selector found - prefer semantic variables",
                severity="warning",
                code="W101",
            ))
    
    return violations


def audit_html_file(file_path: Path) -> list[Violation]:
    """Audit an HTML file for theme violations."""
    violations = []
    
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return [Violation(file_path, 0, 0, f"Failed to read file: {e}", "error", "E001")]
    
    lines = content.split("\n")
    
    for line_num, line in enumerate(lines, 1):
        # Check for inline styles with hardcoded colors
        for match in INLINE_COLOR_PATTERN.finditer(line):
            violations.append(Violation(
                file=file_path,
                line=line_num,
                column=match.start() + 1,
                message="Inline style with hardcoded color - use var() instead",
                severity="error",
                code="E200",
            ))
        
        # Check for <style> blocks with hardcoded hex (simplified check)
        if "<style>" in line.lower() or "</style>" in line.lower():
            continue  # Skip style tag lines themselves
            
        # In <style> blocks within HTML, check for hex colors
        # This is a simplified check - the CSS auditor handles external CSS
        if "style>" not in line:  # Not opening/closing style tag
            clean_line = HEX_IN_VAR_FALLBACK.sub("", line)
            for match in HEX_COLOR_PATTERN.finditer(clean_line):
                # Skip if in a JS string (common pattern for fallback values)
                if "||" in line or "??" in line:
                    continue
                violations.append(Violation(
                    file=file_path,
                    line=line_num,
                    column=match.start() + 1,
                    message=f"Hardcoded hex color '{match.group()}' in template",
                    severity="warning",
                    code="W200",
                ))
    
    return violations


def find_css_files(root: Path) -> list[Path]:
    """Find all CSS files to audit."""
    files = []
    for pattern in ["**/*.css"]:
        for file_path in root.glob(pattern):
            if not is_excluded(file_path):
                files.append(file_path)
    return files


def find_html_files(root: Path) -> list[Path]:
    """Find all HTML template files to audit."""
    files = []
    for pattern in ["**/*.html"]:
        for file_path in root.glob(pattern):
            if not is_excluded(file_path):
                files.append(file_path)
    return files


def print_violations(violations: list[Violation], verbose: bool = False) -> None:
    """Print violations in a readable format."""
    if not violations:
        return
    
    # Group by file
    by_file: dict[Path, list[Violation]] = {}
    for v in violations:
        by_file.setdefault(v.file, []).append(v)
    
    for file_path, file_violations in sorted(by_file.items()):
        print(f"\n{file_path}:")
        for v in sorted(file_violations, key=lambda x: x.line):
            severity_icon = "❌" if v.severity == "error" else "⚠️"
            print(f"  {severity_icon} L{v.line}:{v.column} [{v.code}] {v.message}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Audit theme conformity across CSS and HTML files"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output including warnings"
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help="Only report errors, not warnings"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to auto-fix violations (not yet implemented)"
    )
    args = parser.parse_args()
    
    # Find project root (directory containing pulldb/)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    if not (project_root / "pulldb").exists():
        print("Error: Could not find pulldb/ directory. Run from project root.")
        return 1
    
    print("🎨 Theme Conformity Audit")
    print("=" * 50)
    
    all_violations: list[Violation] = []
    
    # Audit CSS files
    css_dirs = [
        project_root / STATIC_CSS_DIR,
        project_root / SHARED_CSS_DIR,
        project_root / WIDGETS_CSS_DIR,
        project_root / WEB_DIR / "pages" / "css",
    ]
    
    css_files = []
    for css_dir in css_dirs:
        if css_dir.exists():
            css_files.extend(find_css_files(css_dir))
    
    print(f"\nAuditing {len(css_files)} CSS files...")
    for css_file in css_files:
        violations = audit_css_file(css_file)
        all_violations.extend(violations)
    
    # Audit HTML templates
    templates_root = project_root / TEMPLATES_DIR
    if templates_root.exists():
        html_files = find_html_files(templates_root)
        print(f"Auditing {len(html_files)} HTML templates...")
        for html_file in html_files:
            violations = audit_html_file(html_file)
            all_violations.extend(violations)
    
    # Filter by severity if requested
    if args.errors_only:
        all_violations = [v for v in all_violations if v.severity == "error"]
    
    # Report results
    errors = [v for v in all_violations if v.severity == "error"]
    warnings = [v for v in all_violations if v.severity == "warning"]
    
    if all_violations:
        print_violations(all_violations, args.verbose)
        print("\n" + "=" * 50)
        print(f"Found {len(errors)} error(s) and {len(warnings)} warning(s)")
        
        if errors:
            print("\n❌ Audit FAILED - fix errors before committing")
            return 1
        else:
            print("\n⚠️ Audit passed with warnings")
            return 0
    else:
        print("\n✅ All files compliant!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
