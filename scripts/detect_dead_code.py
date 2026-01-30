#!/usr/bin/env python3
"""Dead code detector for pullDB with dynamic dispatch awareness.

HCA Layer: shared (pulldb/infra/ equivalent - tooling)

This script performs multi-pass dead code detection that accounts for:
- Static Python imports and calls
- Dynamic dispatch (getattr, globals, importlib)
- Jinja2 template references
- JavaScript fetch/HTMX calls
- FastAPI route decorators
- Click/Typer CLI decorators
- __all__ exports (intentional public API)

Usage:
    python scripts/detect_dead_code.py [--strict] [--output json|text] [--confidence 90]
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Confidence thresholds
CONFIDENCE_DEAD = 99  # Almost certainly dead
CONFIDENCE_LIKELY = 90  # Likely dead, verify
CONFIDENCE_MAYBE = 70  # Possibly dead, needs review
CONFIDENCE_KEEP = 0  # Definitely not dead


@dataclass
class Symbol:
    """A symbol (function, class, variable) in the codebase."""

    name: str
    file: Path
    line: int
    kind: str  # 'function', 'class', 'method', 'variable'
    module_path: str  # e.g., 'pulldb.worker.service'

    # Classification flags
    is_exported: bool = False  # In __all__
    is_decorated: bool = False  # Has decorators
    is_route: bool = False  # FastAPI route
    is_cli_command: bool = False  # Click/Typer command
    is_test: bool = False  # Test function
    is_private: bool = False  # Starts with _
    is_dunder: bool = False  # Starts with __

    # Reference tracking
    static_importers: Set[str] = field(default_factory=set)
    static_callers: Set[str] = field(default_factory=set)
    dynamic_refs: Set[str] = field(default_factory=set)
    template_refs: Set[str] = field(default_factory=set)
    js_refs: Set[str] = field(default_factory=set)
    string_refs: Set[str] = field(default_factory=set)

    @property
    def full_name(self) -> str:
        return f"{self.module_path}.{self.name}"

    @property
    def is_entry_point(self) -> bool:
        """Check if this is an entry point that shouldn't be removed."""
        return (
            self.is_route
            or self.is_cli_command
            or self.is_exported
            or self.name == "__main__"
            or self.name == "main"
        )

    @property
    def has_any_reference(self) -> bool:
        """Check if this symbol has any reference anywhere."""
        return bool(
            self.static_importers
            or self.static_callers
            or self.dynamic_refs
            or self.template_refs
            or self.js_refs
            or self.string_refs
        )

    def confidence_dead(self) -> int:
        """Return confidence level that this code is dead (0-100)."""
        # Definitely not dead
        if self.is_entry_point:
            return CONFIDENCE_KEEP
        if self.is_dunder:
            return CONFIDENCE_KEEP
        if self.has_any_reference:
            return CONFIDENCE_KEEP

        # Likely dead
        if self.is_private and not self.has_any_reference:
            return CONFIDENCE_DEAD
        if self.is_test:
            return CONFIDENCE_MAYBE  # Tests might be intentionally kept

        # Default for unreferenced public symbols
        return CONFIDENCE_LIKELY


@dataclass
class DeadCodeReport:
    """Report of potentially dead code."""

    candidates: List[Symbol]
    entry_points: Set[str]
    total_symbols: int
    analysis_summary: Dict[str, int]


class DeadCodeDetector:
    """Multi-pass dead code detection with dynamic dispatch awareness."""

    # Patterns that indicate intentional framework wiring
    ROUTE_DECORATORS = {
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "head",
        "options",
        "route",
        "websocket",
    }
    CLI_DECORATORS = {"command", "group", "argument", "option"}

    # Files/patterns to skip
    SKIP_PATTERNS = [
        r".*/__pycache__/.*",
        r".*/_archived/.*",
        r".*/\..*",
        r".*/build/.*",
        r".*/dist.*/.*",
        r".*/\.egg-info/.*",
    ]

    # False positive patterns (names that look unused but aren't)
    FALSE_POSITIVE_PATTERNS = [
        r"^test_",  # Test functions
        r"^Test",  # Test classes
        r"^fixture_",  # Pytest fixtures
        r"^conftest$",  # Pytest config
        r"^setup$",  # Setup functions
        r"^teardown$",  # Teardown functions
        r"^__.*__$",  # Dunder methods
    ]

    def __init__(self, root: Path):
        self.root = root
        self.symbols: Dict[str, Symbol] = {}
        self.imports: Dict[str, Set[str]] = defaultdict(set)  # file -> imported names
        self.entry_points: Set[str] = set()

    def analyze(self, min_confidence: int = 90) -> DeadCodeReport:
        """Run full analysis pipeline."""
        print("Pass 1: Collecting symbols...", file=sys.stderr)
        self._collect_symbols()
        print(f"  Found {len(self.symbols)} symbols", file=sys.stderr)

        print("Pass 2: Finding static imports...", file=sys.stderr)
        self._find_static_imports()

        print("Pass 3: Finding static calls...", file=sys.stderr)
        self._find_static_calls()

        print("Pass 4: Finding dynamic references...", file=sys.stderr)
        self._find_dynamic_refs()

        print("Pass 5: Finding template references...", file=sys.stderr)
        self._find_template_refs()

        print("Pass 6: Finding JavaScript references...", file=sys.stderr)
        self._find_js_refs()

        print("Pass 7: Finding string-based references...", file=sys.stderr)
        self._find_string_refs()

        print("Pass 8: Identifying entry points...", file=sys.stderr)
        self._identify_entry_points()

        print("Pass 9: Computing candidates...", file=sys.stderr)
        candidates = self._compute_candidates(min_confidence)

        # Build summary
        summary = {
            "total_symbols": len(self.symbols),
            "entry_points": len(self.entry_points),
            "dead_candidates": len(candidates),
            "by_confidence": defaultdict(int),
            "by_kind": defaultdict(int),
        }
        for c in candidates:
            summary["by_confidence"][c.confidence_dead()] += 1
            summary["by_kind"][c.kind] += 1

        return DeadCodeReport(
            candidates=candidates,
            entry_points=self.entry_points,
            total_symbols=len(self.symbols),
            analysis_summary=dict(summary),
        )

    def _should_skip(self, path: Path) -> bool:
        """Check if path should be skipped."""
        path_str = str(path)
        return any(re.match(p, path_str) for p in self.SKIP_PATTERNS)

    def _path_to_module(self, path: Path) -> str:
        """Convert file path to module path."""
        try:
            rel = path.relative_to(self.root)
            parts = list(rel.parts)
            if parts[-1] == "__init__.py":
                parts = parts[:-1]
            else:
                parts[-1] = parts[-1].replace(".py", "")
            return ".".join(parts)
        except ValueError:
            return str(path)

    def _collect_symbols(self):
        """Pass 1: Collect all function/class definitions."""
        for py_file in self.root.rglob("*.py"):
            if self._should_skip(py_file):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError) as e:
                print(f"  Warning: Could not parse {py_file}: {e}", file=sys.stderr)
                continue

            module_path = self._path_to_module(py_file)

            # Check for __all__
            exports = self._extract_all_exports(tree)

            # Process all definitions
            for node in ast.walk(tree):
                symbol = self._node_to_symbol(node, py_file, module_path, exports)
                if symbol:
                    key = f"{py_file}:{symbol.name}"
                    self.symbols[key] = symbol

    def _extract_all_exports(self, tree: ast.Module) -> Set[str]:
        """Extract names from __all__ = [...] if present."""
        exports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, ast.List):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(
                                    elt.value, str
                                ):
                                    exports.add(elt.value)
        return exports

    def _node_to_symbol(
        self, node: ast.AST, file: Path, module: str, exports: Set[str]
    ) -> Optional[Symbol]:
        """Convert an AST node to a Symbol if it's a definition."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = [self._get_decorator_name(d) for d in node.decorator_list]
            is_route = any(
                d.split(".")[-1] in self.ROUTE_DECORATORS for d in decorators if d
            )
            is_cli = any(
                d.split(".")[-1] in self.CLI_DECORATORS for d in decorators if d
            )

            return Symbol(
                name=node.name,
                file=file,
                line=node.lineno,
                kind="function",
                module_path=module,
                is_exported=node.name in exports,
                is_decorated=bool(node.decorator_list),
                is_route=is_route,
                is_cli_command=is_cli,
                is_test="test" in str(file).lower() or node.name.startswith("test_"),
                is_private=node.name.startswith("_") and not node.name.startswith("__"),
                is_dunder=node.name.startswith("__") and node.name.endswith("__"),
            )
        elif isinstance(node, ast.ClassDef):
            decorators = [self._get_decorator_name(d) for d in node.decorator_list]
            return Symbol(
                name=node.name,
                file=file,
                line=node.lineno,
                kind="class",
                module_path=module,
                is_exported=node.name in exports,
                is_decorated=bool(node.decorator_list),
                is_test="test" in str(file).lower() or node.name.startswith("Test"),
                is_private=node.name.startswith("_") and not node.name.startswith("__"),
                is_dunder=node.name.startswith("__") and node.name.endswith("__"),
            )
        return None

    def _get_decorator_name(self, decorator: ast.expr) -> Optional[str]:
        """Extract decorator name from AST node."""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return f"{self._get_decorator_name(decorator.value)}.{decorator.attr}"
        elif isinstance(decorator, ast.Call):
            return self._get_decorator_name(decorator.func)
        return None

    def _find_static_imports(self):
        """Pass 2: Find all static import statements."""
        for py_file in self.root.rglob("*.py"):
            if self._should_skip(py_file):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError):
                continue

            file_str = str(py_file)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports[file_str].add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for alias in node.names:
                            imported_name = alias.name
                            # Find symbols that match
                            for key, sym in self.symbols.items():
                                if sym.name == imported_name:
                                    sym.static_importers.add(file_str)

    def _find_static_calls(self):
        """Pass 3: Find all static function/class calls."""
        for py_file in self.root.rglob("*.py"):
            if self._should_skip(py_file):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError):
                continue

            file_str = str(py_file)

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    called_name = self._get_call_name(node.func)
                    if called_name:
                        # Find symbols that match
                        for key, sym in self.symbols.items():
                            if sym.name == called_name:
                                sym.static_callers.add(file_str)
                elif isinstance(node, ast.Name):
                    # Direct name reference (not just call)
                    for key, sym in self.symbols.items():
                        if sym.name == node.id and str(sym.file) != file_str:
                            sym.static_callers.add(file_str)

    def _get_call_name(self, node: ast.expr) -> Optional[str]:
        """Extract the called function/class name."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _find_dynamic_refs(self):
        """Pass 4: Find dynamic dispatch patterns (getattr, globals, etc.)."""
        dynamic_patterns = [
            r"getattr\s*\(\s*\w+\s*,\s*['\"](\w+)['\"]",
            r"globals\s*\(\s*\)\s*\[\s*['\"](\w+)['\"]",
            r"locals\s*\(\s*\)\s*\[\s*['\"](\w+)['\"]",
            r"__dict__\s*\[\s*['\"](\w+)['\"]",
            r"importlib\.import_module\s*\(\s*['\"]([^'\"]+)['\"]",
        ]

        for py_file in self.root.rglob("*.py"):
            if self._should_skip(py_file):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            file_str = str(py_file)

            for pattern in dynamic_patterns:
                for match in re.finditer(pattern, source):
                    ref_name = match.group(1)
                    for key, sym in self.symbols.items():
                        if sym.name == ref_name:
                            sym.dynamic_refs.add(f"{file_str}:dynamic")

    def _find_template_refs(self):
        """Pass 5: Find Jinja2 template references."""
        template_patterns = [
            r"\{\{\s*(\w+)\s*\(",  # {{ function_name( }}
            r"\{\%\s*\w+\s+(\w+)",  # {% tag variable %}
            r"\{\{\s*(\w+)\.",  # {{ object.method }}
        ]

        templates_dir = self.root / "pulldb" / "web" / "templates"
        if not templates_dir.exists():
            return

        for template_file in templates_dir.rglob("*.html"):
            try:
                source = template_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            file_str = str(template_file)

            for pattern in template_patterns:
                for match in re.finditer(pattern, source):
                    ref_name = match.group(1)
                    for key, sym in self.symbols.items():
                        if sym.name == ref_name:
                            sym.template_refs.add(file_str)

    def _find_js_refs(self):
        """Pass 6: Find JavaScript references (fetch, HTMX)."""
        js_patterns = [
            r"fetch\s*\(\s*['\"`]([^'\"`]+)['\"`]",  # fetch('/api/...')
            r"hx-get\s*=\s*['\"]([^'\"]+)['\"]",  # hx-get="/path"
            r"hx-post\s*=\s*['\"]([^'\"]+)['\"]",  # hx-post="/path"
            r"hx-delete\s*=\s*['\"]([^'\"]+)['\"]",
            r"hx-put\s*=\s*['\"]([^'\"]+)['\"]",
            r"hx-patch\s*=\s*['\"]([^'\"]+)['\"]",
        ]

        static_dir = self.root / "pulldb" / "web" / "static"
        if not static_dir.exists():
            return

        # Search both JS files and HTML templates
        search_dirs = [static_dir, self.root / "pulldb" / "web" / "templates"]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for file in search_dir.rglob("*"):
                if file.suffix not in (".js", ".html", ".htm"):
                    continue
                try:
                    source = file.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue

                file_str = str(file)

                for pattern in js_patterns:
                    for match in re.finditer(pattern, source):
                        path = match.group(1)
                        # Mark any route handlers for this path as referenced
                        for key, sym in self.symbols.items():
                            if sym.is_route:
                                sym.js_refs.add(f"{file_str}:{path}")

    def _find_string_refs(self):
        """Pass 7: Find string-based references to symbol names."""
        for py_file in self.root.rglob("*.py"):
            if self._should_skip(py_file):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            file_str = str(py_file)

            for key, sym in self.symbols.items():
                # Look for string literals containing the symbol name
                patterns = [
                    rf"['\"]({re.escape(sym.name)})['\"]",
                ]
                for pattern in patterns:
                    if re.search(pattern, source):
                        # Don't count self-references
                        if str(sym.file) != file_str:
                            sym.string_refs.add(file_str)

    def _identify_entry_points(self):
        """Pass 8: Identify entry points that are definitely reachable."""
        for key, sym in self.symbols.items():
            # Entry points
            if sym.name in ("main", "__main__"):
                self.entry_points.add(key)
            # Routes are reachable via HTTP
            if sym.is_route:
                self.entry_points.add(key)
            # CLI commands are reachable via CLI
            if sym.is_cli_command:
                self.entry_points.add(key)
            # Exported symbols are intentional public API
            if sym.is_exported:
                self.entry_points.add(key)

    def _compute_candidates(self, min_confidence: int) -> List[Symbol]:
        """Pass 9: Compute dead code candidates."""
        candidates = []

        for key, sym in self.symbols.items():
            confidence = sym.confidence_dead()
            if confidence >= min_confidence:
                candidates.append(sym)

        # Sort by confidence (highest first), then by file and line
        return sorted(candidates, key=lambda s: (-s.confidence_dead(), str(s.file), s.line))


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Detect dead code in pullDB")
    parser.add_argument(
        "--confidence",
        type=int,
        default=90,
        help="Minimum confidence level (0-100) to report",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).parent.parent,
        help="Root directory to analyze",
    )

    args = parser.parse_args()

    # Find pulldb directory
    root = args.root
    pulldb_dir = root / "pulldb"
    if not pulldb_dir.exists():
        print(f"Error: pulldb directory not found at {pulldb_dir}", file=sys.stderr)
        sys.exit(1)

    detector = DeadCodeDetector(root)
    report = detector.analyze(min_confidence=args.confidence)

    if args.output == "json":
        output = {
            "candidates": [
                {
                    "name": c.name,
                    "file": str(c.file),
                    "line": c.line,
                    "kind": c.kind,
                    "confidence": c.confidence_dead(),
                    "is_private": c.is_private,
                    "is_test": c.is_test,
                    "refs": {
                        "static_importers": list(c.static_importers),
                        "static_callers": list(c.static_callers),
                        "dynamic": list(c.dynamic_refs),
                        "template": list(c.template_refs),
                        "js": list(c.js_refs),
                        "string": list(c.string_refs),
                    },
                }
                for c in report.candidates
            ],
            "summary": report.analysis_summary,
        }
        print(json.dumps(output, indent=2))
    else:
        print("=" * 80)
        print("DEAD CODE DETECTION REPORT")
        print("=" * 80)
        print(f"\nTotal symbols analyzed: {report.total_symbols}")
        print(f"Entry points identified: {len(report.entry_points)}")
        print(f"Dead code candidates: {len(report.candidates)}")
        print()

        if report.candidates:
            print("-" * 80)
            print("CANDIDATES (sorted by confidence)")
            print("-" * 80)
            for c in report.candidates:
                print(
                    f"\n[{c.confidence_dead()}%] {c.kind.upper()}: {c.name}"
                )
                print(f"    File: {c.file}:{c.line}")
                print(f"    Module: {c.module_path}")
                flags = []
                if c.is_private:
                    flags.append("private")
                if c.is_test:
                    flags.append("test")
                if c.is_decorated:
                    flags.append("decorated")
                if flags:
                    print(f"    Flags: {', '.join(flags)}")

        print("\n" + "=" * 80)
        print("VERIFICATION STEPS:")
        print("=" * 80)
        print("""
For each candidate above:
1. grep -r "symbol_name" pulldb/ tests/ --include="*.py"
2. grep -r "symbol_name" pulldb/web/templates/ --include="*.html"
3. grep -r "symbol_name" pulldb/web/static/ --include="*.js"
4. Check if in __init__.py __all__ exports
5. Remove and run: pytest tests/ -x
""")


if __name__ == "__main__":
    main()
