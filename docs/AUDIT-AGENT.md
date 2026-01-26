# Documentation Audit Agent

Continuous documentation auditing to keep KNOWLEDGE-POOL synchronized with codebase reality.

## Overview

The Documentation Audit Agent automatically detects and reports discrepancies between the `docs/KNOWLEDGE-POOL.md` and `docs/KNOWLEDGE-POOL.json` documentation files and the actual codebase. It was built based on lessons learned from 11 passes of manual auditing.

## Two Modes of Operation

### 1. Targeted Audit (Fast, Deterministic)

Uses hardcoded mappings for precise verification of known doc-code relationships.
Best for CI/pre-commit hooks.

```bash
python -m pulldb.audit --full
python -m pulldb.audit --pre-commit
```

### 2. Comprehensive Drift Detection (For AI Reasoning)

Scans entire codebase and compares against KNOWLEDGE-POOL. Finds undocumented files,
missing exports, renamed classes, etc. Provides rich context for AI agent reasoning.

```bash
python -m pulldb.audit --drift
python -m pulldb.audit --drift --copilot  # AI-friendly context
python -m pulldb.audit --drift --severity high
```

## Usage

### Command Line - Targeted Audit

```bash
# Audit recent git changes (default: since last commit)
python -m pulldb.audit

# Full audit of all documentation mappings
python -m pulldb.audit --full

# Audit specific section
python -m pulldb.audit --section "Sidebar"

# Pre-commit mode (exit 1 if critical issues)
python -m pulldb.audit --pre-commit

# Auto-fix mode
python -m pulldb.audit --auto-fix

# JSON output
python -m pulldb.audit --full --json

# Verbose output with detailed findings
python -m pulldb.audit --full --verbose
```

### Command Line - Drift Detection

```bash
# Comprehensive drift detection
python -m pulldb.audit --drift

# Filter by severity
python -m pulldb.audit --drift --severity high

# AI/Copilot-friendly context (markdown output with reasoning context)
python -m pulldb.audit --drift --copilot

# JSON output for programmatic consumption
python -m pulldb.audit --drift --json
```

### Python API

```python
from pulldb.audit import DocumentationAuditAgent

# Initialize agent
agent = DocumentationAuditAgent()

# TARGETED AUDIT
report = agent.audit_changes()
report = agent.audit_full()

# Check results
if report.has_critical:
    print("Critical issues found!")
    for finding in report.findings:
        print(f"[{finding.severity}] {finding.description}")

# COMPREHENSIVE DRIFT DETECTION
drift = agent.detect_drift()

# Get AI-friendly context
context = agent.get_copilot_context()
print(context)

# Get individual alerts
for alert in drift.alerts:
    print(f"{alert.drift_type.value}: {alert.description}")
    print(f"  Suggested: {alert.suggested_actions[0]}")
```

### Pre-commit Hook

Install the pre-commit hook to automatically run audits before commits:

```bash
ln -sf ../../scripts/pre-commit-doc-audit.sh .git/hooks/pre-commit
```

## What It Checks

### Targeted Audit Verifications

| Category | What It Checks | Example |
|----------|---------------|---------|
| `exports` | Python `__all__` exports match documented | simulation package exports |
| `class_names` | Documented class names exist in code | MockJobRepository vs SimulatedJobRepository |
| `function_names` | Documented functions exist | get_current_user vs get_authenticated_user |
| `css_values` | CSS property values match documentation | sidebar trigger width, timing delays |
| `css_classes` | Documented CSS classes exist | .app-sidebar.sidebar-open |
| `file_count` | File counts match documented numbers | schema files, help pages |
| `cli_commands` | CLI commands match documentation | user and admin commands |
| `route_count` | API endpoint counts match | REST API routes |

### Drift Detection Types

| Type | Description | Severity |
|------|-------------|----------|
| `undocumented_file` | New file not in docs | medium-high |
| `missing_file` | Documented file doesn't exist | high |
| `renamed_file` | File appears to be renamed | high |
| `undocumented_class` | New class not documented | medium |
| `missing_export` | Documented export not in __all__ | high |
| `extra_export` | Export in __all__ but not documented | medium |
| `renamed_symbol` | Class/function renamed | high |
| `count_mismatch` | File/endpoint counts wrong | medium |
| `value_mismatch` | Timing, width values changed | medium |
| `package_restructure` | Package layout changed | info |

## Adding New Mappings

To add new documentation-to-code mappings, edit `pulldb/audit/mappings.py`:

```python
DocCodeMapping(
    doc_section="My New Section",      # Section header in KNOWLEDGE-POOL.md
    code_patterns=["path/to/*.py"],    # Glob patterns for code files
    verification_type="exports",        # Type of verification
    search_patterns=[r"__all__"],      # Regex patterns to search
    json_path="$.my_section.exports",  # JSONPath in KNOWLEDGE-POOL.json
    priority=2,                        # 1=highest, 5=lowest
)
```

## Finding Severity Levels

| Level | Meaning | Example |
|-------|---------|---------|
| CRITICAL | Documentation is wrong and misleading | Wrong API endpoint URL |
| HIGH | Significant discrepancy affecting understanding | Wrong class name |
| MEDIUM | Minor inaccuracy or outdated info | File count off by 1 |
| LOW | Style/formatting issue, still correct | Inconsistent naming |
| INFO | Suggestion or enhancement | Could add more detail |

## Architecture

```
pulldb/audit/
├── __init__.py          # Package exports
├── __main__.py          # CLI interface
├── agent.py             # Main orchestrator
├── analyzers.py         # Code analyzers (Python, CSS, JS, SQL)
├── knowledge_pool.py    # KNOWLEDGE-POOL parser/updater
├── mappings.py          # Documentation-to-code mappings
└── report.py            # Report data structures
```

## HCA Layer

This package is in the **features** layer (business logic for documentation maintenance).

```
┌─────────────────────────────────────────────────────┐
│ features/ → pulldb/audit/         Business logic   │
└─────────────────────────────────────────────────────┘
```

## Based On

This agent was built based on findings from 11 passes of manual auditing:

- **Pass 1-3**: Schema structure, file counts, broken links
- **Pass 4-6**: RBAC roles, settings keys, CLI commands
- **Pass 7-9**: API counts, help pages, test configuration
- **Pass 10-11**: Code examples, class names, CSS/JS values

## See Also

- [KNOWLEDGE-POOL.md](KNOWLEDGE-POOL.md) - The documentation being audited
- [KNOWLEDGE-POOL.json](KNOWLEDGE-POOL.json) - Machine-readable companion
- [SESSION-LOG.md](../.pulldb/SESSION-LOG.md) - Audit history
