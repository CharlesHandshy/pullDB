"""Tests for the documentation audit agent.

These tests verify that the audit agent correctly identifies
discrepancies between KNOWLEDGE-POOL documentation and actual code.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pulldb.audit import DocumentationAuditAgent, AuditReport, FindingSeverity
from pulldb.audit.analyzers import PythonAnalyzer, CSSAnalyzer, JavaScriptAnalyzer
from pulldb.audit.knowledge_pool import KnowledgePoolParser


class TestPythonAnalyzer:
    """Test Python code analyzer."""

    def test_extract_exports(self, tmp_path: Path) -> None:
        """Test __all__ extraction from Python module."""
        py_file = tmp_path / "test_module.py"
        py_file.write_text('''
__all__ = [
    "ClassA",
    "ClassB",
    "function_c",
]

class ClassA:
    pass

class ClassB:
    pass

def function_c():
    pass
''')
        analyzer = PythonAnalyzer()
        exports = analyzer.extract_exports(py_file)

        assert exports == ["ClassA", "ClassB", "function_c"]

    def test_extract_class_names(self, tmp_path: Path) -> None:
        """Test class name extraction."""
        py_file = tmp_path / "test_classes.py"
        py_file.write_text('''
class MockRepository:
    pass

class SimulatedDatabase:
    pass

class RegularClass:
    pass
''')
        analyzer = PythonAnalyzer()

        # All classes
        all_classes = analyzer.extract_class_names(py_file)
        assert "MockRepository" in all_classes
        assert "SimulatedDatabase" in all_classes
        assert "RegularClass" in all_classes

        # Mock prefix only
        mock_classes = analyzer.extract_class_names(py_file, prefix="Mock")
        assert mock_classes == ["MockRepository"]

    def test_extract_function_names(self, tmp_path: Path) -> None:
        """Test function name extraction."""
        py_file = tmp_path / "test_functions.py"
        py_file.write_text('''
def get_user():
    pass

def get_authenticated_user():
    pass

def validate_input():
    pass
''')
        analyzer = PythonAnalyzer()

        functions = analyzer.extract_function_names(py_file)
        assert "get_user" in functions
        assert "get_authenticated_user" in functions
        assert "validate_input" in functions

        # With prefix
        get_functions = analyzer.extract_function_names(py_file, prefix="get_")
        assert len(get_functions) == 2


class TestCSSAnalyzer:
    """Test CSS analyzer."""

    def test_extract_class_selectors(self, tmp_path: Path) -> None:
        """Test CSS class selector extraction."""
        css_file = tmp_path / "test.css"
        css_file.write_text('''
.sidebar {
    width: 240px;
}

.sidebar-trigger {
    width: 5px;
}

.app-sidebar.sidebar-open {
    left: 0;
}
''')
        analyzer = CSSAnalyzer()
        classes = analyzer.extract_class_selectors(css_file)

        assert "sidebar" in classes
        assert "sidebar-trigger" in classes
        assert "app-sidebar" in classes
        assert "sidebar-open" in classes

    def test_extract_property_value(self, tmp_path: Path) -> None:
        """Test CSS property value extraction."""
        css_file = tmp_path / "test.css"
        css_file.write_text('''
.sidebar-trigger {
    position: fixed;
    left: 0;
    width: 5px;
    height: 100%;
}
''')
        analyzer = CSSAnalyzer()

        width = analyzer.extract_property_value(css_file, ".sidebar-trigger", "width")
        assert width == "5px"

        height = analyzer.extract_property_value(css_file, ".sidebar-trigger", "height")
        assert height == "100%"


class TestJavaScriptAnalyzer:
    """Test JavaScript analyzer."""

    def test_extract_timeout_value(self, tmp_path: Path) -> None:
        """Test setTimeout value extraction."""
        js_file = tmp_path / "test.js"
        js_file.write_text('''
function openSidebar() {
    // ...
}

function closeSidebar() {
    // ...
}

element.addEventListener('mouseleave', () => {
    setTimeout(closeSidebar, 300);
});
''')
        analyzer = JavaScriptAnalyzer()

        delay = analyzer.extract_timeout_value(js_file, "closeSidebar")
        assert delay == 300


class TestKnowledgePoolParser:
    """Test KNOWLEDGE-POOL parser."""

    def test_parse_markdown_sections(self, tmp_path: Path) -> None:
        """Test markdown section parsing."""
        md_file = tmp_path / "docs" / "KNOWLEDGE-POOL.md"
        md_file.parent.mkdir(parents=True)
        md_file.write_text('''
# KNOWLEDGE-POOL

## Database Schema
- `table_count`: 24
- **Note**: All tables in schema/

## Web UI Patterns
- Sidebar width: 240px
- Trigger zone: 5px
''')

        # Create empty JSON file
        json_file = tmp_path / "docs" / "KNOWLEDGE-POOL.json"
        json_file.write_text("{}")

        parser = KnowledgePoolParser(tmp_path)
        facts = parser.parse_markdown()

        assert "Database Schema" in facts
        assert "Web UI Patterns" in facts

    def test_get_json_value(self, tmp_path: Path) -> None:
        """Test JSON value extraction by path."""
        json_file = tmp_path / "docs" / "KNOWLEDGE-POOL.json"
        json_file.parent.mkdir(parents=True)
        json_file.write_text(json.dumps({
            "web_ui": {
                "sidebar_pattern": {
                    "trigger_zone_width": "5px",
                    "close_delay_ms": 300,
                }
            }
        }))

        # Create empty markdown file
        md_file = tmp_path / "docs" / "KNOWLEDGE-POOL.md"
        md_file.write_text("# KNOWLEDGE-POOL")

        parser = KnowledgePoolParser(tmp_path)

        width = parser.get_json_value("web_ui.sidebar_pattern.trigger_zone_width")
        assert width == "5px"

        delay = parser.get_json_value("web_ui.sidebar_pattern.close_delay_ms")
        assert delay == 300


class TestDocumentationAuditAgent:
    """Test the main audit agent."""

    def test_audit_full_no_findings(self) -> None:
        """Test full audit with properly synchronized docs."""
        # Use actual pullDB directory
        agent = DocumentationAuditAgent(base_path=Path.cwd())
        report = agent.audit_full()

        assert isinstance(report, AuditReport)
        assert report.trigger == "full_audit"
        assert len(report.sections_checked) > 0

    def test_audit_section_specific(self) -> None:
        """Test section-specific audit."""
        agent = DocumentationAuditAgent(base_path=Path.cwd())
        report = agent.audit_section("Sidebar")

        assert isinstance(report, AuditReport)
        assert "Hover-Reveal Sidebar Pattern" in report.sections_checked

    def test_report_summary(self) -> None:
        """Test report summary generation."""
        report = AuditReport()
        assert "No documentation discrepancies" in report.summary

        # Add a finding
        from pulldb.audit.report import AuditFinding
        report.findings.append(AuditFinding(
            doc_file=Path("test.md"),
            doc_section="Test",
            code_file=Path("test.py"),
            code_location="line 10",
            severity=FindingSeverity.HIGH,
            category="test",
            description="Test finding",
            documented_value="old",
            actual_value="new",
        ))
        assert "1 finding" in report.summary
        assert "High: 1" in report.summary

    def test_report_to_json(self) -> None:
        """Test report JSON serialization."""
        report = AuditReport(trigger="test")
        json_dict = report.to_dict()

        assert json_dict["trigger"] == "test"
        assert "timestamp" in json_dict
        assert "findings" in json_dict

    def test_report_to_markdown(self) -> None:
        """Test report markdown generation."""
        report = AuditReport(trigger="manual")
        md = report.to_markdown()

        assert "Documentation Audit" in md
        assert "manual" in md


class TestExportsMismatchDetection:
    """Test that exports mismatches are correctly detected."""

    def test_detects_missing_export(self, tmp_path: Path) -> None:
        """Test detection when documented export doesn't exist in code."""
        # Create mock directory structure
        sim_dir = tmp_path / "pulldb" / "simulation"
        sim_dir.mkdir(parents=True)

        init_file = sim_dir / "__init__.py"
        init_file.write_text('''
__all__ = ["ClassA", "ClassB"]

class ClassA:
    pass

class ClassB:
    pass
''')

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        json_file = docs_dir / "KNOWLEDGE-POOL.json"
        json_file.write_text(json.dumps({
            "simulation": {
                "exports": ["ClassA", "ClassB", "ClassC"]  # ClassC doesn't exist
            }
        }))

        md_file = docs_dir / "KNOWLEDGE-POOL.md"
        md_file.write_text("# KNOWLEDGE-POOL\n\n## Simulation Framework\n")

        # This tests the parsing, not full agent (which needs more setup)
        parser = KnowledgePoolParser(tmp_path)
        doc_exports = parser.get_json_value("simulation.exports")
        assert doc_exports == ["ClassA", "ClassB", "ClassC"]

        analyzer = PythonAnalyzer()
        actual_exports = analyzer.extract_exports(init_file)
        assert actual_exports == ["ClassA", "ClassB"]

        # The mismatch
        assert set(doc_exports) != set(actual_exports)
        assert "ClassC" in set(doc_exports) - set(actual_exports)


class TestDriftDetection:
    """Test comprehensive drift detection."""

    def test_detect_drift_returns_detector(self) -> None:
        """Test that detect_drift returns a DriftDetector."""
        from pulldb.audit import DriftDetector

        agent = DocumentationAuditAgent(base_path=Path.cwd())
        detector = agent.detect_drift()

        assert isinstance(detector, DriftDetector)

    def test_drift_detector_alerts_populated(self) -> None:
        """Test that drift detection populates alerts."""
        agent = DocumentationAuditAgent(base_path=Path.cwd())
        detector = agent.detect_drift()

        # Alerts should be a list (may be empty or populated)
        assert isinstance(detector.alerts, list)

    def test_drift_detector_summary(self) -> None:
        """Test drift detector summary generation."""
        agent = DocumentationAuditAgent(base_path=Path.cwd())
        detector = agent.detect_drift()

        summary = detector.get_summary()

        assert "total_alerts" in summary
        assert "by_type" in summary
        assert "by_severity" in summary
        assert "inventory_summary" in summary

    def test_copilot_context_generation(self) -> None:
        """Test Copilot context generation."""
        agent = DocumentationAuditAgent(base_path=Path.cwd())
        context = agent.get_copilot_context()

        assert isinstance(context, str)
        assert "Codebase Documentation Audit" in context
        assert "Files Scanned" in context

    def test_drift_severity_filter(self) -> None:
        """Test that severity filter works."""
        agent = DocumentationAuditAgent(base_path=Path.cwd())

        # Get all alerts
        detector_all = agent.detect_drift()
        all_count = len(detector_all.alerts)

        # Get only high severity
        agent._drift_detector = None  # Reset
        detector_high = agent.detect_drift(severities=["high"])

        # If there were any alerts, high-only should be <= all
        if all_count > 0:
            assert len(detector_high.alerts) <= all_count
            for alert in detector_high.alerts:
                assert alert.severity == "high"


class TestFileInventory:
    """Test file inventory functionality."""

    def test_inventory_scan(self) -> None:
        """Test that inventory scan works."""
        from pulldb.audit import FileInventory

        inventory = FileInventory(Path.cwd())
        inventory.scan()

        assert len(inventory.items) > 0

    def test_inventory_summary(self) -> None:
        """Test inventory summary."""
        from pulldb.audit import FileInventory

        inventory = FileInventory(Path.cwd())
        inventory.scan()
        summary = inventory.get_summary()

        assert "total_files" in summary
        assert "by_category" in summary
        assert summary["total_files"] > 0

    def test_inventory_excludes_venv(self) -> None:
        """Test that inventory excludes venv directory."""
        from pulldb.audit import FileInventory

        inventory = FileInventory(Path.cwd())
        inventory.scan()

        for path in inventory.items.keys():
            assert "venv" not in str(path)
            assert ".venv" not in str(path)
