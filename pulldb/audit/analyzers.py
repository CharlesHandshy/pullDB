"""Code analyzers for documentation audit.

Each analyzer knows how to extract facts from a specific type of code
and compare them against documented values.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ExtractedFact:
    """A fact extracted from code.

    Attributes:
        key: Identifier for the fact (e.g., 'class_name', 'timing_ms').
        value: The actual value found in code.
        location: File path and line number.
        context: Surrounding code for verification.
    """

    key: str
    value: Any
    location: str
    context: str = ""


class BaseAnalyzer(ABC):
    """Base class for code analyzers."""

    @abstractmethod
    def can_analyze(self, file_path: Path) -> bool:
        """Check if this analyzer can handle the given file."""
        pass

    @abstractmethod
    def extract_facts(self, file_path: Path, patterns: list[str]) -> list[ExtractedFact]:
        """Extract facts from a file using the given patterns."""
        pass


class PythonAnalyzer(BaseAnalyzer):
    """Analyzer for Python source files."""

    def can_analyze(self, file_path: Path) -> bool:
        return file_path.suffix == ".py"

    def extract_facts(self, file_path: Path, patterns: list[str]) -> list[ExtractedFact]:
        """Extract facts from Python file.

        Supports:
        - __all__ exports
        - Class names (Mock*, Simulated*)
        - Function definitions
        - Constants
        - Dataclass fields
        """
        facts = []
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return facts

        lines = content.split("\n")

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
                # Find line number
                line_num = content[:match.start()].count("\n") + 1
                context_start = max(0, line_num - 2)
                context_end = min(len(lines), line_num + 2)
                context = "\n".join(lines[context_start:context_end])

                # Extract the captured group or full match
                value = match.group(1) if match.groups() else match.group(0)

                facts.append(ExtractedFact(
                    key=pattern[:30],  # Use pattern prefix as key
                    value=value.strip(),
                    location=f"{file_path}:{line_num}",
                    context=context,
                ))

        return facts

    def extract_exports(self, file_path: Path) -> list[str]:
        """Extract __all__ exports from a Python module."""
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return []

        match = re.search(r"__all__\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
        if not match:
            return []

        # Parse the list
        exports_str = match.group(1)
        exports = re.findall(r'["\'](\w+)["\']', exports_str)
        return exports

    def extract_class_names(self, file_path: Path, prefix: str = "") -> list[str]:
        """Extract class names from a Python file."""
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return []

        pattern = rf"class\s+({prefix}\w+)" if prefix else r"class\s+(\w+)"
        return re.findall(pattern, content)

    def extract_function_names(self, file_path: Path, prefix: str = "") -> list[str]:
        """Extract function names from a Python file."""
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return []

        pattern = rf"def\s+({prefix}\w+)" if prefix else r"def\s+(\w+)"
        return re.findall(pattern, content)


class CSSAnalyzer(BaseAnalyzer):
    """Analyzer for CSS files."""

    def can_analyze(self, file_path: Path) -> bool:
        return file_path.suffix == ".css"

    def extract_facts(self, file_path: Path, patterns: list[str]) -> list[ExtractedFact]:
        """Extract facts from CSS file."""
        facts = []
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return facts

        lines = content.split("\n")

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count("\n") + 1
                context_start = max(0, line_num - 2)
                context_end = min(len(lines), line_num + 2)
                context = "\n".join(lines[context_start:context_end])

                value = match.group(1) if match.groups() else match.group(0)

                facts.append(ExtractedFact(
                    key=pattern[:30],
                    value=value.strip(),
                    location=f"{file_path}:{line_num}",
                    context=context,
                ))

        return facts

    def extract_class_selectors(self, file_path: Path) -> list[str]:
        """Extract all CSS class selectors from a file."""
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return []

        # Match class selectors
        return re.findall(r"\.([a-zA-Z][\w-]*)", content)

    def extract_property_value(
        self, file_path: Path, selector: str, property_name: str
    ) -> str | None:
        """Extract a specific CSS property value for a selector."""
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return None

        # Find the selector block
        selector_escaped = re.escape(selector)
        pattern = rf"{selector_escaped}\s*\{{([^}}]+)\}}"
        match = re.search(pattern, content, re.DOTALL)
        if not match:
            return None

        # Find the property in the block
        block = match.group(1)
        prop_pattern = rf"{re.escape(property_name)}\s*:\s*([^;]+)"
        prop_match = re.search(prop_pattern, block)
        if prop_match:
            return prop_match.group(1).strip()
        return None


class JavaScriptAnalyzer(BaseAnalyzer):
    """Analyzer for JavaScript files."""

    def can_analyze(self, file_path: Path) -> bool:
        return file_path.suffix == ".js"

    def extract_facts(self, file_path: Path, patterns: list[str]) -> list[ExtractedFact]:
        """Extract facts from JavaScript file."""
        facts = []
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return facts

        lines = content.split("\n")

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count("\n") + 1
                context_start = max(0, line_num - 2)
                context_end = min(len(lines), line_num + 2)
                context = "\n".join(lines[context_start:context_end])

                value = match.group(1) if match.groups() else match.group(0)

                facts.append(ExtractedFact(
                    key=pattern[:30],
                    value=value.strip(),
                    location=f"{file_path}:{line_num}",
                    context=context,
                ))

        return facts

    def extract_timeout_value(self, file_path: Path, function_name: str) -> int | None:
        """Extract setTimeout value for a specific function call."""
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return None

        pattern = rf"setTimeout\s*\(\s*{re.escape(function_name)}\s*,\s*(\d+)\s*\)"
        match = re.search(pattern, content)
        if match:
            return int(match.group(1))
        return None


class SQLAnalyzer(BaseAnalyzer):
    """Analyzer for SQL files."""

    def can_analyze(self, file_path: Path) -> bool:
        return file_path.suffix == ".sql"

    def extract_facts(self, file_path: Path, patterns: list[str]) -> list[ExtractedFact]:
        """Extract facts from SQL file."""
        facts = []
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return facts

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE):
                value = match.group(1) if match.groups() else match.group(0)
                facts.append(ExtractedFact(
                    key=pattern[:30],
                    value=value.strip(),
                    location=str(file_path),
                    context="",
                ))

        return facts

    def extract_table_names(self, file_path: Path) -> list[str]:
        """Extract CREATE TABLE names from SQL file."""
        try:
            content = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return []

        return re.findall(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?",
            content,
            re.IGNORECASE,
        )


class FileCountAnalyzer(BaseAnalyzer):
    """Analyzer for counting files matching patterns."""

    def can_analyze(self, file_path: Path) -> bool:
        return True  # Works on any file

    def extract_facts(self, file_path: Path, patterns: list[str]) -> list[ExtractedFact]:
        """Not used - use count_files instead."""
        return []

    def count_files(self, pattern: str, base_path: Path) -> int:
        """Count files matching a glob pattern."""
        from glob import glob

        full_pattern = str(base_path / pattern)
        return len(glob(full_pattern, recursive=True))

    def list_files(self, pattern: str, base_path: Path) -> list[Path]:
        """List files matching a glob pattern."""
        from glob import glob

        full_pattern = str(base_path / pattern)
        return [Path(p) for p in glob(full_pattern, recursive=True)]


# Analyzer registry
ANALYZERS: list[BaseAnalyzer] = [
    PythonAnalyzer(),
    CSSAnalyzer(),
    JavaScriptAnalyzer(),
    SQLAnalyzer(),
    FileCountAnalyzer(),
]


def get_analyzer(file_path: Path) -> BaseAnalyzer | None:
    """Get appropriate analyzer for a file type."""
    for analyzer in ANALYZERS:
        if analyzer.can_analyze(file_path):
            return analyzer
    return None
