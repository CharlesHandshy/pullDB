"""Drift detection engine.

Compares file inventory against documented state to detect
various types of documentation drift. Provides rich context
for AI agent reasoning.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pulldb.audit.inventory import FileCategory, FileInventory, FileInventoryItem


class DriftType(Enum):
    """Types of documentation drift."""

    # File-level drift
    UNDOCUMENTED_FILE = "undocumented_file"  # New file not in docs
    MISSING_FILE = "missing_file"  # Documented file doesn't exist
    RENAMED_FILE = "renamed_file"  # File appears to be renamed

    # Symbol-level drift
    UNDOCUMENTED_CLASS = "undocumented_class"
    UNDOCUMENTED_FUNCTION = "undocumented_function"
    MISSING_EXPORT = "missing_export"  # Documented export not in __all__
    EXTRA_EXPORT = "extra_export"  # Export in __all__ but not documented
    RENAMED_SYMBOL = "renamed_symbol"

    # Value drift
    COUNT_MISMATCH = "count_mismatch"  # File/endpoint counts wrong
    VALUE_MISMATCH = "value_mismatch"  # Timing, width, etc. wrong
    CONFIG_DRIFT = "config_drift"  # Configuration values changed

    # Structural drift
    MOVED_FILE = "moved_file"  # File in different location
    PACKAGE_RESTRUCTURE = "package_restructure"  # Package layout changed


@dataclass
class DriftAlert:
    """Single drift alert with full context for AI reasoning.

    This structure is designed to give an AI agent all the context
    needed to understand and fix the drift.
    """

    drift_type: DriftType
    severity: str  # critical, high, medium, low, info

    # Location
    file_path: Path | None
    doc_location: str  # Where in KNOWLEDGE-POOL this is referenced

    # The drift
    documented_state: Any
    actual_state: Any

    # Context for AI reasoning
    description: str
    reasoning_context: str  # Detailed context for AI
    suggested_actions: list[str]  # What an AI agent should do

    # Metadata
    detected_at: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0  # How confident we are this is real drift

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "drift_type": self.drift_type.value,
            "severity": self.severity,
            "file_path": str(self.file_path) if self.file_path else None,
            "doc_location": self.doc_location,
            "documented_state": self.documented_state,
            "actual_state": self.actual_state,
            "description": self.description,
            "reasoning_context": self.reasoning_context,
            "suggested_actions": self.suggested_actions,
            "detected_at": self.detected_at.isoformat(),
            "confidence": self.confidence,
        }

    def to_agent_prompt(self) -> str:
        """Format as a prompt section for AI agent reasoning."""
        return f"""
## Drift Alert: {self.drift_type.value}

**Severity**: {self.severity}
**File**: {self.file_path or 'N/A'}
**Documentation Location**: {self.doc_location}

### What Changed
- **Documented**: {self.documented_state}
- **Actual**: {self.actual_state}

### Context
{self.reasoning_context}

### Suggested Actions
{chr(10).join(f'- {action}' for action in self.suggested_actions)}
"""


class DriftDetector:
    """Detects documentation drift by comparing inventory to docs.

    Designed to provide rich context for AI agent reasoning.
    """

    def __init__(self, base_path: Path):
        """Initialize detector with project root."""
        self.base_path = base_path
        self.inventory = FileInventory(base_path)
        self.alerts: list[DriftAlert] = []
        self._load_knowledge_pool()

    def _load_knowledge_pool(self) -> None:
        """Load KNOWLEDGE-POOL content."""
        md_path = self.base_path / "docs" / "KNOWLEDGE-POOL.md"
        json_path = self.base_path / "docs" / "KNOWLEDGE-POOL.json"

        self.kp_md = md_path.read_text() if md_path.exists() else ""
        self.kp_json = {}
        if json_path.exists():
            try:
                self.kp_json = json.loads(json_path.read_text())
            except json.JSONDecodeError:
                pass

    def detect_all(self) -> list[DriftAlert]:
        """Run all drift detection checks."""
        self.alerts.clear()
        self.inventory.scan()

        # File-level checks
        self._detect_undocumented_files()
        self._detect_missing_files()

        # Symbol-level checks
        self._detect_export_drift()
        self._detect_class_drift()
        self._detect_function_drift()

        # Value checks
        self._detect_count_drift()
        self._detect_css_js_drift()

        # Package structure checks
        self._detect_package_drift()

        return self.alerts

    def _detect_undocumented_files(self) -> None:
        """Detect files that aren't mentioned in documentation."""
        undocumented = self.inventory.get_undocumented_files()

        # Group by package for better context
        by_package: dict[str, list[FileInventoryItem]] = {}
        for item in undocumented:
            if item.category == FileCategory.TEST:
                continue  # Skip test files
            package = str(item.path.parent)
            by_package.setdefault(package, []).append(item)

        for package, items in by_package.items():
            # Skip if too many (likely intentionally undocumented)
            if len(items) > 10:
                continue

            for item in items:
                # Determine severity based on content
                severity = "low"
                if item.symbols.get("classes") or item.symbols.get("exports"):
                    severity = "medium"
                if "api" in str(item.path) or "cli" in str(item.path):
                    severity = "high"

                self.alerts.append(DriftAlert(
                    drift_type=DriftType.UNDOCUMENTED_FILE,
                    severity=severity,
                    file_path=item.path,
                    doc_location="KNOWLEDGE-POOL.md (missing)",
                    documented_state="Not mentioned",
                    actual_state={
                        "category": item.category.value,
                        "classes": item.symbols.get("classes", []),
                        "functions": item.symbols.get("functions", [])[:5],
                        "lines": item.metrics.get("lines", 0),
                    },
                    description=f"File {item.path} is not documented in KNOWLEDGE-POOL",
                    reasoning_context=self._build_file_context(item),
                    suggested_actions=[
                        f"Add {item.path} to appropriate section in KNOWLEDGE-POOL.md",
                        f"Document key classes: {', '.join(item.symbols.get('classes', [])[:3])}",
                        "Consider if this file is significant enough to document",
                    ],
                    confidence=0.8 if severity == "low" else 0.95,
                ))

    def _detect_missing_files(self) -> None:
        """Detect files mentioned in docs that don't exist."""
        # Extract file paths from KNOWLEDGE-POOL
        documented_paths = set()

        # From markdown - look for path patterns (only project-relative paths)
        path_patterns = [
            r"`(pulldb/[\w/]+\.py)`",
            r"`(schema/[\w/]+\.sql)`",
            r"`(tests/[\w/]+\.py)`",
            r'"(pulldb/[\w/]+\.py)"',
            r"'(pulldb/[\w/]+\.py)'",
        ]
        for pattern in path_patterns:
            documented_paths.update(re.findall(pattern, self.kp_md))

        # From JSON - look for path values (only project-relative paths with valid extensions)
        def extract_paths(obj: Any, paths: set) -> None:
            if isinstance(obj, str):
                # Only extract if it looks like a project-relative path
                if (obj.startswith(("pulldb/", "schema/", "tests/", "scripts/"))
                    and "/" in obj
                    and not obj.startswith("http")
                    and not ":" in obj):  # Skip ARNs, URLs, etc.
                    paths.add(obj)
            elif isinstance(obj, dict):
                for v in obj.values():
                    extract_paths(v, paths)
            elif isinstance(obj, list):
                for item in obj:
                    extract_paths(item, paths)

        extract_paths(self.kp_json, documented_paths)

        # Check each documented path
        actual_paths = {str(p) for p in self.inventory.items.keys()}

        # Skip dirs that aren't scanned (but still valid to document)
        from pulldb.audit.inventory import FileInventory
        skip_prefixes = tuple(f"{d}/" for d in FileInventory.SKIP_DIRS)

        for doc_path in documented_paths:
            # Normalize path
            normalized = doc_path.strip("`'\"")

            # Skip directory references (end with /)
            if normalized.endswith("/"):
                continue

            # Skip paths in directories we don't scan (tests/, docs/, etc.)
            if normalized.startswith(skip_prefixes):
                # Verify the file actually exists before skipping
                if (self.base_path / normalized).exists():
                    continue

            # Recognized extensions tracked by inventory or valid as static assets
            _known_extensions = (".py", ".sql", ".html", ".css", ".js", ".json", ".yaml", ".yml")
            if not any(normalized.endswith(ext) for ext in _known_extensions):
                normalized += ".py"  # Assume Python if no recognized extension

            if normalized not in actual_paths:
                # For static assets not tracked by inventory (JSON, YAML, etc.),
                # verify existence on disk before flagging
                if (self.base_path / normalized).exists():
                    continue

                # Check for similar paths (might be renamed)
                similar = self._find_similar_path(normalized, actual_paths)

                self.alerts.append(DriftAlert(
                    drift_type=DriftType.MISSING_FILE if not similar else DriftType.RENAMED_FILE,
                    severity="high",
                    file_path=Path(normalized),
                    doc_location=f"KNOWLEDGE-POOL references: {doc_path}",
                    documented_state=doc_path,
                    actual_state=similar or "File not found",
                    description=f"Documented file '{normalized}' does not exist",
                    reasoning_context=f"""
The file '{normalized}' is referenced in KNOWLEDGE-POOL but doesn't exist in the codebase.
This could mean:
1. The file was renamed (similar: {similar or 'none found'})
2. The file was deleted
3. The documentation has a typo
4. The path format changed
""",
                    suggested_actions=[
                        f"If renamed, update documentation to: {similar}" if similar else "Remove reference from documentation",
                        "Search codebase for similar functionality",
                        "Check git history for what happened to this file",
                    ],
                ))

    def _detect_export_drift(self) -> None:
        """Detect __all__ export mismatches."""
        # Find all __init__.py files with exports
        init_files = [
            item for item in self.inventory.items.values()
            if item.category == FileCategory.PYTHON_INIT
            and item.symbols.get("exports")
        ]

        for item in init_files:
            actual_exports = set(item.symbols["exports"])

            # Find documented exports for this package
            package_name = str(item.path.parent).replace("/", ".")
            doc_exports = self._get_documented_exports(package_name)

            if doc_exports is None:
                continue  # No documented exports for this package

            doc_set = set(doc_exports)

            missing = doc_set - actual_exports
            extra = actual_exports - doc_set

            if missing:
                self.alerts.append(DriftAlert(
                    drift_type=DriftType.MISSING_EXPORT,
                    severity="high",
                    file_path=item.path,
                    doc_location=f"KNOWLEDGE-POOL exports for {package_name}",
                    documented_state=list(missing),
                    actual_state=list(actual_exports),
                    description=f"Documented exports not found in {item.path}",
                    reasoning_context=f"""
The following exports are documented but not in __all__:
{', '.join(missing)}

This could mean:
1. Symbols were renamed (check for similar names)
2. Symbols were removed (check if still needed)
3. Documentation is outdated

Actual exports: {', '.join(sorted(actual_exports)[:10])}...
""",
                    suggested_actions=[
                        "Remove missing exports from KNOWLEDGE-POOL.json",
                        "Or add missing symbols back to __all__ if they should exist",
                        f"Check git history for {item.path}",
                    ],
                ))

            if extra:
                self.alerts.append(DriftAlert(
                    drift_type=DriftType.EXTRA_EXPORT,
                    severity="medium",
                    file_path=item.path,
                    doc_location=f"KNOWLEDGE-POOL exports for {package_name}",
                    documented_state=list(doc_exports),
                    actual_state=list(extra),
                    description=f"Exports in {item.path} not documented",
                    reasoning_context=f"""
The following exports exist in __all__ but aren't documented:
{', '.join(extra)}

These should be added to KNOWLEDGE-POOL.json under the appropriate section.
""",
                    suggested_actions=[
                        f"Add {', '.join(list(extra)[:5])} to KNOWLEDGE-POOL.json exports",
                        "Verify these are public API exports that should be documented",
                    ],
                ))

    def _detect_class_drift(self) -> None:
        """Detect class name changes."""
        # Extract documented class names
        documented_classes: dict[str, str] = {}  # class -> where documented
        
        # Pattern for class references in markdown
        class_patterns = [
            r"`([A-Z][a-zA-Z0-9]+(?:Repository|Manager|Client|Service|Handler))`",
            r"`(Mock[A-Z][a-zA-Z0-9]+)`",
            r"`(Simulated[A-Z][a-zA-Z0-9]+)`",
        ]
        for pattern in class_patterns:
            for match in re.finditer(pattern, self.kp_md):
                class_name = match.group(1)
                # Get surrounding context
                start = max(0, match.start() - 50)
                end = min(len(self.kp_md), match.end() + 50)
                context = self.kp_md[start:end].replace("\n", " ")
                documented_classes[class_name] = context

        # Get all actual classes
        actual_classes: set[str] = set()
        for item in self.inventory.items.values():
            if item.category in (FileCategory.PYTHON_MODULE, FileCategory.PYTHON_INIT):
                actual_classes.update(item.symbols.get("classes", []))

        # Find missing classes
        for class_name, context in documented_classes.items():
            if class_name not in actual_classes:
                similar = self._find_similar_symbol(class_name, actual_classes)
                
                self.alerts.append(DriftAlert(
                    drift_type=DriftType.RENAMED_SYMBOL if similar else DriftType.UNDOCUMENTED_CLASS,
                    severity="high",
                    file_path=None,
                    doc_location=f"Context: ...{context}...",
                    documented_state=class_name,
                    actual_state=similar or "Not found",
                    description=f"Documented class '{class_name}' not found in codebase",
                    reasoning_context=f"""
Class '{class_name}' is documented but doesn't exist.
{f"Similar class found: '{similar}' - likely a rename" if similar else "No similar class found - may have been removed"}

Common rename patterns:
- Mock* -> Simulated* (or vice versa)
- *Repository -> *Store
- *Manager -> *Service
""",
                    suggested_actions=[
                        f"Update documentation to use '{similar}'" if similar else "Remove reference from documentation",
                        "Search for the functionality this class provided",
                    ],
                ))

    def _detect_function_drift(self) -> None:
        """Detect function name changes in key modules."""
        # Focus on commonly documented functions
        key_function_patterns = [
            r"`(get_\w+)`",
            r"`(create_\w+)`",
            r"`(delete_\w+)`",
            r"`(validate_\w+)`",
        ]

        documented_functions: set[str] = set()
        for pattern in key_function_patterns:
            documented_functions.update(re.findall(pattern, self.kp_md))

        # Get actual functions from key modules
        actual_functions: set[str] = set()
        key_modules = ["api", "domain", "infra", "worker", "web"]
        for item in self.inventory.items.values():
            if any(mod in str(item.path) for mod in key_modules):
                actual_functions.update(item.symbols.get("functions", []))

        # Find missing functions
        for func_name in documented_functions:
            if func_name not in actual_functions:
                similar = self._find_similar_symbol(func_name, actual_functions)
                if similar:
                    self.alerts.append(DriftAlert(
                        drift_type=DriftType.RENAMED_SYMBOL,
                        severity="high",
                        file_path=None,
                        doc_location=f"KNOWLEDGE-POOL reference to {func_name}",
                        documented_state=func_name,
                        actual_state=similar,
                        description=f"Function '{func_name}' renamed to '{similar}'",
                        reasoning_context=f"""
Function '{func_name}' in documentation appears to have been renamed to '{similar}'.
This is a common pattern when:
- API naming conventions change
- Function responsibilities are clarified
- Code review feedback is incorporated
""",
                        suggested_actions=[
                            f"Replace '{func_name}' with '{similar}' in KNOWLEDGE-POOL.md",
                            "Verify the function signature hasn't changed",
                        ],
                    ))

    def _detect_count_drift(self) -> None:
        """Detect file/item count mismatches."""
        # Check documented counts against reality
        count_checks = [
            ("schema.table_count", "schema/00_tables/*.sql", "schema tables"),
            ("package.schema_files", "schema/**/*.sql", "total schema files"),
            ("package.after_sql_templates", "pulldb/template_after_sql/**/*.sql", "after-SQL templates"),
            ("web.help_page_count", "pulldb/web/help/templates/**/*.html", "help pages"),
        ]

        for json_path, glob_pattern, description in count_checks:
            doc_count = self._get_json_value(json_path)
            if doc_count is None:
                continue

            actual_count = len(list(self.base_path.glob(glob_pattern)))

            if actual_count != doc_count:
                self.alerts.append(DriftAlert(
                    drift_type=DriftType.COUNT_MISMATCH,
                    severity="medium",
                    file_path=None,
                    doc_location=f"KNOWLEDGE-POOL.json: {json_path}",
                    documented_state=doc_count,
                    actual_state=actual_count,
                    description=f"Count mismatch for {description}",
                    reasoning_context=f"""
Documented count: {doc_count}
Actual count: {actual_count}
Pattern: {glob_pattern}

This drift of {abs(actual_count - doc_count)} indicates files were {'added' if actual_count > doc_count else 'removed'}.
""",
                    suggested_actions=[
                        f"Update {json_path} to {actual_count} in KNOWLEDGE-POOL.json",
                        f"Also update the corresponding markdown section",
                    ],
                ))

    def _detect_css_js_drift(self) -> None:
        """Detect CSS and JS value drift."""
        # Check sidebar timing
        js_file = self.base_path / "pulldb" / "web" / "static" / "js" / "main.js"
        if js_file.exists():
            content = js_file.read_text()
            match = re.search(r"setTimeout\s*\(\s*closeSidebar\s*,\s*(\d+)\s*\)", content)
            if match:
                actual_delay = int(match.group(1))
                doc_delay = self._get_json_value("web_ui.sidebar_pattern.close_delay_ms")
                if doc_delay and actual_delay != doc_delay:
                    self.alerts.append(DriftAlert(
                        drift_type=DriftType.VALUE_MISMATCH,
                        severity="medium",
                        file_path=js_file.relative_to(self.base_path),
                        doc_location="web_ui.sidebar_pattern.close_delay_ms",
                        documented_state=f"{doc_delay}ms",
                        actual_state=f"{actual_delay}ms",
                        description="Sidebar close delay changed",
                        reasoning_context=f"""
The sidebar close delay in main.js is {actual_delay}ms but documentation says {doc_delay}ms.
This affects user experience - the sidebar will close {'faster' if actual_delay < doc_delay else 'slower'} than documented.
""",
                        suggested_actions=[
                            f"Update close_delay_ms to {actual_delay} in KNOWLEDGE-POOL.json",
                            "Update the 'JavaScript Timing' section in KNOWLEDGE-POOL.md",
                        ],
                    ))

        # Check CSS trigger width
        css_file = self.base_path / "pulldb" / "web" / "static" / "css" / "widgets" / "sidebar.css"
        if css_file.exists():
            content = css_file.read_text()
            match = re.search(r"\.sidebar-trigger\s*\{[^}]*width:\s*(\d+px)", content, re.DOTALL)
            if match:
                actual_width = match.group(1)
                doc_width = self._get_json_value("web_ui.sidebar_pattern.trigger_zone_width")
                if doc_width and actual_width != doc_width:
                    self.alerts.append(DriftAlert(
                        drift_type=DriftType.VALUE_MISMATCH,
                        severity="low",
                        file_path=css_file.relative_to(self.base_path),
                        doc_location="web_ui.sidebar_pattern.trigger_zone_width",
                        documented_state=doc_width,
                        actual_state=actual_width,
                        description="Sidebar trigger width changed",
                        reasoning_context=f"""
The sidebar trigger zone is {actual_width} but documentation says {doc_width}.
This affects how easy it is to reveal the sidebar on hover.
""",
                        suggested_actions=[
                            f"Update trigger_zone_width to '{actual_width}' in KNOWLEDGE-POOL.json",
                        ],
                    ))

    def _detect_package_drift(self) -> None:
        """Detect package structure changes."""
        # Check if documented package structure matches reality
        documented_packages = set()

        # Extract package paths from JSON
        def find_packages(obj: Any, prefix: str = "") -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str) and v.endswith(".py"):
                        package = str(Path(v).parent)
                        documented_packages.add(package)
                    else:
                        find_packages(v, f"{prefix}{k}.")

        find_packages(self.kp_json)

        # Get actual packages
        actual_packages = set()
        for item in self.inventory.items.values():
            if item.category in (FileCategory.PYTHON_MODULE, FileCategory.PYTHON_INIT):
                actual_packages.add(str(item.path.parent))

        # Find new packages not in docs
        new_packages = actual_packages - documented_packages - {"tests", "scripts"}
        for package in new_packages:
            if package.startswith("pulldb/") and "__pycache__" not in package:
                items_in_package = [
                    i for i in self.inventory.items.values()
                    if str(i.path.parent) == package
                ]
                if items_in_package:
                    self.alerts.append(DriftAlert(
                        drift_type=DriftType.PACKAGE_RESTRUCTURE,
                        severity="info",
                        file_path=Path(package),
                        doc_location="Package structure in KNOWLEDGE-POOL",
                        documented_state="Not documented",
                        actual_state={
                            "package": package,
                            "files": len(items_in_package),
                            "sample_files": [str(i.path.name) for i in items_in_package[:3]],
                        },
                        description=f"New package '{package}' not in documentation",
                        reasoning_context=f"""
Package '{package}' exists with {len(items_in_package)} file(s) but isn't documented.
Files: {', '.join(str(i.path.name) for i in items_in_package[:5])}

This might be:
1. A new feature package that should be documented
2. Internal implementation detail (OK to skip)
3. Temporary/experimental code
""",
                        suggested_actions=[
                            f"Add {package} to HCA layer documentation if public API",
                            "Or mark as internal if not meant for public consumption",
                        ],
                    ))

    def _build_file_context(self, item: FileInventoryItem) -> str:
        """Build detailed context for a file."""
        lines = [f"**File**: {item.path}"]
        lines.append(f"**Category**: {item.category.value}")
        lines.append(f"**Lines**: {item.metrics.get('lines', 'unknown')}")

        if item.symbols.get("classes"):
            lines.append(f"**Classes**: {', '.join(item.symbols['classes'][:5])}")
        if item.symbols.get("functions"):
            lines.append(f"**Functions**: {', '.join(item.symbols['functions'][:5])}")
        if item.symbols.get("exports"):
            lines.append(f"**Exports**: {', '.join(item.symbols['exports'][:5])}")

        return "\n".join(lines)

    def _get_documented_exports(self, package_name: str) -> list[str] | None:
        """Get documented exports for a package.
        
        Only returns exports for the main package __init__.py, not subpackages.
        e.g., "pulldb.simulation" matches, "pulldb.simulation.api" does not.
        """
        # Must be the exact main package, not a subpackage
        # pulldb.simulation -> simulation exports
        # pulldb.simulation.api -> no exports (it's a subpackage with its own scope)
        # pulldb.audit -> audit exports
        # pulldb.audit.something -> no exports
        
        if package_name == "pulldb.simulation":
            return self.kp_json.get("simulation", {}).get("exports")
        if package_name == "pulldb.audit":
            return self.kp_json.get("audit", {}).get("exports")
        return None

    def _get_json_value(self, path: str) -> Any:
        """Get value from KNOWLEDGE-POOL.json by dot notation."""
        parts = path.split(".")
        current = self.kp_json
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def _find_similar_path(self, target: str, candidates: set[str]) -> str | None:
        """Find similar path from candidates."""
        target_name = Path(target).name
        for candidate in candidates:
            if Path(candidate).name == target_name:
                return candidate
        return None

    def _find_similar_symbol(self, target: str, candidates: set[str]) -> str | None:
        """Find similar symbol name from candidates."""
        # Common rename patterns
        patterns = [
            (r"^Mock", "Simulated"),
            (r"^Simulated", "Mock"),
            (r"current_user", "authenticated_user"),
            (r"authenticated_user", "current_user"),
            (r"Repository$", "Store"),
            (r"Store$", "Repository"),
        ]

        for pattern, replacement in patterns:
            alt = re.sub(pattern, replacement, target)
            if alt in candidates:
                return alt

        # Check for meaningful partial matches (at least 5 chars overlap)
        # and candidate must be at least 70% as long as target
        target_lower = target.lower()
        min_match_len = max(5, len(target) // 2)  # At least 5 chars or half the target
        for candidate in candidates:
            candidate_lower = candidate.lower()
            # Skip very short candidates
            if len(candidate) < min_match_len:
                continue
            # Skip if length ratio is too different (avoid matching "b" with "database")
            if len(candidate) < len(target) * 0.5 or len(candidate) > len(target) * 2:
                continue
            if target_lower in candidate_lower or candidate_lower in target_lower:
                return candidate

        return None

    def get_summary(self) -> dict[str, Any]:
        """Get drift detection summary."""
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}

        for alert in self.alerts:
            by_type[alert.drift_type.value] = by_type.get(alert.drift_type.value, 0) + 1
            by_severity[alert.severity] = by_severity.get(alert.severity, 0) + 1

        return {
            "total_alerts": len(self.alerts),
            "by_type": by_type,
            "by_severity": by_severity,
            "inventory_summary": self.inventory.get_summary(),
        }

    def to_agent_context(self) -> str:
        """Format all alerts as context for AI agent reasoning."""
        if not self.alerts:
            return "No documentation drift detected. KNOWLEDGE-POOL is synchronized with codebase."

        sections = [
            "# Documentation Drift Report",
            "",
            f"**Total Alerts**: {len(self.alerts)}",
            f"**Generated**: {datetime.now().isoformat()}",
            "",
            "---",
        ]

        # Group by severity
        by_severity = {"critical": [], "high": [], "medium": [], "low": [], "info": []}
        for alert in self.alerts:
            by_severity[alert.severity].append(alert)

        for severity in ["critical", "high", "medium", "low", "info"]:
            alerts = by_severity[severity]
            if alerts:
                sections.append(f"\n# {severity.upper()} ({len(alerts)})\n")
                for alert in alerts:
                    sections.append(alert.to_agent_prompt())

        return "\n".join(sections)
