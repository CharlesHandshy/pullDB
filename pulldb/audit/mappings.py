"""Documentation-to-Code Mapping Registry.

Maps documentation sections in KNOWLEDGE-POOL.md/.json to their
corresponding code locations. This is the source of truth for
what code should be verified when auditing documentation.

Based on lessons learned from 11 passes of manual auditing.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class DocCodeMapping:
    """Mapping between a documentation section and code to verify.

    Attributes:
        doc_section: Section header or JSON path in KNOWLEDGE-POOL.
        code_patterns: Glob patterns for code files to check.
        verification_type: Type of verification to perform.
        search_patterns: Regex patterns to find documented values in code.
        json_path: JSONPath to corresponding entry in KNOWLEDGE-POOL.json.
        priority: Audit priority (1=highest, 5=lowest).
    """

    doc_section: str
    code_patterns: list[str]
    verification_type: str
    search_patterns: list[str]
    json_path: str | None = None
    priority: int = 3


# =============================================================================
# MAPPING REGISTRY
# Based on patterns discovered during 11 audit passes
# =============================================================================

MAPPINGS: list[DocCodeMapping] = [
    # -------------------------------------------------------------------------
    # SIMULATION PACKAGE - Pass 10 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="Simulation Framework",
        code_patterns=["pulldb/simulation/__init__.py"],
        verification_type="exports",
        search_patterns=[r"__all__\s*=\s*\[([^\]]+)\]"],
        json_path="$.simulation.exports",
        priority=1,
    ),
    DocCodeMapping(
        doc_section="Mock Adapters",
        code_patterns=["pulldb/simulation/**/*.py"],
        verification_type="class_names",
        search_patterns=[r"class\s+(Mock\w+|Simulated\w+)"],
        json_path="$.simulation.mock_adapters",
        priority=1,
    ),
    # -------------------------------------------------------------------------
    # AUTH FUNCTIONS - Pass 10 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="RBAC Usage Patterns",
        code_patterns=["pulldb/api/auth.py"],
        verification_type="function_names",
        search_patterns=[r"def\s+(get_\w+_user|require_\w+)"],
        json_path="$.rbac.auth_functions",
        priority=1,
    ),
    DocCodeMapping(
        doc_section="Permission Functions",
        code_patterns=["pulldb/api/dependencies.py", "pulldb/api/auth.py"],
        verification_type="function_names",
        search_patterns=[r"def\s+(require_|check_|has_)"],
        json_path="$.rbac.permissions",
        priority=2,
    ),
    # -------------------------------------------------------------------------
    # WEB UI CSS - Pass 11 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="Hover-Reveal Sidebar Pattern",
        code_patterns=[
            "pulldb/web/static/css/widgets/sidebar.css",
            "pulldb/web/static/js/main.js",
        ],
        verification_type="css_values",
        search_patterns=[
            r"\.sidebar-trigger\s*\{[^}]*width:\s*(\d+px)",
            r"\.app-sidebar\.sidebar-open",
            r"setTimeout\(closeSidebar,\s*(\d+)\)",
        ],
        json_path="$.web_ui.sidebar_pattern",
        priority=1,
    ),
    DocCodeMapping(
        doc_section="Responsive Table Layout Pattern",
        code_patterns=["pulldb/web/static/css/shared/layout.css"],
        verification_type="css_classes",
        search_patterns=[
            r"\.(app-body|main-content|content-body)\s*\{",
        ],
        json_path="$.web_ui.responsive_table",
        priority=2,
    ),
    # -------------------------------------------------------------------------
    # SCHEMA - Pass 1 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="Database Schema",
        code_patterns=["schema/00_tables/*.sql"],
        verification_type="file_count",
        search_patterns=[],
        json_path="$.schema.table_count",
        priority=2,
    ),
    DocCodeMapping(
        doc_section="Schema Files",
        code_patterns=["schema/**/*.sql"],
        verification_type="file_list",
        search_patterns=[],
        json_path="$.schema.files",
        priority=3,
    ),
    # -------------------------------------------------------------------------
    # CLI COMMANDS - Pass 5 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="CLI Commands",
        code_patterns=["pulldb/cli/**/*.py"],
        verification_type="click_commands",
        search_patterns=[r"@\w+\.command\(['\"](\w+)['\"]"],
        json_path="$.cli.commands",
        priority=2,
    ),
    DocCodeMapping(
        doc_section="Admin CLI",
        code_patterns=["pulldb/cli/admin*.py"],
        verification_type="click_commands",
        search_patterns=[r"@\w+\.command\(['\"](\w+)['\"]"],
        json_path="$.cli.admin_commands",
        priority=2,
    ),
    # -------------------------------------------------------------------------
    # API ENDPOINTS - Pass 7 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="REST API Endpoints",
        code_patterns=["pulldb/api/routes/**/*.py"],
        verification_type="route_count",
        search_patterns=[r"@router\.(get|post|put|delete|patch)\("],
        json_path="$.api.endpoint_count",
        priority=2,
    ),
    # -------------------------------------------------------------------------
    # SETTINGS - Pass 4 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="Settings Keys",
        code_patterns=["pulldb/domain/config.py", "pulldb/infra/settings.py"],
        verification_type="constants",
        search_patterns=[r'[A-Z_]+\s*=\s*["\']([^"\']+)["\']'],
        json_path="$.settings.keys",
        priority=3,
    ),
    # -------------------------------------------------------------------------
    # DOMAIN MODELS - Pass 10 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="MySQLCredentials",
        code_patterns=["pulldb/domain/models.py"],
        verification_type="dataclass_fields",
        search_patterns=[r"class MySQLCredentials.*?(?=class|\Z)"],
        json_path="$.domain.mysql_credentials",
        priority=2,
    ),
    DocCodeMapping(
        doc_section="CredentialResolver",
        code_patterns=["pulldb/infra/secrets.py"],
        verification_type="class_methods",
        search_patterns=[r"def\s+(resolve|_resolve_from_\w+)"],
        json_path="$.infra.credential_resolver",
        priority=2,
    ),
    # -------------------------------------------------------------------------
    # HELP PAGES - Pass 8 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="Help Pages",
        code_patterns=["pulldb/web/help/templates/**/*.html"],
        verification_type="file_count",
        search_patterns=[],
        json_path="$.web.help_page_count",
        priority=3,
    ),
    # -------------------------------------------------------------------------
    # AFTER-SQL TEMPLATES - Pass 8 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="After-SQL Templates",
        code_patterns=["pulldb/template_after_sql/*.sql"],
        verification_type="file_count",
        search_patterns=[],
        json_path="$.templates.after_sql_count",
        priority=3,
    ),
    # -------------------------------------------------------------------------
    # TEST CONFIGURATION - Pass 9 findings
    # -------------------------------------------------------------------------
    DocCodeMapping(
        doc_section="Test MySQL User",
        code_patterns=["tests/conftest.py", "pyproject.toml"],
        verification_type="config_value",
        search_patterns=[r'MYSQL_USER["\s:=]+["\']?(\w+)'],
        json_path="$.test.mysql_user",
        priority=2,
    ),
]


def get_mappings_for_file(changed_file: Path) -> list[DocCodeMapping]:
    """Get all documentation mappings affected by a changed file.

    Args:
        changed_file: Path to a file that was modified.

    Returns:
        List of mappings that need to be verified.
    """
    import fnmatch

    results = []
    file_str = str(changed_file)

    for mapping in MAPPINGS:
        for pattern in mapping.code_patterns:
            # Handle glob patterns
            if fnmatch.fnmatch(file_str, pattern) or fnmatch.fnmatch(
                file_str, f"**/{pattern}"
            ):
                results.append(mapping)
                break

    return sorted(results, key=lambda m: m.priority)


def get_mappings_by_section(section_name: str) -> list[DocCodeMapping]:
    """Get mappings for a specific documentation section.

    Args:
        section_name: Partial or full section name to match.

    Returns:
        List of matching mappings.
    """
    return [
        m for m in MAPPINGS if section_name.lower() in m.doc_section.lower()
    ]


def get_all_mappings() -> list[DocCodeMapping]:
    """Get all registered mappings, sorted by priority."""
    return sorted(MAPPINGS, key=lambda m: m.priority)
