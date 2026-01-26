"""KNOWLEDGE-POOL document parser and updater.

Handles reading, parsing, and updating both KNOWLEDGE-POOL.md
and KNOWLEDGE-POOL.json files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DocumentedFact:
    """A fact documented in KNOWLEDGE-POOL.

    Attributes:
        section: Section name in markdown.
        key: Key or identifier for the fact.
        value: The documented value.
        line_number: Line number in the file.
        json_path: Corresponding path in JSON file.
        raw_text: Original text containing the fact.
    """

    section: str
    key: str
    value: Any
    line_number: int
    json_path: str | None = None
    raw_text: str = ""


class KnowledgePoolParser:
    """Parser for KNOWLEDGE-POOL files."""

    def __init__(self, base_path: Path):
        """Initialize parser with project base path.

        Args:
            base_path: Root path of the pullDB project.
        """
        self.base_path = base_path
        self.md_path = base_path / "docs" / "KNOWLEDGE-POOL.md"
        self.json_path = base_path / "docs" / "KNOWLEDGE-POOL.json"

    def parse_markdown(self) -> dict[str, list[DocumentedFact]]:
        """Parse KNOWLEDGE-POOL.md into structured facts.

        Returns:
            Dictionary mapping section names to lists of facts.
        """
        facts: dict[str, list[DocumentedFact]] = {}

        try:
            content = self.md_path.read_text()
        except (OSError, UnicodeDecodeError):
            return facts

        lines = content.split("\n")
        current_section = "Header"

        for i, line in enumerate(lines):
            line_num = i + 1

            # Track section headers
            if line.startswith("## "):
                current_section = line[3:].strip()
                facts.setdefault(current_section, [])
                continue

            if current_section not in facts:
                facts[current_section] = []

            # Extract facts from various patterns
            self._extract_facts_from_line(
                line, line_num, current_section, facts[current_section]
            )

        return facts

    def _extract_facts_from_line(
        self,
        line: str,
        line_num: int,
        section: str,
        facts_list: list[DocumentedFact],
    ) -> None:
        """Extract documented facts from a single line."""
        # Pattern: `key`: value or **key**: value
        match = re.match(r"[-*]\s*[`*]*([^`:*]+)[`*]*\s*[:=]\s*(.+)", line)
        if match:
            facts_list.append(DocumentedFact(
                section=section,
                key=match.group(1).strip(),
                value=match.group(2).strip(),
                line_number=line_num,
                raw_text=line,
            ))
            return

        # Pattern: - Key: value (list items)
        match = re.match(r"-\s+(\w[\w\s]+):\s+(.+)", line)
        if match:
            facts_list.append(DocumentedFact(
                section=section,
                key=match.group(1).strip(),
                value=match.group(2).strip(),
                line_number=line_num,
                raw_text=line,
            ))
            return

        # Pattern: CSS property in code block
        match = re.match(r"\s*([\w-]+)\s*:\s*([^;]+);", line)
        if match and ":" in line and ";" in line:
            facts_list.append(DocumentedFact(
                section=section,
                key=f"css:{match.group(1).strip()}",
                value=match.group(2).strip(),
                line_number=line_num,
                raw_text=line,
            ))

    def parse_json(self) -> dict[str, Any]:
        """Parse KNOWLEDGE-POOL.json.

        Returns:
            Parsed JSON data.
        """
        try:
            return json.loads(self.json_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def get_json_value(self, json_path: str) -> Any:
        """Get a value from the JSON file using dot notation.

        Args:
            json_path: Path like "$.web_ui.sidebar_pattern.close_delay_ms"

        Returns:
            The value at that path, or None if not found.
        """
        data = self.parse_json()
        if not data:
            return None

        # Remove leading $. if present
        path = json_path.lstrip("$.")
        parts = path.split(".")

        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current

    def find_documented_value(
        self, section: str, key_pattern: str
    ) -> DocumentedFact | None:
        """Find a documented fact matching section and key pattern.

        Args:
            section: Section name (partial match).
            key_pattern: Regex pattern for key.

        Returns:
            Matching fact or None.
        """
        facts = self.parse_markdown()

        for section_name, section_facts in facts.items():
            if section.lower() not in section_name.lower():
                continue

            for fact in section_facts:
                if re.search(key_pattern, fact.key, re.IGNORECASE):
                    return fact

        return None


class KnowledgePoolUpdater:
    """Updater for KNOWLEDGE-POOL files."""

    def __init__(self, base_path: Path):
        """Initialize updater with project base path."""
        self.base_path = base_path
        self.md_path = base_path / "docs" / "KNOWLEDGE-POOL.md"
        self.json_path = base_path / "docs" / "KNOWLEDGE-POOL.json"
        self.changes: list[dict[str, Any]] = []

    def update_markdown_value(
        self,
        old_value: str,
        new_value: str,
        context_before: str = "",
        context_after: str = "",
    ) -> bool:
        """Update a value in KNOWLEDGE-POOL.md.

        Args:
            old_value: The current (incorrect) value to find.
            new_value: The new (correct) value to replace with.
            context_before: Context to help identify the right occurrence.
            context_after: Additional context after the value.

        Returns:
            True if update was successful.
        """
        try:
            content = self.md_path.read_text()
        except OSError:
            return False

        # Build pattern with context
        if context_before or context_after:
            pattern = re.escape(context_before) + re.escape(old_value) + re.escape(context_after)
            replacement = context_before + new_value + context_after
        else:
            pattern = re.escape(old_value)
            replacement = new_value

        new_content, count = re.subn(pattern, replacement, content, count=1)

        if count == 0:
            return False

        self.md_path.write_text(new_content)
        self.changes.append({
            "file": str(self.md_path),
            "old": old_value,
            "new": new_value,
        })
        return True

    def update_json_value(self, json_path: str, new_value: Any) -> bool:
        """Update a value in KNOWLEDGE-POOL.json.

        Args:
            json_path: Dot notation path like "web_ui.sidebar_pattern.close_delay_ms"
            new_value: New value to set.

        Returns:
            True if update was successful.
        """
        try:
            data = json.loads(self.json_path.read_text())
        except (OSError, json.JSONDecodeError):
            return False

        # Navigate to parent and update
        path = json_path.lstrip("$.")
        parts = path.split(".")

        current = data
        for part in parts[:-1]:
            if part not in current:
                return False
            current = current[part]

        if parts[-1] not in current:
            return False

        old_value = current[parts[-1]]
        current[parts[-1]] = new_value

        # Write back
        self.json_path.write_text(json.dumps(data, indent=2) + "\n")
        self.changes.append({
            "file": str(self.json_path),
            "path": json_path,
            "old": old_value,
            "new": new_value,
        })
        return True

    def get_changes(self) -> list[dict[str, Any]]:
        """Get list of changes made by this updater."""
        return self.changes.copy()

    def clear_changes(self) -> None:
        """Clear the changes log."""
        self.changes.clear()
