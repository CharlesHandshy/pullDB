#!/usr/bin/env python3
"""
Validate HCA template path compliance in pullDB routes.

This script checks all TemplateResponse calls to ensure templates
are properly located under features/{feature}/ following HCA principles.

Usage:
    python scripts/validate_template_paths.py [--fix-suggestions]

Violations:
    - Root-level templates (except base.html, partials/, widgets/)
    - Templates in old-style folders (admin/, manager/, audit/)

Exit codes:
    0 - All paths compliant
    1 - Violations found
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Violation:
    """A template path violation."""

    file: str
    line: int
    template_path: str
    reason: str
    suggested_fix: str


# Allowed root-level templates
ALLOWED_ROOT = {
    "base.html",
}

# Allowed prefixes (shared infrastructure)
ALLOWED_PREFIXES = {
    "partials/",
    "widgets/",
    "features/",
}

# Old-style folders that should be migrated
LEGACY_FOLDERS = {
    "admin/",
    "manager/",
    "audit/",
}


def extract_template_paths(file_path: Path) -> list[tuple[int, str]]:
    """Extract all template paths from a Python file."""
    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Patterns for template references
    patterns = [
        # TemplateResponse("path", ...) or TemplateResponse('path', ...)
        re.compile(r'TemplateResponse\s*\(\s*["\']([^"\']+)["\']'),
        # templates.TemplateResponse("path", ...)
        re.compile(r'templates\.TemplateResponse\s*\(\s*["\']([^"\']+)["\']'),
        # request.state.templates.TemplateResponse("path", ...)
        re.compile(r'\.TemplateResponse\s*\(\s*["\']([^"\']+)["\']'),
        # render_template("path", ...)
        re.compile(r'render_template\s*\(\s*["\']([^"\']+)["\']'),
        # template="path"
        re.compile(r'template\s*=\s*["\']([^"\']+)["\']'),
    ]

    results = []
    for line_num, line in enumerate(lines, 1):
        for pattern in patterns:
            for match in pattern.finditer(line):
                template_path = match.group(1)
                if template_path.endswith(".html"):
                    results.append((line_num, template_path))

    return results


def suggest_fix(template_path: str) -> str:
    """Suggest the correct HCA-compliant path."""
    # Map legacy paths to features/ paths
    mappings = {
        # Root templates
        "login.html": "features/auth/login.html",
        "index.html": "features/dashboard/dashboard.html",
        "dashboard.html": "features/dashboard/dashboard.html",
        "restore.html": "features/restore/restore.html",
        "my_job.html": "features/jobs/detail.html",
        "my_jobs.html": "features/jobs/my_jobs.html",
        "job_profile.html": "features/jobs/profile.html",
        "job_history.html": "features/jobs/history.html",
        "search.html": "features/search/index.html",
        "error.html": "features/shared/error.html",
        # Admin folder
        "admin/index.html": "features/admin/index.html",
        "admin/users.html": "features/admin/users.html",
        "admin/user_detail.html": "features/admin/user_detail.html",
        "admin/hosts.html": "features/admin/hosts.html",
        "admin/host_detail.html": "features/admin/host_detail.html",
        "admin/jobs.html": "features/admin/jobs.html",
        "admin/settings.html": "features/admin/settings.html",
        "admin/maintenance.html": "features/admin/maintenance.html",
        "admin/cleanup.html": "features/admin/cleanup.html",
        "admin/logo.html": "features/admin/logo.html",
        "admin/styleguide.html": "features/admin/styleguide.html",
        # Manager folder
        "manager/index.html": "features/manager/index.html",
        "manager/create_user.html": "features/manager/create_user.html",
        "manager/my_team.html": "features/manager/my_team.html",
        "manager/submit_for_user.html": "features/manager/submit_for_user.html",
        "manager/user_detail.html": "features/manager/user_detail.html",
        # Audit folder
        "audit/index.html": "features/audit/index.html",
        "audit/my_actions.html": "features/audit/my_actions.html",
        "audit/on_me.html": "features/audit/on_me.html",
    }

    if template_path in mappings:
        return mappings[template_path]

    # Try to infer from path structure
    if template_path.startswith("admin/"):
        return template_path.replace("admin/", "features/admin/", 1)
    if template_path.startswith("manager/"):
        return template_path.replace("manager/", "features/manager/", 1)
    if template_path.startswith("audit/"):
        return template_path.replace("audit/", "features/audit/", 1)

    # For root templates, guess the feature
    return f"features/unknown/{template_path}"


def check_template_path(template_path: str) -> tuple[bool, str]:
    """
    Check if a template path is HCA-compliant.

    Returns:
        (is_valid, reason)
    """
    # Check allowed root templates
    if template_path in ALLOWED_ROOT:
        return True, ""

    # Check allowed prefixes
    for prefix in ALLOWED_PREFIXES:
        if template_path.startswith(prefix):
            return True, ""

    # Check for legacy folders
    for legacy in LEGACY_FOLDERS:
        if template_path.startswith(legacy):
            return False, f"Legacy folder '{legacy}' - migrate to features/{legacy}"

    # Root-level template (no / in path)
    if "/" not in template_path:
        return False, f"Root-level template - migrate to features/"

    return False, "Unknown path structure"


def analyze_routes(routes_dir: Path) -> list[Violation]:
    """Analyze all route files for template path violations."""
    violations = []

    for py_file in routes_dir.rglob("*.py"):
        paths = extract_template_paths(py_file)

        for line_num, template_path in paths:
            is_valid, reason = check_template_path(template_path)

            if not is_valid:
                violations.append(
                    Violation(
                        file=str(py_file.relative_to(Path.cwd())),
                        line=line_num,
                        template_path=template_path,
                        reason=reason,
                        suggested_fix=suggest_fix(template_path),
                    )
                )

    return violations


def output_report(violations: list[Violation], show_fixes: bool) -> str:
    """Generate violation report."""
    if not violations:
        return "✅ All template paths are HCA-compliant!"

    lines = [
        "# HCA Template Path Violations",
        "",
        f"**Total violations**: {len(violations)}",
        "",
        "## Violations",
        "",
        "| File | Line | Template | Reason |" + (" Fix |" if show_fixes else ""),
        "|------|------|----------|--------|" + ("-----|" if show_fixes else ""),
    ]

    for v in sorted(violations, key=lambda x: (x.file, x.line)):
        row = f"| `{v.file.split('/')[-1]}` | {v.line} | `{v.template_path}` | {v.reason} |"
        if show_fixes:
            row += f" `{v.suggested_fix}` |"
        lines.append(row)

    lines.extend([
        "",
        "## Migration Summary",
        "",
    ])

    # Group by target feature
    by_feature = {}
    for v in violations:
        feature = v.suggested_fix.split("/")[1] if "/" in v.suggested_fix else "unknown"
        if feature not in by_feature:
            by_feature[feature] = []
        by_feature[feature].append(v)

    for feature, vios in sorted(by_feature.items()):
        lines.append(f"### features/{feature}/ ({len(vios)} templates)")
        for v in vios:
            lines.append(f"- `{v.template_path}` → `{v.suggested_fix}`")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Validate HCA template path compliance"
    )
    parser.add_argument(
        "--fix-suggestions",
        action="store_true",
        help="Show suggested fixes in output",
    )
    parser.add_argument(
        "--routes-dir",
        type=Path,
        default=Path("pulldb/web"),
        help="Path to routes directory (default: pulldb/web)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    if not args.routes_dir.exists():
        print(f"Error: Routes directory not found: {args.routes_dir}", file=sys.stderr)
        sys.exit(1)

    violations = analyze_routes(args.routes_dir)

    if args.json:
        import json
        print(json.dumps([
            {
                "file": v.file,
                "line": v.line,
                "template": v.template_path,
                "reason": v.reason,
                "fix": v.suggested_fix,
            }
            for v in violations
        ], indent=2))
    else:
        print(output_report(violations, args.fix_suggestions))

    # Exit with error if violations found
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
