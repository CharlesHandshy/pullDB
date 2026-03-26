"""CI guard: verify committed CSS theme manifests match current ColorSchema defaults.

Usage:
    python scripts/check_css_manifest.py          # exits 0 if OK, 1 if drift
    python scripts/check_css_manifest.py --fix    # regenerate manifests in-place

The generated files are:
    pulldb/web/static/css/generated/manifest-light.css
    pulldb/web/static/css/generated/manifest-dark.css

These are auto-generated from LIGHT_PRESETS["Default"] and DARK_PRESETS["Default"].
If ColorSchema.to_css_variables() or a preset changes, the manifests must be
regenerated and committed — this script detects that drift.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# Resolve project root (two levels above this script)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _strip_timestamp(css: str) -> str:
    """Remove the auto-generated timestamp line so diffs are content-only."""
    return re.sub(r"^\s*\*\s*Generated:.*$", "", css, flags=re.MULTILINE)


def _extract_variables(css: str) -> dict[str, str]:
    """Return {--var-name: value} from all CSS custom property declarations."""
    return {
        m.group(1).strip(): m.group(2).strip()
        for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", css)
    }


def check_manifests(fix: bool = False) -> bool:
    """Compare committed manifests against freshly generated ones.

    Args:
        fix: When True, overwrite committed manifests with the fresh content.

    Returns:
        True if manifests are up-to-date (or were fixed), False if drift detected.
    """
    from pulldb.domain.color_schemas import DARK_PRESETS, LIGHT_PRESETS
    from pulldb.web.features.admin.theme_generator import generate_theme_css

    light_schema = LIGHT_PRESETS["Default"]
    dark_schema = DARK_PRESETS["Default"]

    generated_dir = (
        _PROJECT_ROOT / "pulldb" / "web" / "static" / "css" / "generated"
    )
    manifests = {
        "manifest-light.css": generate_theme_css(light_schema, mode="light"),
        "manifest-dark.css": generate_theme_css(dark_schema, mode="dark"),
    }

    all_ok = True
    for filename, fresh_css in manifests.items():
        committed_path = generated_dir / filename
        if not committed_path.exists():
            print(f"MISSING  {filename} — file does not exist in repository")
            all_ok = False
            if fix:
                committed_path.parent.mkdir(parents=True, exist_ok=True)
                committed_path.write_text(fresh_css, encoding="utf-8")
                print(f"  -> Created {filename}")
            continue

        committed_css = committed_path.read_text(encoding="utf-8")

        # Compare CSS variables only (ignores timestamp comment)
        committed_vars = _extract_variables(_strip_timestamp(committed_css))
        fresh_vars = _extract_variables(_strip_timestamp(fresh_css))

        added = sorted(set(fresh_vars) - set(committed_vars))
        removed = sorted(set(committed_vars) - set(fresh_vars))
        changed = sorted(
            k for k in fresh_vars if k in committed_vars and fresh_vars[k] != committed_vars[k]
        )

        if not (added or removed or changed):
            print(f"OK       {filename}")
            continue

        all_ok = False
        print(f"DRIFT    {filename}")
        for var in added:
            print(f"  + {var}: {fresh_vars[var]}")
        for var in removed:
            print(f"  - {var}: {committed_vars[var]}")
        for var in changed:
            print(f"  ~ {var}: {committed_vars[var]!r}  ->  {fresh_vars[var]!r}")

        if fix:
            committed_path.write_text(fresh_css, encoding="utf-8")
            print(f"  -> Updated {filename}")

    return all_ok or fix


def main() -> int:
    fix = "--fix" in sys.argv
    ok = check_manifests(fix=fix)
    if not ok:
        print(
            "\nCSS manifest drift detected. Run with --fix to regenerate:\n"
            "  python scripts/check_css_manifest.py --fix\n"
            "Then commit the updated manifest files."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
