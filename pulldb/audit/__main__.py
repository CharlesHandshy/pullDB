"""CLI interface for documentation audit agent.

Usage:
    # Audit recent changes (targeted)
    python -m pulldb.audit

    # Full targeted audit
    python -m pulldb.audit --full

    # COMPREHENSIVE DRIFT DETECTION (for AI reasoning)
    python -m pulldb.audit --drift

    # Drift detection with Copilot context
    python -m pulldb.audit --drift --copilot

    # Specific section
    python -m pulldb.audit --section "Sidebar"

    # Pre-commit mode (exit 1 if critical issues)
    python -m pulldb.audit --pre-commit

    # Auto-fix mode
    python -m pulldb.audit --auto-fix
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pulldb.audit import DocumentationAuditAgent, FindingSeverity


def main() -> int:
    """Run documentation audit from command line."""
    parser = argparse.ArgumentParser(
        description="Continuous documentation audit for KNOWLEDGE-POOL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # TARGETED AUDIT (fast, uses hardcoded mappings)
    python -m pulldb.audit              # Audit recent git changes
    python -m pulldb.audit --full       # Full audit of all mappings
    python -m pulldb.audit --section UI # Audit UI-related sections
    python -m pulldb.audit --pre-commit # For git pre-commit hook

    # COMPREHENSIVE DRIFT DETECTION (scans entire codebase)
    python -m pulldb.audit --drift                    # Find all drift
    python -m pulldb.audit --drift --severity high    # Only high severity
    python -m pulldb.audit --drift --copilot          # AI-friendly context
    python -m pulldb.audit --drift --json             # JSON output
        """,
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help="Perform full targeted audit of all documentation mappings",
    )
    parser.add_argument(
        "--drift",
        action="store_true",
        help="Comprehensive drift detection (scans entire codebase)",
    )
    parser.add_argument(
        "--copilot",
        action="store_true",
        help="Output context optimized for Copilot/AI agent reasoning",
    )
    parser.add_argument(
        "--severity",
        type=str,
        choices=["critical", "high", "medium", "low", "info"],
        help="Filter drift alerts by severity",
    )
    parser.add_argument(
        "--section",
        type=str,
        help="Audit specific section (partial match)",
    )
    parser.add_argument(
        "--since",
        type=str,
        default="HEAD~1",
        help="Git ref to compare against (default: HEAD~1)",
    )
    parser.add_argument(
        "--pre-commit",
        action="store_true",
        help="Pre-commit mode: check staged files, exit 1 if critical",
    )
    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="Automatically fix discovered issues",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON",
    )
    parser.add_argument(
        "--base-path",
        type=str,
        help="Base path of pullDB project (default: cwd)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # Determine base path
    base_path = Path(args.base_path) if args.base_path else Path.cwd()

    # Initialize agent
    agent = DocumentationAuditAgent(
        base_path=base_path,
        auto_fix=args.auto_fix,
    )

    # DRIFT DETECTION MODE
    if args.drift:
        return _run_drift_detection(agent, args)

    # TARGETED AUDIT MODE
    if args.pre_commit:
        report = agent.audit_staged()
    elif args.full:
        report = agent.audit_full()
    elif args.section:
        report = agent.audit_section(args.section)
    else:
        report = agent.audit_changes(since=args.since)

    # Output results
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"\n{'='*60}")
        print("📚 KNOWLEDGE-POOL Documentation Audit")
        print(f"{'='*60}\n")
        print(f"Trigger: {report.trigger}")
        print(f"Duration: {report.duration_seconds:.2f}s")
        print(f"Sections checked: {len(report.sections_checked)}")
        print()
        print(report.summary)
        print()

        if report.findings and args.verbose:
            print("\n📋 Detailed Findings:\n")
            for i, finding in enumerate(report.findings, 1):
                print(f"{i}. [{finding.severity.value.upper()}] {finding.category}")
                print(f"   {finding.description}")
                print(f"   Documented: {finding.documented_value[:80]}...")
                print(f"   Actual: {finding.actual_value[:80]}...")
                if finding.suggested_fix:
                    print(f"   Fix: {finding.suggested_fix}")
                print()

        if report.auto_fixed > 0:
            print(f"\n✅ Auto-fixed {report.auto_fixed} issue(s)")

    # Exit code
    if args.pre_commit:
        if report.has_critical:
            print("\n❌ CRITICAL documentation issues found. Commit blocked.")
            return 1
        elif report.has_high:
            print("\n⚠️  HIGH severity issues found. Consider fixing before commit.")
            return 0  # Warning only, don't block
    return 0


def _run_drift_detection(agent: DocumentationAuditAgent, args: argparse.Namespace) -> int:
    """Run comprehensive drift detection mode."""
    print("\n🔍 Running comprehensive drift detection...\n")

    # Filter by severity if specified
    severities = [args.severity] if args.severity else None
    drift = agent.detect_drift(severities=severities)

    # Copilot context mode
    if args.copilot:
        print(agent.get_copilot_context())
        return 0

    # JSON output
    if args.json:
        output = {
            "summary": drift.get_summary(),
            "alerts": [a.to_dict() for a in drift.alerts],
        }
        print(json.dumps(output, indent=2, default=str))
        return 0

    # Human-readable output
    summary = drift.get_summary()
    
    print(f"{'='*60}")
    print("🔍 COMPREHENSIVE DRIFT DETECTION REPORT")
    print(f"{'='*60}\n")

    inv = summary["inventory_summary"]
    print(f"📁 Files Scanned: {inv['total_files']}")
    print(f"   - Python: {inv.get('by_category', {}).get('python_module', 0) + inv.get('by_category', {}).get('python_init', 0)}")
    print(f"   - CSS: {inv.get('by_category', {}).get('css_stylesheet', 0)}")
    print(f"   - JS: {inv.get('by_category', {}).get('javascript', 0)}")
    print(f"   - SQL: {inv.get('by_category', {}).get('sql_schema', 0) + inv.get('by_category', {}).get('sql_seed', 0)}")
    print()

    # Alert summary
    total = summary["total_alerts"]
    if total == 0:
        print("✅ No documentation drift detected!")
        print("   KNOWLEDGE-POOL is synchronized with codebase.")
        return 0

    print(f"⚠️  Total Drift Alerts: {total}\n")

    # By severity
    by_sev = summary.get("by_severity", {})
    severity_icons = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🔵",
        "info": "⚪",
    }
    for sev in ["critical", "high", "medium", "low", "info"]:
        count = by_sev.get(sev, 0)
        if count > 0:
            print(f"  {severity_icons.get(sev, '⚫')} {sev.upper()}: {count}")

    print()

    # Show alerts
    if args.verbose or total <= 10:
        print("\n📋 Drift Alerts:\n")
        for i, alert in enumerate(drift.alerts, 1):
            sev_icon = severity_icons.get(alert.severity, "⚫")
            print(f"{i}. {sev_icon} [{alert.severity.upper()}] {alert.drift_type.value}")
            print(f"   File: {alert.file_path or 'N/A'}")
            print(f"   {alert.description}")
            if args.verbose:
                print(f"   Documented: {alert.documented_state}")
                print(f"   Actual: {alert.actual_state}")
                if alert.suggested_actions:
                    print(f"   Actions: {alert.suggested_actions[0]}")
            print()
    else:
        print(f"\nRun with -v or --verbose to see all {total} alerts")
        print("Or use --copilot for AI-friendly context")

    # Exit code based on severity
    if by_sev.get("critical", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())