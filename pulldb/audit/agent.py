"""Documentation Audit Agent.

Main orchestrator for continuous documentation auditing.
Detects changes, identifies affected documentation, verifies
accuracy, and updates documentation to match code reality.

HCA Layer: features (business logic)

TWO MODES OF OPERATION:

1. **Targeted Audit** (audit_full, audit_staged, audit_changes)
   Uses hardcoded mappings for precise verification of known doc-code relationships.
   Fast, deterministic, good for CI/pre-commit hooks.

2. **Comprehensive Drift Detection** (detect_drift)
   Scans entire codebase and compares against KNOWLEDGE-POOL.
   Finds undocumented files, missing exports, renamed classes, etc.
   Provides rich context for AI agent reasoning.

Usage:
    # After git commit
    agent = DocumentationAuditAgent("/path/to/pullDB")
    report = agent.audit_changes()

    # Full audit (targeted)
    report = agent.audit_full()

    # Pre-commit hook
    report = agent.audit_staged()
    if report.has_critical:
        sys.exit(1)

    # Comprehensive drift detection (for AI reasoning)
    drift_report = agent.detect_drift()
    print(drift_report.to_agent_context())
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pulldb.audit.analyzers import (
    CSSAnalyzer,
    FileCountAnalyzer,
    JavaScriptAnalyzer,
    PythonAnalyzer,
)
from pulldb.audit.drift import DriftDetector
from pulldb.audit.inventory import FileInventory
from pulldb.audit.knowledge_pool import KnowledgePoolParser, KnowledgePoolUpdater
from pulldb.audit.mappings import (
    DocCodeMapping,
    get_all_mappings,
    get_mappings_for_file,
)
from pulldb.audit.report import AuditFinding, AuditReport, FindingSeverity

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DocumentationAuditAgent:
    """Continuous documentation audit agent.

    Monitors code changes and ensures KNOWLEDGE-POOL documentation
    stays synchronized with actual implementation.

    Attributes:
        base_path: Root path of the pullDB project.
        auto_fix: Whether to automatically fix discrepancies.
        parser: KNOWLEDGE-POOL parser instance.
        updater: KNOWLEDGE-POOL updater instance.
    """

    def __init__(
        self,
        base_path: str | Path | None = None,
        auto_fix: bool = False,
    ):
        """Initialize the audit agent.

        Args:
            base_path: Root path of pullDB project. Defaults to cwd.
            auto_fix: Whether to automatically fix found issues.
        """
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.auto_fix = auto_fix
        self.parser = KnowledgePoolParser(self.base_path)
        self.updater = KnowledgePoolUpdater(self.base_path)

        # Specialized analyzers
        self._python = PythonAnalyzer()
        self._css = CSSAnalyzer()
        self._js = JavaScriptAnalyzer()
        self._files = FileCountAnalyzer()

        # Comprehensive drift detection (lazy loaded)
        self._drift_detector: DriftDetector | None = None
        self._inventory: FileInventory | None = None

    @property
    def drift_detector(self) -> DriftDetector:
        """Lazy-load drift detector."""
        if self._drift_detector is None:
            self._drift_detector = DriftDetector(self.base_path)
        return self._drift_detector

    @property
    def inventory(self) -> FileInventory:
        """Lazy-load file inventory."""
        if self._inventory is None:
            self._inventory = FileInventory(self.base_path)
        return self._inventory

    def detect_drift(self, severities: list[str] | None = None) -> DriftDetector:
        """Run comprehensive drift detection.

        Scans entire codebase and compares against documentation.
        Returns rich context suitable for AI agent reasoning.

        Args:
            severities: Filter to specific severities (critical, high, medium, low, info).

        Returns:
            DriftDetector with alerts populated.

        Usage for AI agent integration:
            agent = DocumentationAuditAgent("/path/to/pullDB")
            drift = agent.detect_drift()

            # Get context for AI reasoning
            context = drift.to_agent_context()

            # Get structured data
            summary = drift.get_summary()

            # Get individual alerts
            for alert in drift.alerts:
                print(alert.to_agent_prompt())
        """
        self.drift_detector.detect_all()

        if severities:
            self.drift_detector.alerts = [
                a for a in self.drift_detector.alerts
                if a.severity in severities
            ]

        return self.drift_detector

    def get_copilot_context(self) -> str:
        """Generate context summary for Copilot/AI agent reasoning.

        This method provides a comprehensive summary of the codebase state
        and any drift from documentation, formatted for AI consumption.

        Returns:
            Markdown-formatted context for AI reasoning.
        """
        # Run drift detection
        self.detect_drift()

        sections = []

        # Summary
        summary = self.drift_detector.get_summary()
        sections.append(f"""# Codebase Documentation Audit

**Files Scanned**: {summary['inventory_summary']['total_files']}
**Documentation Drift Alerts**: {summary['total_alerts']}

## Alert Summary by Severity
""")

        for sev, count in summary.get("by_severity", {}).items():
            emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}.get(sev, "⚫")
            sections.append(f"- {emoji} **{sev}**: {count}")

        sections.append("\n## Alert Summary by Type\n")
        for dtype, count in summary.get("by_type", {}).items():
            sections.append(f"- **{dtype}**: {count}")

        # Full drift context
        if summary["total_alerts"] > 0:
            sections.append("\n---\n")
            sections.append(self.drift_detector.to_agent_context())

        return "\n".join(sections)

    def audit_changes(self, since: str = "HEAD~1") -> AuditReport:
        """Audit documentation based on recent git changes.

        Args:
            since: Git ref to compare against (default: last commit).

        Returns:
            Audit report with findings.
        """
        start_time = time.time()
        report = AuditReport(trigger=f"git_changes:{since}")

        # Get changed files
        changed_files = self._get_git_diff(since)
        report.changed_files = changed_files

        if not changed_files:
            report.duration_seconds = time.time() - start_time
            return report

        # Find affected mappings
        affected_mappings: set[DocCodeMapping] = set()
        for file_path in changed_files:
            affected_mappings.update(get_mappings_for_file(file_path))

        # Audit each affected mapping
        for mapping in affected_mappings:
            findings = self._audit_mapping(mapping)
            report.findings.extend(findings)
            report.sections_checked.append(mapping.doc_section)

            # Auto-fix if enabled
            if self.auto_fix:
                fixed = self._apply_fixes(findings)
                report.auto_fixed += fixed

        report.duration_seconds = time.time() - start_time
        return report

    def audit_staged(self) -> AuditReport:
        """Audit documentation based on staged git changes.

        For use in pre-commit hooks.

        Returns:
            Audit report with findings.
        """
        start_time = time.time()
        report = AuditReport(trigger="pre_commit")

        # Get staged files
        staged_files = self._get_git_staged()
        report.changed_files = staged_files

        if not staged_files:
            report.duration_seconds = time.time() - start_time
            return report

        # Find affected mappings (use dict to deduplicate by doc_section)
        affected_mappings: dict[str, DocCodeMapping] = {}
        for file_path in staged_files:
            for mapping in get_mappings_for_file(file_path):
                affected_mappings[mapping.doc_section] = mapping

        # Audit each affected mapping
        for mapping in affected_mappings.values():
            findings = self._audit_mapping(mapping)
            report.findings.extend(findings)
            report.sections_checked.append(mapping.doc_section)

        report.duration_seconds = time.time() - start_time
        return report

    def audit_full(self) -> AuditReport:
        """Perform a full audit of all documentation mappings.

        Returns:
            Audit report with findings.
        """
        start_time = time.time()
        report = AuditReport(trigger="full_audit")

        # Audit all mappings
        for mapping in get_all_mappings():
            findings = self._audit_mapping(mapping)
            report.findings.extend(findings)
            report.sections_checked.append(mapping.doc_section)

            # Auto-fix if enabled
            if self.auto_fix:
                fixed = self._apply_fixes(findings)
                report.auto_fixed += fixed

        report.duration_seconds = time.time() - start_time
        return report

    def audit_section(self, section_name: str) -> AuditReport:
        """Audit a specific documentation section.

        Args:
            section_name: Partial or full section name.

        Returns:
            Audit report with findings.
        """
        from pulldb.audit.mappings import get_mappings_by_section

        start_time = time.time()
        report = AuditReport(trigger=f"section:{section_name}")

        mappings = get_mappings_by_section(section_name)
        for mapping in mappings:
            findings = self._audit_mapping(mapping)
            report.findings.extend(findings)
            report.sections_checked.append(mapping.doc_section)

        report.duration_seconds = time.time() - start_time
        return report

    def _audit_mapping(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Audit a single documentation-code mapping.

        Args:
            mapping: The mapping to verify.

        Returns:
            List of findings for this mapping.
        """
        findings: list[AuditFinding] = []

        # Dispatch to appropriate verification method
        verification_methods = {
            "exports": self._verify_exports,
            "class_names": self._verify_class_names,
            "function_names": self._verify_function_names,
            "css_values": self._verify_css_values,
            "css_classes": self._verify_css_classes,
            "file_count": self._verify_file_count,
            "file_list": self._verify_file_list,
            "click_commands": self._verify_click_commands,
            "route_count": self._verify_route_count,
            "constants": self._verify_constants,
            "dataclass_fields": self._verify_dataclass_fields,
            "class_methods": self._verify_class_methods,
            "config_value": self._verify_config_value,
        }

        verify_method = verification_methods.get(mapping.verification_type)
        if verify_method:
            findings.extend(verify_method(mapping))
        else:
            logger.warning(f"Unknown verification type: {mapping.verification_type}")

        return findings

    def _verify_exports(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify __all__ exports match documentation."""
        findings = []

        for pattern in mapping.code_patterns:
            files = self._files.list_files(pattern, self.base_path)
            for file_path in files:
                actual_exports = self._python.extract_exports(file_path)

                # Get documented exports from JSON
                if mapping.json_path:
                    documented = self.parser.get_json_value(mapping.json_path)
                    if documented and isinstance(documented, list):
                        # Compare
                        actual_set = set(actual_exports)
                        documented_set = set(documented)

                        missing = documented_set - actual_set
                        extra = actual_set - documented_set

                        if missing or extra:
                            findings.append(AuditFinding(
                                doc_file=self.parser.json_path,
                                doc_section=mapping.doc_section,
                                code_file=file_path,
                                code_location="__all__",
                                severity=FindingSeverity.HIGH,
                                category="exports",
                                description=f"Exports mismatch in {file_path.name}",
                                documented_value=str(documented),
                                actual_value=str(actual_exports),
                                suggested_fix=f"Update {mapping.json_path} to {actual_exports}",
                                auto_fixable=True,
                            ))

        return findings

    def _verify_class_names(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify class names match documentation."""
        findings = []
        all_classes: list[str] = []

        for pattern in mapping.code_patterns:
            files = self._files.list_files(pattern, self.base_path)
            for file_path in files:
                classes = self._python.extract_class_names(file_path)
                all_classes.extend(classes)

        # Check if documented classes exist
        documented_facts = self.parser.parse_markdown().get(mapping.doc_section, [])
        for fact in documented_facts:
            if "class" in fact.key.lower() or fact.key in ["Mock Adapters", "Simulated"]:
                # Extract class names from the documented value
                doc_classes = self._extract_class_names_from_text(fact.value)
                for doc_class in doc_classes:
                    if doc_class not in all_classes:
                        # Check for similar names (renamed classes)
                        similar = self._find_similar_class(doc_class, all_classes)
                        findings.append(AuditFinding(
                            doc_file=self.parser.md_path,
                            doc_section=mapping.doc_section,
                            code_file=Path("multiple"),
                            code_location="class definition",
                            severity=FindingSeverity.HIGH,
                            category="class_name",
                            description=f"Documented class '{doc_class}' not found",
                            documented_value=doc_class,
                            actual_value=similar or "not found",
                            suggested_fix=f"Update to '{similar}'" if similar else "Remove reference",
                            auto_fixable=bool(similar),
                        ))

        return findings

    def _verify_function_names(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify function names match documentation."""
        findings = []
        all_functions: list[str] = []

        for pattern in mapping.code_patterns:
            files = self._files.list_files(pattern, self.base_path)
            for file_path in files:
                functions = self._python.extract_function_names(file_path)
                all_functions.extend(functions)

        # Check documented functions
        documented_facts = self.parser.parse_markdown().get(mapping.doc_section, [])
        for fact in documented_facts:
            # Look for function references in values
            func_refs = self._extract_function_refs_from_text(fact.value)
            for func_name in func_refs:
                if func_name not in all_functions:
                    similar = self._find_similar_function(func_name, all_functions)
                    findings.append(AuditFinding(
                        doc_file=self.parser.md_path,
                        doc_section=mapping.doc_section,
                        code_file=Path("multiple"),
                        code_location="function definition",
                        severity=FindingSeverity.HIGH,
                        category="function_name",
                        description=f"Documented function '{func_name}' not found",
                        documented_value=func_name,
                        actual_value=similar or "not found",
                        suggested_fix=f"Update to '{similar}'" if similar else "Remove reference",
                        auto_fixable=bool(similar),
                    ))

        return findings

    def _verify_css_values(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify specific CSS values match documentation.
        
        This is a targeted verification that looks for specific values
        like timing delays, widths, etc. in CSS and JS files.
        """
        findings = []

        # For sidebar pattern, check specific values
        if "sidebar" in mapping.doc_section.lower():
            findings.extend(self._verify_sidebar_pattern(mapping))

        return findings

    def _verify_sidebar_pattern(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify sidebar-specific CSS/JS values."""
        findings = []

        # Check trigger width in CSS
        css_files = self._files.list_files(
            "pulldb/web/static/css/widgets/sidebar.css", self.base_path
        )
        for css_file in css_files:
            trigger_width = self._css.extract_property_value(
                css_file, ".sidebar-trigger", "width"
            )
            if trigger_width:
                doc_width = self.parser.get_json_value("web_ui.sidebar_pattern.trigger_zone_width")
                if doc_width and trigger_width.strip() != doc_width.strip():
                    findings.append(AuditFinding(
                        doc_file=self.parser.json_path,
                        doc_section=mapping.doc_section,
                        code_file=css_file,
                        code_location=".sidebar-trigger { width }",
                        severity=FindingSeverity.MEDIUM,
                        category="css_value",
                        description="Sidebar trigger width mismatch",
                        documented_value=doc_width,
                        actual_value=trigger_width,
                        suggested_fix=f"Update trigger_zone_width to '{trigger_width}'",
                        auto_fixable=True,
                    ))

        # Check close delay in JS
        js_files = self._files.list_files(
            "pulldb/web/static/js/main.js", self.base_path
        )
        for js_file in js_files:
            close_delay = self._js.extract_timeout_value(js_file, "closeSidebar")
            if close_delay is not None:
                doc_delay = self.parser.get_json_value("web_ui.sidebar_pattern.close_delay_ms")
                if doc_delay is not None and close_delay != int(doc_delay):
                    findings.append(AuditFinding(
                        doc_file=self.parser.json_path,
                        doc_section=mapping.doc_section,
                        code_file=js_file,
                        code_location="setTimeout(closeSidebar, ...)",
                        severity=FindingSeverity.MEDIUM,
                        category="js_timing",
                        description="Sidebar close delay mismatch",
                        documented_value=str(doc_delay),
                        actual_value=str(close_delay),
                        suggested_fix=f"Update close_delay_ms to {close_delay}",
                        auto_fixable=True,
                    ))

        return findings

        return findings

    def _verify_css_classes(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify CSS class names match documentation."""
        findings = []
        all_classes: set[str] = set()

        for pattern in mapping.code_patterns:
            files = self._files.list_files(pattern, self.base_path)
            for file_path in files:
                if file_path.suffix == ".css":
                    classes = self._css.extract_class_selectors(file_path)
                    all_classes.update(classes)

        # Check documented classes
        if mapping.json_path:
            doc_value = self.parser.get_json_value(mapping.json_path)
            if doc_value and isinstance(doc_value, dict):
                for key, selector in doc_value.items():
                    if isinstance(selector, str) and selector.startswith("."):
                        # Extract class name from selector
                        class_name = selector.lstrip(".").split()[0].split(".")[0]
                        if class_name not in all_classes:
                            findings.append(AuditFinding(
                                doc_file=self.parser.json_path,
                                doc_section=mapping.doc_section,
                                code_file=Path("CSS files"),
                                code_location="class selector",
                                severity=FindingSeverity.MEDIUM,
                                category="css_class",
                                description=f"CSS class '{class_name}' not found",
                                documented_value=selector,
                                actual_value="not found",
                                auto_fixable=False,
                            ))

        return findings

    def _verify_file_count(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify file counts match documentation."""
        findings = []

        for pattern in mapping.code_patterns:
            actual_count = self._files.count_files(pattern, self.base_path)

            if mapping.json_path:
                doc_count = self.parser.get_json_value(mapping.json_path)
                if doc_count is not None and int(doc_count) != actual_count:
                    findings.append(AuditFinding(
                        doc_file=self.parser.json_path,
                        doc_section=mapping.doc_section,
                        code_file=Path(pattern),
                        code_location="file count",
                        severity=FindingSeverity.MEDIUM,
                        category="file_count",
                        description=f"File count mismatch for {pattern}",
                        documented_value=str(doc_count),
                        actual_value=str(actual_count),
                        suggested_fix=f"Update to {actual_count}",
                        auto_fixable=True,
                    ))

        return findings

    def _verify_file_list(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify file lists match documentation."""
        # Similar to file_count but checks full list
        return []  # Placeholder

    def _verify_click_commands(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify Click CLI commands match documentation."""
        findings = []
        all_commands: list[str] = []

        for pattern in mapping.code_patterns:
            files = self._files.list_files(pattern, self.base_path)
            for file_path in files:
                facts = self._python.extract_facts(
                    file_path, [r"@\w+\.command\(['\"](\w+)['\"]"]
                )
                for fact in facts:
                    all_commands.append(fact.value)

        if mapping.json_path:
            doc_commands = self.parser.get_json_value(mapping.json_path)
            if doc_commands and isinstance(doc_commands, list):
                doc_set = set(doc_commands)
                actual_set = set(all_commands)

                missing = doc_set - actual_set
                extra = actual_set - doc_set

                if missing or extra:
                    findings.append(AuditFinding(
                        doc_file=self.parser.json_path,
                        doc_section=mapping.doc_section,
                        code_file=Path("CLI files"),
                        code_location="@command decorators",
                        severity=FindingSeverity.MEDIUM,
                        category="cli_commands",
                        description="CLI commands mismatch",
                        documented_value=str(doc_commands),
                        actual_value=str(all_commands),
                        auto_fixable=True,
                    ))

        return findings

    def _verify_route_count(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify API route counts match documentation."""
        findings = []
        route_count = 0

        for pattern in mapping.code_patterns:
            files = self._files.list_files(pattern, self.base_path)
            for file_path in files:
                facts = self._python.extract_facts(
                    file_path, [r"@router\.(get|post|put|delete|patch)\("]
                )
                route_count += len(facts)

        if mapping.json_path:
            doc_count = self.parser.get_json_value(mapping.json_path)
            if doc_count is not None and int(doc_count) != route_count:
                findings.append(AuditFinding(
                    doc_file=self.parser.json_path,
                    doc_section=mapping.doc_section,
                    code_file=Path("API routes"),
                    code_location="@router decorators",
                    severity=FindingSeverity.MEDIUM,
                    category="route_count",
                    description="API route count mismatch",
                    documented_value=str(doc_count),
                    actual_value=str(route_count),
                    auto_fixable=True,
                ))

        return findings

    def _verify_constants(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify constants match documentation."""
        return []  # Placeholder

    def _verify_dataclass_fields(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify dataclass fields match documentation."""
        return []  # Placeholder

    def _verify_class_methods(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify class methods match documentation."""
        return []  # Placeholder

    def _verify_config_value(self, mapping: DocCodeMapping) -> list[AuditFinding]:
        """Verify configuration values match documentation."""
        return []  # Placeholder

    def _apply_fixes(self, findings: list[AuditFinding]) -> int:
        """Apply automatic fixes for findings.

        Args:
            findings: List of findings to potentially fix.

        Returns:
            Number of findings that were fixed.
        """
        fixed = 0
        for finding in findings:
            if not finding.auto_fixable:
                continue

            # Try to apply fix based on category
            if finding.category in ["exports", "file_count", "route_count", "cli_commands"]:
                if finding.doc_file.suffix == ".json":
                    # Extract JSON path from the finding
                    # This is simplified - real implementation would be more robust
                    success = self.updater.update_json_value(
                        finding.doc_section.lower().replace(" ", "_"),
                        finding.actual_value,
                    )
                    if success:
                        fixed += 1
            elif finding.category in ["class_name", "function_name"]:
                if finding.suggested_fix and "Update to" in finding.suggested_fix:
                    success = self.updater.update_markdown_value(
                        finding.documented_value,
                        finding.actual_value,
                    )
                    if success:
                        fixed += 1

        return fixed

    def _get_git_diff(self, since: str) -> list[Path]:
        """Get list of changed files since a git ref.

        Args:
            since: Git reference to compare against.

        Returns:
            List of changed file paths.
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", since],
                capture_output=True,
                text=True,
                cwd=self.base_path,
            )
            if result.returncode == 0:
                return [
                    self.base_path / f
                    for f in result.stdout.strip().split("\n")
                    if f
                ]
        except subprocess.SubprocessError:
            pass
        return []

    def _get_git_staged(self) -> list[Path]:
        """Get list of staged files.

        Returns:
            List of staged file paths.
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                capture_output=True,
                text=True,
                cwd=self.base_path,
            )
            if result.returncode == 0:
                return [
                    self.base_path / f
                    for f in result.stdout.strip().split("\n")
                    if f
                ]
        except subprocess.SubprocessError:
            pass
        return []

    def _extract_class_names_from_text(self, text: str) -> list[str]:
        """Extract class name references from text."""
        # Match PascalCase names
        return re.findall(r"\b([A-Z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*)+)\b", text)

    def _extract_function_refs_from_text(self, text: str) -> list[str]:
        """Extract function name references from text."""
        # Match snake_case names that look like functions
        return re.findall(r"\b(get_\w+|set_\w+|create_\w+|delete_\w+|update_\w+|check_\w+|validate_\w+)\b", text)

    def _find_similar_class(self, name: str, candidates: list[str]) -> str | None:
        """Find a similar class name from candidates."""
        # Check for common rename patterns
        # Mock -> Simulated, etc.
        patterns = [
            (r"^Mock", "Simulated"),
            (r"^Simulated", "Mock"),
        ]

        for pattern, replacement in patterns:
            alt_name = re.sub(pattern, replacement, name)
            if alt_name in candidates:
                return alt_name

        # Check for partial matches
        name_lower = name.lower()
        for candidate in candidates:
            if name_lower in candidate.lower() or candidate.lower() in name_lower:
                return candidate

        return None

    def _find_similar_function(self, name: str, candidates: list[str]) -> str | None:
        """Find a similar function name from candidates."""
        # Common patterns
        patterns = [
            (r"current_user", "authenticated_user"),
            (r"authenticated_user", "current_user"),
        ]

        for pattern, replacement in patterns:
            if pattern in name:
                alt_name = name.replace(pattern, replacement)
                if alt_name in candidates:
                    return alt_name

        return None

    def _values_mismatch(self, actual: Any, documented: Any) -> bool:
        """Check if two values are meaningfully different."""
        # Handle numeric comparison
        try:
            if isinstance(documented, (int, float)):
                return float(actual) != float(documented)
        except (ValueError, TypeError):
            pass

        # String comparison
        return str(actual).strip() != str(documented).strip()
