#!/usr/bin/env python3
"""Validate docs/KNOWLEDGE-POOL.md embedded JSON matches docs/KNOWLEDGE-POOL.json.

Usage:
  ./scripts/validate-knowledge-pool.py
"""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "docs" / "KNOWLEDGE-POOL.md"
JSON = ROOT / "docs" / "KNOWLEDGE-POOL.json"


def extract_json_block(md_text: str) -> str:
    """Return the first JSON fenced block following the heading.

    'Machine-readable index' heading.

    Raises SystemExit if no block is found.
    """
    pattern = (
        r"Machine-readable index \(JSON\).*?"
        r"```json\n(.*?)\n```"
    )
    m = re.search(pattern, md_text, re.S)
    if not m:
        raise SystemExit("No JSON block found in KNOWLEDGE-POOL.md")
    return m.group(1)


def main() -> int:
    """Validate that the embedded JSON block matches the standalone JSON file.

    Returns 0 on success, non-zero on mismatch or parse error.
    """
    md_text = MD.read_text(encoding="utf-8")
    embedded = extract_json_block(md_text)

    try:
        embedded_obj = json.loads(embedded)
    except json.JSONDecodeError as exc:
        print(f"ERROR: embedded JSON in {MD} is invalid: {exc}")
        return 2

    file_obj = json.loads(JSON.read_text(encoding="utf-8"))

    if embedded_obj != file_obj:
        print("Mismatch between embedded JSON and docs/KNOWLEDGE-POOL.json")
        print("--- Embedded JSON ---")
        print(json.dumps(embedded_obj, indent=2))
        print("--- File JSON ---")
        print(json.dumps(file_obj, indent=2))
        return 1

    print("OK: embedded JSON matches docs/KNOWLEDGE-POOL.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
