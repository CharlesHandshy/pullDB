#!/usr/bin/env python3
"""Validate documentation-index.json schema and integrity.

This tool validates the engineering-dna documentation index to ensure:
- JSON schema compliance
- All referenced files exist
- No orphaned dependencies
- Token estimates are current (optional check)
- No undocumented .md files in key directories

Usage:
    python3 scripts/validate_documentation_index.py
    python3 scripts/validate_documentation_index.py --fix-token-estimates
    python3 scripts/validate_documentation_index.py --json

Exit codes:
    0: Valid
    1: Validation failed
    2: Error (missing index file, parse errors)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ValidationResult:
    """Results from documentation index validation."""

    schema_valid: bool = True
    schema_errors: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    orphaned_dependencies: list[tuple[str, str]] = field(default_factory=list)
    stale_token_estimates: list[tuple[str, int, int]] = field(default_factory=list)
    undocumented_files: list[Path] = field(default_factory=list)
    dependency_cycles: list[list[str]] = field(default_factory=list)
    total_documents: int = 0

    def is_valid(self) -> bool:
        """Check if validation passed."""
        return (
            self.schema_valid
            and len(self.missing_files) == 0
            and len(self.orphaned_dependencies) == 0
            and len(self.dependency_cycles) == 0
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "status": "valid" if self.is_valid() else "invalid",
            "total_documents": self.total_documents,
            "schema_valid": self.schema_valid,
            "schema_errors": self.schema_errors,
            "missing_files": self.missing_files,
            "orphaned_dependencies": [
                {"doc_id": doc_id, "missing_dep": dep}
                for doc_id, dep in self.orphaned_dependencies
            ],
            "stale_token_estimates": [
                {
                    "file": file_path,
                    "indexed_tokens": indexed,
                    "actual_tokens": actual,
                    "diff_percent": int(((actual - indexed) / indexed) * 100),
                }
                for file_path, indexed, actual in self.stale_token_estimates
            ],
            "undocumented_files": [str(f) for f in self.undocumented_files],
            "dependency_cycles": self.dependency_cycles,
        }


class DocumentationIndexValidator:
    """Validates documentation-index.json integrity."""

    def __init__(self, index_path: Path, project_root: Path):
        """Initialize validator.

        Args:
            index_path: Path to documentation-index.json.
            project_root: Root directory of project (for resolving paths).
        """
        self.index_path = index_path
        self.project_root = project_root
        self.index_data: dict[str, Any] = {}
        self.documents: dict[str, dict[str, Any]] = {}

    def load_index(self) -> None:
        """Load and parse documentation index file.

        Raises:
            RuntimeError: If file not found or invalid JSON.
        """
        try:
            self.index_data = json.loads(self.index_path.read_text())
            self.documents = {
                doc["id"]: doc for doc in self.index_data.get("documents", [])
            }
        except FileNotFoundError as e:
            raise RuntimeError(f"Index file not found: {self.index_path}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in index: {e}") from e

    def validate_schema(self) -> list[str]:
        """Validate required fields in index schema.

        Returns:
            List of schema error messages (empty if valid).
        """
        errors = []

        # Check top-level required fields
        required_top_level = ["schema_version", "documents", "corpus_stats"]
        for field in required_top_level:
            if field not in self.index_data:
                errors.append(f"Missing required top-level field: {field}")

        # Check each document has required fields
        required_doc_fields = ["id", "path", "category", "token_estimate"]
        for i, doc in enumerate(self.index_data.get("documents", [])):
            for field in required_doc_fields:
                if field not in doc:
                    doc_id = doc.get("id", f"<document {i}>")
                    errors.append(f"Document '{doc_id}' missing required field: {field}")

        return errors

    def check_file_existence(self) -> list[str]:
        """Check that all referenced documentation files exist.

        Returns:
            List of missing file paths.
        """
        missing = []
        engineering_dna = self.project_root / "engineering-dna"

        for doc in self.index_data.get("documents", []):
            doc_path = engineering_dna / doc["path"]
            if not doc_path.exists():
                missing.append(doc["path"])

        return missing

    def check_orphaned_dependencies(self) -> list[tuple[str, str]]:
        """Check for dependencies referencing non-existent document IDs.

        Returns:
            List of (doc_id, missing_dependency_id) tuples.
        """
        orphaned = []

        for doc in self.index_data.get("documents", []):
            doc_id = doc["id"]
            dependencies = doc.get("dependencies", {})

            # Check load_with dependencies
            for dep_id in dependencies.get("load_with", []):
                if dep_id not in self.documents:
                    orphaned.append((doc_id, dep_id))

            # Check load_after dependencies
            for dep_id in dependencies.get("load_after", []):
                if dep_id not in self.documents:
                    orphaned.append((doc_id, dep_id))

        return orphaned

    def estimate_tokens(self, file_path: Path) -> int:
        """Estimate token count for a file (rough approximation).

        Args:
            file_path: Path to markdown file.

        Returns:
            Estimated token count (words * 1.3).
        """
        try:
            content = file_path.read_text()
            words = len(content.split())
            return int(words * 1.3)  # Rough token estimate
        except OSError:
            return 0

    def check_stale_token_estimates(
        self, tolerance_percent: int = 20
    ) -> list[tuple[str, int, int]]:
        """Check if token estimates are outdated based on file modification.

        Args:
            tolerance_percent: Percent difference to trigger warning (default 20%).

        Returns:
            List of (file_path, indexed_tokens, actual_tokens) tuples.
        """
        stale = []
        engineering_dna = self.project_root / "engineering-dna"

        for doc in self.index_data.get("documents", []):
            doc_path = engineering_dna / doc["path"]
            if not doc_path.exists():
                continue

            indexed_tokens = doc.get("token_estimate", 0)
            actual_tokens = self.estimate_tokens(doc_path)

            if indexed_tokens > 0:
                diff_percent = abs(actual_tokens - indexed_tokens) / indexed_tokens * 100
                if diff_percent > tolerance_percent:
                    stale.append((doc["path"], indexed_tokens, actual_tokens))

        return stale

    def find_undocumented_files(self) -> list[Path]:
        """Find .md files in engineering-dna not included in index.

        Returns:
            List of undocumented file paths.
        """
        engineering_dna = self.project_root / "engineering-dna"
        documented_paths = {doc["path"] for doc in self.index_data.get("documents", [])}

        # Directories to scan
        scan_dirs = ["standards", "protocols", "patterns", "templates"]
        undocumented = []

        for scan_dir in scan_dirs:
            dir_path = engineering_dna / scan_dir
            if not dir_path.exists():
                continue

            for md_file in dir_path.rglob("*.md"):
                relative = md_file.relative_to(engineering_dna)
                if str(relative) not in documented_paths:
                    undocumented.append(relative)

        return undocumented

    def detect_dependency_cycles(self) -> list[list[str]]:
        """Detect circular dependencies in load_after relationships.

        Returns:
            List of dependency cycles (each cycle is a list of doc IDs).
        """
        # Build adjacency list
        graph: dict[str, list[str]] = {doc_id: [] for doc_id in self.documents}
        for doc_id, doc in self.documents.items():
            dependencies = doc.get("dependencies", {})
            for dep_id in dependencies.get("load_after", []):
                if dep_id in graph:
                    graph[doc_id].append(dep_id)

        # Detect cycles using DFS
        cycles = []
        visited = set()
        rec_stack = set()

        def dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path.copy())
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])

            rec_stack.remove(node)

        for doc_id in graph:
            if doc_id not in visited:
                dfs(doc_id, [])

        return cycles

    def validate(self) -> ValidationResult:
        """Run all validation checks.

        Returns:
            Validation results with all errors and warnings.
        """
        result = ValidationResult()
        result.total_documents = len(self.index_data.get("documents", []))

        # Schema validation
        schema_errors = self.validate_schema()
        if schema_errors:
            result.schema_valid = False
            result.schema_errors = schema_errors

        # File existence
        result.missing_files = self.check_file_existence()

        # Orphaned dependencies
        result.orphaned_dependencies = self.check_orphaned_dependencies()

        # Stale token estimates
        result.stale_token_estimates = self.check_stale_token_estimates()

        # Undocumented files
        result.undocumented_files = self.find_undocumented_files()

        # Dependency cycles
        result.dependency_cycles = self.detect_dependency_cycles()

        return result


def format_report(result: ValidationResult) -> str:
    """Format validation result as human-readable report.

    Args:
        result: Validation results to format.

    Returns:
        Formatted report string.
    """
    lines = ["Documentation Index Validation Report", "=" * 50]

    # Schema validation
    if result.schema_valid:
        lines.append("✅ Schema valid")
    else:
        lines.append("❌ Schema validation failed:")
        for error in result.schema_errors:
            lines.append(f"  - {error}")

    # File existence
    if not result.missing_files:
        lines.append(f"✅ All {result.total_documents} referenced files exist")
    else:
        lines.append(f"❌ Found {len(result.missing_files)} missing files:")
        for path in result.missing_files:
            lines.append(f"  - {path}")

    # Orphaned dependencies
    if not result.orphaned_dependencies:
        lines.append("✅ No orphaned dependencies")
    else:
        lines.append(f"❌ Found {len(result.orphaned_dependencies)} orphaned dependencies:")
        for doc_id, dep_id in result.orphaned_dependencies:
            lines.append(f"  - {doc_id} references '{dep_id}' (doesn't exist)")

    # Stale token estimates
    if not result.stale_token_estimates:
        lines.append("✅ Token estimates current")
    else:
        lines.append(f"⚠️  {len(result.stale_token_estimates)} stale token estimates:")
        for path, indexed, actual in result.stale_token_estimates:
            diff_percent = int(((actual - indexed) / indexed) * 100)
            sign = "+" if actual > indexed else ""
            lines.append(
                f"  - {path}: indexed {indexed} tokens, actual {actual} tokens ({sign}{diff_percent}%)"
            )

    # Undocumented files
    if not result.undocumented_files:
        lines.append("✅ No undocumented .md files")
    else:
        lines.append(f"⚠️  {len(result.undocumented_files)} .md files not in index:")
        for path in result.undocumented_files:
            lines.append(f"  - engineering-dna/{path}")

    # Dependency cycles
    if not result.dependency_cycles:
        lines.append("✅ No dependency cycles")
    else:
        lines.append(f"❌ Found {len(result.dependency_cycles)} dependency cycles:")
        for cycle in result.dependency_cycles:
            lines.append(f"  - {' → '.join(cycle)}")

    return "\n".join(lines)


def main() -> int:
    """CLI entrypoint for documentation index validation.

    Returns:
        Exit code (0 = valid, 1 = invalid, 2 = error).
    """
    parser = argparse.ArgumentParser(
        description="Validate documentation-index.json integrity"
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("engineering-dna/metadata/documentation-index.json"),
        help="Path to documentation index file",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root directory",
    )
    parser.add_argument(
        "--fix-token-estimates",
        action="store_true",
        help="Update stale token estimates in index",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    index_path = args.index
    if not index_path.is_absolute():
        index_path = args.project_root / index_path

    if not index_path.exists():
        print(f"Error: Index file not found: {index_path}", file=sys.stderr)
        return 2

    # Create validator and load index
    validator = DocumentationIndexValidator(index_path, args.project_root)
    try:
        validator.load_index()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    # Run validation
    result = validator.validate()

    # Handle --fix-token-estimates
    if args.fix_token_estimates and result.stale_token_estimates:
        engineering_dna = args.project_root / "engineering-dna"
        for path, indexed, actual in result.stale_token_estimates:
            for doc in validator.index_data["documents"]:
                if doc["path"] == path:
                    doc["token_estimate"] = actual
                    break

        # Write updated index
        index_path.write_text(json.dumps(validator.index_data, indent=2) + "\n")
        print(f"Updated {len(result.stale_token_estimates)} token estimates")
        # Re-validate after fix
        result.stale_token_estimates = []

    # Output results
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_report(result))

    return 0 if result.is_valid() else 1


if __name__ == "__main__":
    sys.exit(main())
