"""Audit report data structures.

Defines the output format for documentation audits including
findings, severity levels, and suggested fixes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class FindingSeverity(Enum):
    """Severity level for audit findings."""

    CRITICAL = "critical"  # Documentation is wrong and misleading
    HIGH = "high"  # Significant discrepancy affecting understanding
    MEDIUM = "medium"  # Minor inaccuracy or outdated info
    LOW = "low"  # Style/formatting issue, still correct
    INFO = "info"  # Suggestion or enhancement


@dataclass
class AuditFinding:
    """Single finding from documentation audit.

    Attributes:
        doc_file: Path to documentation file with the issue.
        doc_section: Section name or line range in documentation.
        code_file: Path to code file that contradicts documentation.
        code_location: Line number or symbol in code.
        severity: How serious the discrepancy is.
        category: Type of issue (e.g., 'class_name', 'timing', 'css_class').
        description: Human-readable description of the finding.
        documented_value: What the documentation says.
        actual_value: What the code actually has.
        suggested_fix: Optional suggested correction.
        auto_fixable: Whether this can be auto-corrected.
    """

    doc_file: Path
    doc_section: str
    code_file: Path
    code_location: str
    severity: FindingSeverity
    category: str
    description: str
    documented_value: str
    actual_value: str
    suggested_fix: str | None = None
    auto_fixable: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert finding to dictionary for JSON serialization."""
        return {
            "doc_file": str(self.doc_file),
            "doc_section": self.doc_section,
            "code_file": str(self.code_file),
            "code_location": self.code_location,
            "severity": self.severity.value,
            "category": self.category,
            "description": self.description,
            "documented_value": self.documented_value,
            "actual_value": self.actual_value,
            "suggested_fix": self.suggested_fix,
            "auto_fixable": self.auto_fixable,
        }


@dataclass
class AuditReport:
    """Complete audit report from a documentation audit run.

    Attributes:
        timestamp: When the audit was performed.
        trigger: What triggered the audit (e.g., 'git_commit', 'manual', 'pre_commit').
        changed_files: List of files that triggered the audit.
        sections_checked: Documentation sections that were verified.
        findings: List of all findings discovered.
        auto_fixed: Number of findings that were auto-corrected.
        duration_seconds: How long the audit took.
    """

    timestamp: datetime = field(default_factory=datetime.now)
    trigger: str = "manual"
    changed_files: list[Path] = field(default_factory=list)
    sections_checked: list[str] = field(default_factory=list)
    findings: list[AuditFinding] = field(default_factory=list)
    auto_fixed: int = 0
    duration_seconds: float = 0.0

    @property
    def has_critical(self) -> bool:
        """Check if any critical findings exist."""
        return any(f.severity == FindingSeverity.CRITICAL for f in self.findings)

    @property
    def has_high(self) -> bool:
        """Check if any high severity findings exist."""
        return any(f.severity == FindingSeverity.HIGH for f in self.findings)

    @property
    def findings_by_severity(self) -> dict[FindingSeverity, list[AuditFinding]]:
        """Group findings by severity level."""
        result: dict[FindingSeverity, list[AuditFinding]] = {s: [] for s in FindingSeverity}
        for finding in self.findings:
            result[finding.severity].append(finding)
        return result

    @property
    def summary(self) -> str:
        """Generate human-readable summary."""
        by_severity = self.findings_by_severity
        counts = {s.value: len(by_severity[s]) for s in FindingSeverity}
        total = len(self.findings)

        if total == 0:
            return "✅ No documentation discrepancies found."

        lines = [
            f"📋 Audit found {total} finding(s):",
            f"   🔴 Critical: {counts['critical']}",
            f"   🟠 High: {counts['high']}",
            f"   🟡 Medium: {counts['medium']}",
            f"   🔵 Low: {counts['low']}",
            f"   ⚪ Info: {counts['info']}",
        ]
        if self.auto_fixed > 0:
            lines.append(f"   ✅ Auto-fixed: {self.auto_fixed}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "trigger": self.trigger,
            "changed_files": [str(f) for f in self.changed_files],
            "sections_checked": self.sections_checked,
            "findings": [f.to_dict() for f in self.findings],
            "auto_fixed": self.auto_fixed,
            "duration_seconds": self.duration_seconds,
            "summary": self.summary,
        }

    def to_markdown(self) -> str:
        """Generate markdown report for SESSION-LOG."""
        lines = [
            f"## {self.timestamp.strftime('%Y-%m-%d %H:%M')} | Documentation Audit ({self.trigger})",
            "",
            "### Summary",
            self.summary,
            "",
        ]

        if self.changed_files:
            lines.extend([
                "### Triggered By",
                *[f"- `{f}`" for f in self.changed_files[:10]],
                "",
            ])

        if self.findings:
            lines.extend([
                "### Findings",
                "",
                "| Severity | Category | Description | Doc | Code |",
                "|----------|----------|-------------|-----|------|",
            ])
            for f in self.findings:
                lines.append(
                    f"| {f.severity.value} | {f.category} | {f.description} | "
                    f"`{f.documented_value[:30]}...` | `{f.actual_value[:30]}...` |"
                )
            lines.append("")

        lines.append(f"*Duration: {self.duration_seconds:.2f}s*")
        return "\n".join(lines)
