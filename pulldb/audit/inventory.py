"""File inventory for comprehensive drift detection.

Scans the entire codebase and builds an inventory of all files
that should be tracked for documentation drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class FileCategory(Enum):
    """Categories of files for documentation tracking."""

    PYTHON_MODULE = "python_module"  # .py files with classes/functions
    PYTHON_INIT = "python_init"  # __init__.py exports
    CSS_STYLESHEET = "css"
    JAVASCRIPT = "javascript"
    SQL_SCHEMA = "sql_schema"
    SQL_SEED = "sql_seed"
    HTML_TEMPLATE = "html_template"
    CONFIG = "config"  # pyproject.toml, etc.
    DOCUMENTATION = "documentation"
    TEST = "test"


@dataclass
class FileInventoryItem:
    """Single file in the inventory.

    Attributes:
        path: Relative path from project root.
        category: Type of file.
        symbols: Extracted symbols (classes, functions, exports, etc.).
        metrics: File metrics (line count, etc.).
        last_modified: Last modification time.
        documented: Whether this file is referenced in KNOWLEDGE-POOL.
        doc_references: Where this file is mentioned in docs.
    """

    path: Path
    category: FileCategory
    symbols: dict[str, list[str]] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    last_modified: float = 0.0
    documented: bool = False
    doc_references: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "path": str(self.path),
            "category": self.category.value,
            "symbols": self.symbols,
            "metrics": self.metrics,
            "documented": self.documented,
            "doc_references": self.doc_references,
        }


class FileInventory:
    """Comprehensive file inventory for the codebase.

    Scans all relevant files and extracts symbols, metrics,
    and documentation references.
    """

    # Directories to scan
    SCAN_DIRS = [
        "pulldb",
        "schema",
        "scripts",
    ]

    # Directories to skip
    SKIP_DIRS = {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "build",
        "dist",
        ".egg-info",
        "_archived",
        "tests",  # Tests are intentionally undocumented
        "engineering-dna",  # Submodule
        "packaging",
        "typings",
        "graph-tools",
        "screenshot_temp",
        "logs",
        "images",
        "design",
        "docs",
        "pulldb.egg-info",
    }

    # File patterns by category
    FILE_PATTERNS = {
        FileCategory.PYTHON_MODULE: "**/*.py",
        FileCategory.CSS_STYLESHEET: "**/*.css",
        FileCategory.JAVASCRIPT: "**/*.js",
        FileCategory.SQL_SCHEMA: "schema/**/*.sql",
        FileCategory.HTML_TEMPLATE: "**/*.html",
    }

    def __init__(self, base_path: Path):
        """Initialize inventory with project root."""
        self.base_path = base_path
        self.items: dict[Path, FileInventoryItem] = {}
        self._knowledge_pool_content: str = ""
        self._knowledge_pool_json: dict = {}

    def scan(self) -> None:
        """Scan codebase and build inventory."""
        self._load_knowledge_pool()
        self._scan_python_files()
        self._scan_css_files()
        self._scan_js_files()
        self._scan_sql_files()
        self._scan_html_templates()
        self._check_documentation_references()

    def _load_knowledge_pool(self) -> None:
        """Load KNOWLEDGE-POOL content for reference checking."""
        import json

        md_path = self.base_path / "docs" / "KNOWLEDGE-POOL.md"
        json_path = self.base_path / "docs" / "KNOWLEDGE-POOL.json"

        if md_path.exists():
            self._knowledge_pool_content = md_path.read_text()
        if json_path.exists():
            try:
                self._knowledge_pool_json = json.loads(json_path.read_text())
            except json.JSONDecodeError:
                pass

    def _scan_python_files(self) -> None:
        """Scan all Python files and extract symbols."""
        for scan_dir in self.SCAN_DIRS:
            dir_path = self.base_path / scan_dir
            if not dir_path.exists():
                continue

            for py_file in dir_path.rglob("*.py"):
                if self._should_skip(py_file):
                    continue

                rel_path = py_file.relative_to(self.base_path)
                category = (
                    FileCategory.PYTHON_INIT
                    if py_file.name == "__init__.py"
                    else FileCategory.TEST
                    if "test" in str(py_file)
                    else FileCategory.PYTHON_MODULE
                )

                symbols = self._extract_python_symbols(py_file)
                metrics = self._get_file_metrics(py_file)

                self.items[rel_path] = FileInventoryItem(
                    path=rel_path,
                    category=category,
                    symbols=symbols,
                    metrics=metrics,
                    last_modified=py_file.stat().st_mtime,
                )

    def _scan_css_files(self) -> None:
        """Scan CSS files and extract selectors."""
        for scan_dir in self.SCAN_DIRS:
            dir_path = self.base_path / scan_dir
            if not dir_path.exists():
                continue

            for css_file in dir_path.rglob("*.css"):
                if self._should_skip(css_file):
                    continue

                rel_path = css_file.relative_to(self.base_path)
                symbols = self._extract_css_symbols(css_file)
                metrics = self._get_file_metrics(css_file)

                self.items[rel_path] = FileInventoryItem(
                    path=rel_path,
                    category=FileCategory.CSS_STYLESHEET,
                    symbols=symbols,
                    metrics=metrics,
                    last_modified=css_file.stat().st_mtime,
                )

    def _scan_js_files(self) -> None:
        """Scan JavaScript files and extract functions."""
        for scan_dir in self.SCAN_DIRS:
            dir_path = self.base_path / scan_dir
            if not dir_path.exists():
                continue

            for js_file in dir_path.rglob("*.js"):
                if self._should_skip(js_file):
                    continue

                rel_path = js_file.relative_to(self.base_path)
                symbols = self._extract_js_symbols(js_file)
                metrics = self._get_file_metrics(js_file)

                self.items[rel_path] = FileInventoryItem(
                    path=rel_path,
                    category=FileCategory.JAVASCRIPT,
                    symbols=symbols,
                    metrics=metrics,
                    last_modified=js_file.stat().st_mtime,
                )

    def _scan_sql_files(self) -> None:
        """Scan SQL schema files."""
        schema_dir = self.base_path / "schema"
        if not schema_dir.exists():
            return

        for sql_file in schema_dir.rglob("*.sql"):
            rel_path = sql_file.relative_to(self.base_path)
            category = (
                FileCategory.SQL_SEED
                if "seed" in str(sql_file).lower()
                else FileCategory.SQL_SCHEMA
            )
            symbols = self._extract_sql_symbols(sql_file)
            metrics = self._get_file_metrics(sql_file)

            self.items[rel_path] = FileInventoryItem(
                path=rel_path,
                category=category,
                symbols=symbols,
                metrics=metrics,
                last_modified=sql_file.stat().st_mtime,
            )

    def _scan_html_templates(self) -> None:
        """Scan HTML template files."""
        for scan_dir in self.SCAN_DIRS:
            dir_path = self.base_path / scan_dir
            if not dir_path.exists():
                continue

            for html_file in dir_path.rglob("*.html"):
                if self._should_skip(html_file):
                    continue

                rel_path = html_file.relative_to(self.base_path)
                symbols = self._extract_html_symbols(html_file)
                metrics = self._get_file_metrics(html_file)

                self.items[rel_path] = FileInventoryItem(
                    path=rel_path,
                    category=FileCategory.HTML_TEMPLATE,
                    symbols=symbols,
                    metrics=metrics,
                    last_modified=html_file.stat().st_mtime,
                )

    def _should_skip(self, path: Path) -> bool:
        """Check if path should be skipped."""
        for skip in self.SKIP_DIRS:
            if skip in path.parts:
                return True
        return False

    def _extract_python_symbols(self, path: Path) -> dict[str, list[str]]:
        """Extract classes, functions, and exports from Python file."""
        try:
            content = path.read_text()
        except (OSError, UnicodeDecodeError):
            return {}

        symbols: dict[str, list[str]] = {
            "classes": [],
            "functions": [],
            "exports": [],
            "imports": [],
        }

        # Classes
        symbols["classes"] = re.findall(r"^class\s+(\w+)", content, re.MULTILINE)

        # Functions (top-level and async, including nested)
        # Match both 'def func' and 'async def func'
        symbols["functions"] = re.findall(r"^(?:async\s+)?def\s+(\w+)", content, re.MULTILINE)

        # __all__ exports
        all_match = re.search(r"__all__\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
        if all_match:
            symbols["exports"] = re.findall(r'["\'](\w+)["\']', all_match.group(1))

        # Imports from pulldb
        symbols["imports"] = re.findall(
            r"from\s+(pulldb\.\w+(?:\.\w+)*)\s+import", content
        )

        return symbols

    def _extract_css_symbols(self, path: Path) -> dict[str, list[str]]:
        """Extract CSS selectors and custom properties."""
        try:
            content = path.read_text()
        except (OSError, UnicodeDecodeError):
            return {}

        symbols: dict[str, list[str]] = {
            "classes": [],
            "ids": [],
            "custom_properties": [],
        }

        # Class selectors
        symbols["classes"] = list(set(re.findall(r"\.([a-zA-Z][\w-]*)", content)))

        # ID selectors
        symbols["ids"] = list(set(re.findall(r"#([a-zA-Z][\w-]*)", content)))

        # CSS custom properties
        symbols["custom_properties"] = list(
            set(re.findall(r"--([\w-]+)", content))
        )

        return symbols

    def _extract_js_symbols(self, path: Path) -> dict[str, list[str]]:
        """Extract JavaScript functions and constants."""
        try:
            content = path.read_text()
        except (OSError, UnicodeDecodeError):
            return {}

        symbols: dict[str, list[str]] = {
            "functions": [],
            "constants": [],
            "event_listeners": [],
        }

        # Function declarations
        symbols["functions"] = re.findall(r"function\s+(\w+)", content)

        # Arrow function assignments
        symbols["functions"].extend(
            re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:\([^)]*\)|[\w,\s]+)\s*=>", content)
        )

        # Constants
        symbols["constants"] = re.findall(r"const\s+([A-Z_]+)\s*=", content)

        # Event listeners
        symbols["event_listeners"] = re.findall(
            r"addEventListener\s*\(\s*['\"](\w+)['\"]", content
        )

        return symbols

    def _extract_sql_symbols(self, path: Path) -> dict[str, list[str]]:
        """Extract SQL tables, views, and indexes."""
        try:
            content = path.read_text()
        except (OSError, UnicodeDecodeError):
            return {}

        symbols: dict[str, list[str]] = {
            "tables": [],
            "views": [],
            "indexes": [],
            "triggers": [],
        }

        # Tables
        symbols["tables"] = re.findall(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)",
            content,
            re.IGNORECASE,
        )

        # Views
        symbols["views"] = re.findall(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+[`\"]?(\w+)",
            content,
            re.IGNORECASE,
        )

        # Indexes
        symbols["indexes"] = re.findall(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+[`\"]?(\w+)",
            content,
            re.IGNORECASE,
        )

        return symbols

    def _extract_html_symbols(self, path: Path) -> dict[str, list[str]]:
        """Extract HTML IDs and data attributes."""
        try:
            content = path.read_text()
        except (OSError, UnicodeDecodeError):
            return {}

        symbols: dict[str, list[str]] = {
            "ids": [],
            "classes": [],
            "data_attributes": [],
        }

        # IDs
        symbols["ids"] = re.findall(r'id=["\']([^"\']+)["\']', content)

        # Classes
        class_matches = re.findall(r'class=["\']([^"\']+)["\']', content)
        symbols["classes"] = list(set(
            cls for match in class_matches for cls in match.split()
        ))

        # Data attributes
        symbols["data_attributes"] = list(set(
            re.findall(r"(data-[\w-]+)", content)
        ))

        return symbols

    def _get_file_metrics(self, path: Path) -> dict[str, Any]:
        """Get file metrics."""
        try:
            content = path.read_text()
            lines = content.split("\n")
            return {
                "lines": len(lines),
                "non_empty_lines": len([l for l in lines if l.strip()]),
                "size_bytes": path.stat().st_size,
            }
        except (OSError, UnicodeDecodeError):
            return {"lines": 0, "non_empty_lines": 0, "size_bytes": 0}

    def _check_documentation_references(self) -> None:
        """Check which files are referenced in KNOWLEDGE-POOL."""
        for rel_path, item in self.items.items():
            path_str = str(rel_path)
            path_variants = [
                path_str,
                path_str.replace("/", "."),  # pulldb.audit.agent
                rel_path.stem,  # agent (without .py)
                rel_path.name,  # agent.py
            ]

            # Check markdown content
            for variant in path_variants:
                if variant in self._knowledge_pool_content:
                    item.documented = True
                    # Find section where it's mentioned
                    for line in self._knowledge_pool_content.split("\n"):
                        if variant in line:
                            item.doc_references.append(line.strip()[:100])
                    break

            # Check JSON for path references
            json_str = str(self._knowledge_pool_json)
            for variant in path_variants:
                if variant in json_str:
                    item.documented = True
                    break

    def get_undocumented_files(self) -> list[FileInventoryItem]:
        """Get files that aren't referenced in documentation."""
        return [
            item
            for item in self.items.values()
            if not item.documented and item.category != FileCategory.TEST
        ]

    def get_by_category(self, category: FileCategory) -> list[FileInventoryItem]:
        """Get all files of a specific category."""
        return [item for item in self.items.values() if item.category == category]

    def get_summary(self) -> dict[str, Any]:
        """Get inventory summary."""
        by_category: dict[str, int] = {}
        for item in self.items.values():
            cat = item.category.value
            by_category[cat] = by_category.get(cat, 0) + 1

        documented = sum(1 for item in self.items.values() if item.documented)
        undocumented = len(self.items) - documented

        return {
            "total_files": len(self.items),
            "documented": documented,
            "undocumented": undocumented,
            "by_category": by_category,
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert entire inventory to dictionary."""
        return {
            "summary": self.get_summary(),
            "items": {str(k): v.to_dict() for k, v in self.items.items()},
        }
