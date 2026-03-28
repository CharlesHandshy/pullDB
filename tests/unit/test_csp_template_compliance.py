"""Regression test: no external resource URLs in templates.

The app's CSP is script-src/style-src/font-src/img-src/connect-src 'self' only.
Any <script src="https://...">, <link href="https://...">, etc. in a template
will be silently blocked by the browser — causing features to break with no
visible error (e.g. htmx loading from unpkg.com broke the backup picker).

This test scans all HTML templates and catches the problem at CI time.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Attributes that load external resources and must not point off-origin
_EXTERNAL_ATTRS = re.compile(
    r"""(?:src|href|action|data)\s*=\s*["'](https?://[^"']+)["']""",
    re.IGNORECASE,
)

# Allowlist: patterns that are explicitly permitted (e.g. canonical links,
# help-doc URLs that are not fetched by the browser as subresources).
# Keep this list minimal and add entries only with justification.
_ALLOWED_PATTERNS: list[re.Pattern[str]] = [
    # <link rel="canonical"> is metadata, not a subresource load.
    re.compile(r"""<link[^>]+rel=["']canonical["'][^>]*>""", re.IGNORECASE),
]


def _is_allowlisted(line: str) -> bool:
    return any(p.search(line) for p in _ALLOWED_PATTERNS)


def _find_template_root() -> Path:
    here = Path(__file__).resolve()
    repo = here.parents[2]  # tests/unit/ → tests/ → repo root
    template_dir = repo / "pulldb" / "web" / "templates"
    if not template_dir.is_dir():
        pytest.skip(f"Template directory not found: {template_dir}")
    return template_dir


def _collect_violations() -> list[tuple[Path, int, str, str]]:
    """Return (file, lineno, matched_url, raw_line) for each violation."""
    violations: list[tuple[Path, int, str, str]] = []
    template_root = _find_template_root()
    for path in sorted(template_root.rglob("*.html")):
        for lineno, raw_line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if _is_allowlisted(raw_line):
                continue
            for match in _EXTERNAL_ATTRS.finditer(raw_line):
                url = match.group(1)
                violations.append((path, lineno, url, raw_line.strip()))
    return violations


def test_no_external_resource_urls_in_templates() -> None:
    """Fail if any template references an external URL as a loadable resource.

    All JS, CSS, fonts, and images must be served from /static/ so the
    'self'-only CSP does not block them.
    """
    violations = _collect_violations()
    if not violations:
        return

    lines = ["External resource URLs found in templates (blocked by CSP):"]
    for path, lineno, url, raw_line in violations:
        lines.append(f"  {path.relative_to(Path(__file__).parents[2])}:{lineno}")
        lines.append(f"    url : {url}")
        lines.append(f"    line: {raw_line}")
    pytest.fail("\n".join(lines))
