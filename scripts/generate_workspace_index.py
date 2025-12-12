#!/usr/bin/env python3
"""
AST-based workspace index generator for pullDB.

Generates WORKSPACE-INDEX.md and WORKSPACE-INDEX.json from Python source files.
Includes HCA layer detection and import violation checking.

Usage:
    python scripts/generate_workspace_index.py           # Generate indexes
    python scripts/generate_workspace_index.py --check   # Check for drift (CI mode)
    python scripts/generate_workspace_index.py --json    # Output JSON only
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PULLDB_SRC = PROJECT_ROOT / "pulldb"
TESTS_DIR = PROJECT_ROOT / "tests"
PULLDB_TESTS_DIR = PULLDB_SRC / "tests"
SCHEMA_DIR = PROJECT_ROOT / "schema" / "pulldb_service"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DOCS_DIR = PROJECT_ROOT / "docs"

OUTPUT_MD = DOCS_DIR / "WORKSPACE-INDEX.md"
OUTPUT_JSON = DOCS_DIR / "WORKSPACE-INDEX.json"

# HCA layer mapping: path prefix -> layer name
HCA_LAYER_MAP: dict[str, str] = {
    "pulldb/infra/": "shared",
    "pulldb/auth/": "shared",  # password.py, repository.py are infrastructure
    "pulldb/domain/": "entities",
    "pulldb/domain/services/": "features",  # services are features
    "pulldb/worker/": "features",
    "pulldb/worker/service.py": "widgets",  # orchestrator is widget
    "pulldb/simulation/adapters/": "shared",  # mock infrastructure
    "pulldb/simulation/core/": "features",  # simulation logic
    "pulldb/simulation/api/": "pages",  # simulation endpoints
    "pulldb/cli/": "pages",
    "pulldb/api/": "pages",
    "pulldb/web/": "pages",  # default for web
    "pulldb/web/shared/": "shared",
    "pulldb/web/entities/": "entities",
    "pulldb/web/features/": "features",
    "pulldb/web/widgets/": "widgets",
    "pulldb/web/pages/": "pages",
    "pulldb/binaries/": "plugins",
}

# Layer ordering for import validation (lower index = lower layer)
LAYER_ORDER = ["shared", "entities", "features", "widgets", "pages", "plugins"]


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class FunctionInfo:
    """Information about a function or method."""

    name: str
    signature: str
    decorators: list[str] = field(default_factory=list)
    docstring_summary: str | None = None
    is_async: bool = False


@dataclass
class ClassInfo:
    """Information about a class."""

    name: str
    bases: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    is_dataclass: bool = False
    is_enum: bool = False
    is_protocol: bool = False
    docstring_summary: str | None = None


@dataclass
class ModuleInfo:
    """Information about a Python module."""

    path: str
    hca_layer: str
    docstring: str | None = None
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    protocols: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)


@dataclass
class HCAViolation:
    """An HCA import violation."""

    file: str
    violation_type: str
    detail: str
    from_layer: str
    to_layer: str


@dataclass
class TestMapping:
    """Mapping of source file to test files."""

    source: str
    tests: list[str]
    coverage_area: str


# ---------------------------------------------------------------------------
# AST Parsing Functions
# ---------------------------------------------------------------------------


def get_hca_layer(rel_path: str) -> str:
    """Determine HCA layer for a file path."""
    # Check specific paths first (more specific = higher priority)
    for prefix, layer in sorted(HCA_LAYER_MAP.items(), key=lambda x: -len(x[0])):
        if rel_path.startswith(prefix) or rel_path == prefix.rstrip("/"):
            return layer
    return "unknown"


def extract_docstring_summary(node: ast.AST) -> str | None:
    """Extract first line of docstring."""
    docstring = ast.get_docstring(node)
    if docstring:
        return docstring.split("\n")[0].strip()
    return None


def extract_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Extract function signature as string."""
    args = []
    for arg in node.args.args:
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"
        args.append(arg_str)

    returns = ""
    if node.returns:
        returns = f" -> {ast.unparse(node.returns)}"

    return f"({', '.join(args)}){returns}"


def extract_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    """Extract decorator names."""
    decorators = []
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name):
            decorators.append(decorator.id)
        elif isinstance(decorator, ast.Attribute):
            decorators.append(f"{ast.unparse(decorator)}")
        elif isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                decorators.append(decorator.func.id)
            elif isinstance(decorator.func, ast.Attribute):
                decorators.append(f"{ast.unparse(decorator.func)}")
    return decorators


def extract_imports(tree: ast.Module) -> list[str]:
    """Extract all import statements."""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def extract_endpoints(tree: ast.Module) -> list[str]:
    """Extract FastAPI route endpoints."""
    endpoints = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Look for @router.get("/path"), @app.post("/path"), etc.
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in ("get", "post", "put", "delete", "patch"):
                    if node.args and isinstance(node.args[0], ast.Constant):
                        endpoints.append(f"{node.func.attr.upper()} {node.args[0].value}")
    return endpoints


def is_protocol_class(node: ast.ClassDef) -> bool:
    """Check if class is a Protocol."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def is_enum_class(node: ast.ClassDef) -> bool:
    """Check if class is an Enum."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in ("Enum", "IntEnum", "StrEnum"):
            return True
        if isinstance(base, ast.Attribute) and base.attr in ("Enum", "IntEnum", "StrEnum"):
            return True
    return False


def is_dataclass(node: ast.ClassDef) -> bool:
    """Check if class is a dataclass."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
            return True
        if isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name) and decorator.func.id == "dataclass":
                return True
    return False


def parse_module(file_path: Path, rel_path: str) -> ModuleInfo | None:
    """Parse a Python module and extract information."""
    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"Warning: Could not parse {rel_path}: {e}", file=sys.stderr)
        return None

    hca_layer = get_hca_layer(rel_path)
    module_info = ModuleInfo(
        path=rel_path,
        hca_layer=hca_layer,
        docstring=extract_docstring_summary(tree),
        imports=extract_imports(tree),
        endpoints=extract_endpoints(tree),
    )

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_info = ClassInfo(
                name=node.name,
                bases=[ast.unparse(base) for base in node.bases],
                methods=[
                    n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
                ],
                is_dataclass=is_dataclass(node),
                is_enum=is_enum_class(node),
                is_protocol=is_protocol_class(node),
                docstring_summary=extract_docstring_summary(node),
            )
            module_info.classes.append(class_info)
            if class_info.is_protocol:
                module_info.protocols.append(class_info.name)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                func_info = FunctionInfo(
                    name=node.name,
                    signature=extract_function_signature(node),
                    decorators=extract_decorators(node),
                    docstring_summary=extract_docstring_summary(node),
                    is_async=isinstance(node, ast.AsyncFunctionDef),
                )
                module_info.functions.append(func_info)

    return module_info


# ---------------------------------------------------------------------------
# HCA Validation
# ---------------------------------------------------------------------------


def check_hca_violations(modules: list[ModuleInfo]) -> list[HCAViolation]:
    """Check for HCA import violations (importing from higher layers)."""
    violations = []

    # Build module -> layer mapping
    module_layers: dict[str, str] = {}
    for mod in modules:
        # Map pulldb.x.y to layer
        py_module = mod.path.replace("/", ".").replace(".py", "")
        module_layers[py_module] = mod.hca_layer

    for mod in modules:
        mod_layer = mod.hca_layer
        mod_layer_idx = LAYER_ORDER.index(mod_layer) if mod_layer in LAYER_ORDER else -1

        for imp in mod.imports:
            # Only check pulldb imports
            if not imp.startswith("pulldb"):
                continue

            # Find the layer of the imported module
            imp_layer = None
            for py_mod, layer in module_layers.items():
                if imp.startswith(py_mod) or py_mod.startswith(imp):
                    imp_layer = layer
                    break

            if imp_layer is None:
                continue

            imp_layer_idx = LAYER_ORDER.index(imp_layer) if imp_layer in LAYER_ORDER else -1

            # Check for upward import
            if imp_layer_idx > mod_layer_idx and mod_layer_idx >= 0:
                violations.append(
                    HCAViolation(
                        file=mod.path,
                        violation_type="upward_import",
                        detail=f"Imports '{imp}' ({imp_layer}) from {mod_layer} layer",
                        from_layer=mod_layer,
                        to_layer=imp_layer,
                    )
                )

    return violations


# ---------------------------------------------------------------------------
# Test Mapping
# ---------------------------------------------------------------------------


def build_test_mapping(modules: list[ModuleInfo], test_files: list[str]) -> list[TestMapping]:
    """Build mapping of source files to test files."""
    mappings = []

    # Source file name patterns to test file patterns
    for mod in modules:
        if "tests" in mod.path or mod.path.endswith("__init__.py"):
            continue

        source_name = Path(mod.path).stem
        related_tests = []

        for test_file in test_files:
            test_name = Path(test_file).stem
            # Common patterns: test_<module>, test_<module>_*, <module>_test
            if (
                test_name == f"test_{source_name}"
                or test_name.startswith(f"test_{source_name}_")
                or test_name == f"{source_name}_test"
                or source_name in test_name
            ):
                related_tests.append(test_file)

        if related_tests:
            # Determine coverage area from path
            parts = mod.path.split("/")
            if len(parts) >= 2:
                coverage_area = parts[1]  # pulldb/<area>/...
            else:
                coverage_area = "core"

            mappings.append(TestMapping(source=mod.path, tests=related_tests, coverage_area=coverage_area))

    return mappings


# ---------------------------------------------------------------------------
# File Discovery
# ---------------------------------------------------------------------------


def find_python_files(root: Path, exclude_patterns: list[str] | None = None) -> list[Path]:
    """Find all Python files in directory."""
    exclude_patterns = exclude_patterns or ["__pycache__", ".git", "venv", ".venv", "node_modules"]
    files = []
    for file in root.rglob("*.py"):
        if any(p in str(file) for p in exclude_patterns):
            continue
        files.append(file)
    return sorted(files)


def find_test_files() -> list[str]:
    """Find all test files."""
    test_files = []

    # tests/ directory
    if TESTS_DIR.exists():
        for f in find_python_files(TESTS_DIR):
            test_files.append(str(f.relative_to(PROJECT_ROOT)))

    # pulldb/tests/ directory
    if PULLDB_TESTS_DIR.exists():
        for f in find_python_files(PULLDB_TESTS_DIR):
            test_files.append(str(f.relative_to(PROJECT_ROOT)))

    return sorted(test_files)


def find_schema_files() -> list[dict[str, str]]:
    """Find schema SQL files."""
    schema_files = []
    if SCHEMA_DIR.exists():
        for f in sorted(SCHEMA_DIR.glob("*.sql")):
            name = f.name
            # Parse table/view from filename
            parts = name.split("_", 1)
            if len(parts) == 2:
                purpose = parts[1].replace(".sql", "")
            else:
                purpose = name.replace(".sql", "")

            schema_files.append({"name": name, "purpose": purpose})

    return schema_files


def find_script_files() -> dict[str, list[str]]:
    """Find and categorize script files."""
    scripts: dict[str, list[str]] = {
        "packaging": [],
        "build": [],
        "setup": [],
        "validation": [],
        "operations": [],
        "development": [],
    }

    if not SCRIPTS_DIR.exists():
        return scripts

    for f in sorted(SCRIPTS_DIR.iterdir()):
        if f.is_dir() or f.name.startswith("."):
            continue

        name = f.name
        # Categorize based on name patterns
        if any(p in name for p in ["install", "uninstall", "upgrade", "configure", "merge", "monitor", "service"]):
            scripts["packaging"].append(name)
        elif any(p in name for p in ["build", "deb"]):
            scripts["build"].append(name)
        elif any(p in name for p in ["setup", "teardown", "start-test"]):
            scripts["setup"].append(name)
        elif any(p in name for p in ["validate", "verify", "check", "audit"]):
            scripts["validation"].append(name)
        elif any(p in name for p in ["cleanup", "deploy", "migrate"]):
            scripts["operations"].append(name)
        else:
            scripts["development"].append(name)

    return scripts


# ---------------------------------------------------------------------------
# Output Generation
# ---------------------------------------------------------------------------


def generate_markdown(
    modules: list[ModuleInfo],
    test_files: list[str],
    test_mappings: list[TestMapping],
    violations: list[HCAViolation],
    baseline_violations: list[dict[str, Any]],
    schema_files: list[dict[str, str]],
    scripts: dict[str, list[str]],
) -> str:
    """Generate WORKSPACE-INDEX.md content."""
    today = datetime.now().strftime("%Y-%m-%d")

    # Count files by category
    src_count = len([m for m in modules if "tests" not in m.path])
    test_count = len(test_files)
    schema_count = len(schema_files)
    script_count = sum(len(v) for v in scripts.values())

    lines = [
        "# pullDB Workspace Index",
        "",
        "[← Back to Documentation Index](START-HERE.md)",
        "",
        "> **Purpose**: Comprehensive atomic-level index for AI model searching and navigation.  ",
        f"> **Last Updated**: {today}  ",
        f"> **File Count**: ~{src_count + test_count + schema_count + script_count} project files (excluding venv, .git, caches)",
        "",
        "---",
        "",
        "## Quick Reference",
        "",
        "| Category | Count | Primary Path |",
        "|----------|-------|--------------|",
        f"| Python Source | {src_count} | `pulldb/` |",
        f"| Tests | {test_count} | `pulldb/tests/`, `tests/` |",
        f"| Shell Scripts | {script_count} | `scripts/` |",
        f"| SQL Schema | {schema_count} | `schema/pulldb_service/` |",
        "| Documentation | 35+ | `docs/` |",
        "| Copilot Instructions | 6 | `.github/` |",
        "",
        "---",
        "",
        "## Architecture Overview",
        "",
        "```",
        "┌─────────┐    ┌─────────────┐    ┌──────────────────┐",
        "│   CLI   │───►│ API Service │───►│ MySQL Queue      │",
        "└─────────┘    │ (FastAPI)   │    │ (pulldb_service) │",
        "               └─────────────┘    └────────┬─────────┘",
        "                     │                     │",
        "                     ▼                     ▼",
        "              ┌─────────────┐   ┌────────────────────────┐",
        "              │   Web UI    │   │    Worker Service      │",
        "              │ (templates) │   │ ┌─────────┬──────────┐ │",
        "              └─────────────┘   │ │Download │ myloader │ │",
        "                                │ │  S3     │ restore  │ │",
        "                                │ └─────────┴──────────┘ │",
        "                                └────────────────────────┘",
        "```",
        "",
        "---",
        "",
        "## HCA Layer Summary",
        "",
        "| Layer | Directories | File Count |",
        "|-------|-------------|------------|",
    ]

    # Count by layer
    layer_counts: dict[str, int] = {layer: 0 for layer in LAYER_ORDER}
    layer_dirs: dict[str, set[str]] = {layer: set() for layer in LAYER_ORDER}
    for mod in modules:
        if mod.hca_layer in layer_counts:
            layer_counts[mod.hca_layer] += 1
            # Get directory
            dir_path = str(Path(mod.path).parent)
            layer_dirs[mod.hca_layer].add(dir_path)

    for layer in LAYER_ORDER:
        dirs = ", ".join(f"`{d}/`" for d in sorted(layer_dirs[layer])[:3])
        if len(layer_dirs[layer]) > 3:
            dirs += f" (+{len(layer_dirs[layer]) - 3} more)"
        lines.append(f"| **{layer}** | {dirs} | {layer_counts[layer]} |")

    lines.extend(
        [
            "",
            "---",
            "",
        ]
    )

    # Group modules by package
    packages: dict[str, list[ModuleInfo]] = {}
    for mod in modules:
        if "tests" in mod.path:
            continue
        parts = mod.path.split("/")
        if len(parts) >= 2:
            pkg = parts[1]
        else:
            pkg = "root"
        if pkg not in packages:
            packages[pkg] = []
        packages[pkg].append(mod)

    # Document each package
    section_num = 1
    for pkg_name in ["api", "auth", "cli", "domain", "infra", "simulation", "web", "worker", "binaries"]:
        if pkg_name not in packages:
            continue

        pkg_modules = packages[pkg_name]
        lines.extend(
            [
                f"## {section_num}. Package: `pulldb/{pkg_name}/`",
                "",
            ]
        )

        # Sub-packages detection
        sub_packages: dict[str, list[ModuleInfo]] = {"root": []}
        for mod in pkg_modules:
            parts = mod.path.split("/")
            if len(parts) >= 4:
                sub_pkg = parts[2]
            else:
                sub_pkg = "root"
            if sub_pkg not in sub_packages:
                sub_packages[sub_pkg] = []
            sub_packages[sub_pkg].append(mod)

        for sub_name, sub_mods in sorted(sub_packages.items()):
            if sub_name != "root":
                lines.append(f"### {pkg_name}/{sub_name}/")
                lines.append("")

            lines.extend(
                [
                    "| File | Layer | Key Elements |",
                    "|------|-------|--------------|",
                ]
            )

            for mod in sorted(sub_mods, key=lambda m: m.path):
                filename = Path(mod.path).name
                elements = []
                for cls in mod.classes[:3]:
                    prefix = ""
                    if cls.is_protocol:
                        prefix = "🔌 "
                    elif cls.is_enum:
                        prefix = "📊 "
                    elif cls.is_dataclass:
                        prefix = "📦 "
                    elements.append(f"{prefix}`{cls.name}`")
                for func in mod.functions[:3]:
                    elements.append(f"`{func.name}()`")
                if mod.endpoints:
                    elements.append(f"📍 {len(mod.endpoints)} endpoints")

                elements_str = ", ".join(elements[:5])
                if len(mod.classes) + len(mod.functions) > 5:
                    elements_str += f" (+{len(mod.classes) + len(mod.functions) - 5} more)"

                lines.append(f"| `{filename}` | {mod.hca_layer} | {elements_str} |")

            lines.append("")

        section_num += 1

    # Test Coverage Mapping
    lines.extend(
        [
            "---",
            "",
            "## Test Coverage Mapping",
            "",
            "| Source Module | Test File(s) | Coverage Area |",
            "|---------------|--------------|---------------|",
        ]
    )

    for mapping in sorted(test_mappings, key=lambda m: m.source)[:30]:
        tests_str = ", ".join(f"`{Path(t).name}`" for t in mapping.tests[:2])
        if len(mapping.tests) > 2:
            tests_str += f" (+{len(mapping.tests) - 2})"
        source_name = Path(mapping.source).name
        lines.append(f"| `{source_name}` | {tests_str} | {mapping.coverage_area} |")

    if len(test_mappings) > 30:
        lines.append(f"| ... | ({len(test_mappings) - 30} more mappings) | ... |")

    lines.append("")

    # Schema Files
    lines.extend(
        [
            "---",
            "",
            "## Database Schema",
            "",
            "| File | Purpose |",
            "|------|---------|",
        ]
    )

    for schema in schema_files:
        lines.append(f"| `{schema['name']}` | {schema['purpose']} |")

    lines.append("")

    # HCA Violations (Baseline)
    lines.extend(
        [
            "---",
            "",
            "## Known HCA Violations (Technical Debt Baseline)",
            "",
            f"Established: {today}",
            "",
        ]
    )

    if baseline_violations:
        lines.extend(
            [
                "| File | Violation | Detail |",
                "|------|-----------|--------|",
            ]
        )
        for v in baseline_violations[:20]:
            lines.append(f"| `{v['file']}` | {v['violation_type']} | {v['detail'][:50]}... |")
        if len(baseline_violations) > 20:
            lines.append(f"| ... | {len(baseline_violations) - 20} more violations | See JSON for full list |")
    else:
        lines.append("✅ No HCA violations detected.")

    lines.append("")

    # Search patterns
    lines.extend(
        [
            "---",
            "",
            "## Search Patterns",
            "",
            "| Topic | Search Terms |",
            "|-------|--------------|",
            "| Authentication | `AuthRepository`, `hash_password`, `verify_password`, `SessionManager` |",
            "| RBAC | `permissions.py`, `check_permission`, `UserRole`, `require_permission` |",
            "| Job Creation | `JobRepository.create`, `submit_job`, `_enqueue_job` |",
            "| Job Processing | `run_poll_loop`, `_execute_job`, `WorkerJobExecutor` |",
            "| S3 Download | `download_backup`, `S3Client`, `discover_latest_backup` |",
            "| myloader | `run_myloader`, `build_myloader_command`, `MyLoaderSpec` |",
            "| Staging | `generate_staging_name`, `cleanup_orphaned_staging`, `StagingResult` |",
            "| Atomic Rename | `atomic_rename_staging_to_target`, `AtomicRenameSpec` |",
            "| Simulation | `MockJobRepository`, `SimulationEngine`, `ScenarioRunner` |",
            "| Web UI | `router_registry`, `dependencies.py`, `templates/` |",
            "",
            "---",
            "",
            "## Key Invariants",
            "",
            "1. MySQL is the only coordinator",
            "2. Per-target exclusivity (one restore per database at a time)",
            "3. Download per job (no archive reuse)",
            "4. Staging prefix: `stg_`",
            "5. Service-specific MySQL users (api, worker, loader)",
            "6. Fail hard - never silent degradation",
            "7. Post-SQL lexicographic ordering",
            "8. Atomic rename via stored procedure",
            "9. HCA layer isolation (import only from same or lower layers)",
            "",
            "---",
            "",
            f"*Generated by `scripts/generate_workspace_index.py` on {today}*",
            "",
            "**Remember to update the README.md badge when regenerating!**",
            f"Badge date: `{today}`",
        ]
    )

    return "\n".join(lines)


def generate_json(
    modules: list[ModuleInfo],
    test_files: list[str],
    test_mappings: list[TestMapping],
    violations: list[HCAViolation],
    baseline_violations: list[dict[str, Any]],
    schema_files: list[dict[str, str]],
    scripts: dict[str, list[str]],
) -> dict[str, Any]:
    """Generate WORKSPACE-INDEX.json content."""
    today = datetime.now().strftime("%Y-%m-%d")

    src_count = len([m for m in modules if "tests" not in m.path])
    test_count = len(test_files)

    # Build packages structure
    packages: dict[str, Any] = {}
    for mod in modules:
        if "tests" in mod.path:
            continue

        parts = mod.path.split("/")
        if len(parts) < 2:
            continue

        pkg = parts[1]
        if pkg not in packages:
            packages[pkg] = {}

        # Determine subpackage
        if len(parts) >= 4:
            sub_pkg = parts[2]
            if sub_pkg not in packages[pkg]:
                packages[pkg][sub_pkg] = {}
            target = packages[pkg][sub_pkg]
        else:
            target = packages[pkg]

        filename = Path(mod.path).name
        target[filename] = {
            "layer": mod.hca_layer,
            "classes": [c.name for c in mod.classes],
            "functions": [f.name for f in mod.functions],
        }
        if mod.endpoints:
            target[filename]["endpoints"] = mod.endpoints
        if mod.protocols:
            target[filename]["protocols"] = mod.protocols

    # Build HCA layers structure
    hca_layers: dict[str, list[str]] = {layer: [] for layer in LAYER_ORDER}
    for mod in modules:
        if mod.hca_layer in hca_layers:
            hca_layers[mod.hca_layer].append(mod.path)

    # Build test mapping
    test_mapping: dict[str, list[str]] = {}
    for mapping in test_mappings:
        test_mapping[mapping.source] = mapping.tests

    # Build search index
    search_index: dict[str, dict[str, str]] = {"classes": {}, "functions": {}, "protocols": {}}
    for mod in modules:
        for cls in mod.classes:
            search_index["classes"][cls.name] = mod.path
            if cls.is_protocol:
                search_index["protocols"][cls.name] = mod.path
        for func in mod.functions:
            search_index["functions"][func.name] = mod.path

    return {
        "meta": {
            "version": "2.0.0",
            "generated": today,
            "file_count": src_count,
            "test_count": test_count,
            "purpose": "Atomic-level workspace index for AI model searching",
        },
        "architecture": {
            "pattern": "CLI → API → MySQL Queue ← Worker → S3/myloader",
            "services": ["api", "worker", "web"],
            "database": "pulldb_service",
            "coordinator": "mysql_only",
        },
        "hca_layers": hca_layers,
        "packages": packages,
        "schema": {
            "database": "pulldb_service",
            "path": "schema/pulldb_service/",
            "files": schema_files,
        },
        "scripts": scripts,
        "test_mapping": test_mapping,
        "search_index": search_index,
        "search_patterns": {
            "authentication": ["AuthRepository", "hash_password", "verify_password", "SessionManager"],
            "rbac": ["permissions.py", "check_permission", "UserRole", "require_permission"],
            "job_creation": ["JobRepository.create", "submit_job", "_enqueue_job"],
            "job_processing": ["run_poll_loop", "_execute_job", "WorkerJobExecutor"],
            "s3_download": ["download_backup", "S3Client", "discover_latest_backup"],
            "myloader": ["run_myloader", "build_myloader_command", "MyLoaderSpec"],
            "staging": ["generate_staging_name", "cleanup_orphaned_staging", "StagingResult"],
            "atomic_rename": ["atomic_rename_staging_to_target", "AtomicRenameSpec"],
            "simulation": ["MockJobRepository", "SimulationEngine", "ScenarioRunner"],
            "web_ui": ["router_registry", "dependencies.py", "templates/"],
        },
        "hca_violations": [
            {"file": v.file, "violation_type": v.violation_type, "detail": v.detail, "from_layer": v.from_layer, "to_layer": v.to_layer}
            for v in violations
        ],
        "hca_violation_baseline": baseline_violations,
        "invariants": [
            "MySQL is the only coordinator",
            "Per-target exclusivity",
            "Download per job (no reuse)",
            "Staging prefix: stg_",
            "Service-specific MySQL users",
            "Fail hard - never silent degradation",
            "Post-SQL lexicographic ordering",
            "Atomic rename via stored procedure",
            "HCA layer isolation",
        ],
        "versions": {
            "python": "3.12+",
            "mydumper": ["0.9.5", "0.19.3-3"],
            "mysql": "8.0+",
            "fastapi": "0.100+",
            "pydantic": "2.0+",
        },
    }


# ---------------------------------------------------------------------------
# Main Entry Points
# ---------------------------------------------------------------------------


def load_baseline_violations() -> list[dict[str, Any]]:
    """Load existing baseline violations from JSON file."""
    if OUTPUT_JSON.exists():
        try:
            with open(OUTPUT_JSON, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("hca_violation_baseline", [])
        except (json.JSONDecodeError, KeyError):
            pass
    return []


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate pullDB workspace index")
    parser.add_argument("--check", action="store_true", help="Check for drift (CI mode)")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument("--set-baseline", action="store_true", help="Set current violations as baseline")
    args = parser.parse_args()

    print("🔍 Scanning pullDB codebase...", file=sys.stderr)

    # Find and parse all Python files
    python_files = find_python_files(PULLDB_SRC)
    modules: list[ModuleInfo] = []

    for file_path in python_files:
        rel_path = str(file_path.relative_to(PROJECT_ROOT))
        module_info = parse_module(file_path, rel_path)
        if module_info:
            modules.append(module_info)

    print(f"   Parsed {len(modules)} Python modules", file=sys.stderr)

    # Find test files
    test_files = find_test_files()
    print(f"   Found {len(test_files)} test files", file=sys.stderr)

    # Build test mappings
    test_mappings = build_test_mapping(modules, test_files)
    print(f"   Built {len(test_mappings)} test mappings", file=sys.stderr)

    # Check HCA violations
    violations = check_hca_violations(modules)
    print(f"   Found {len(violations)} HCA violations", file=sys.stderr)

    # Load or set baseline
    if args.set_baseline:
        baseline_violations = [
            {"file": v.file, "violation_type": v.violation_type, "detail": v.detail, "from_layer": v.from_layer, "to_layer": v.to_layer}
            for v in violations
        ]
        print(f"   Setting {len(baseline_violations)} violations as baseline", file=sys.stderr)
    else:
        baseline_violations = load_baseline_violations()

    # Find schema and scripts
    schema_files = find_schema_files()
    scripts = find_script_files()

    # Generate outputs
    md_content = generate_markdown(modules, test_files, test_mappings, violations, baseline_violations, schema_files, scripts)

    json_content = generate_json(modules, test_files, test_mappings, violations, baseline_violations, schema_files, scripts)

    if args.check:
        # Check mode: compare with existing files
        changes_detected = False

        if OUTPUT_JSON.exists():
            with open(OUTPUT_JSON, encoding="utf-8") as f:
                existing_json = json.load(f)

            # Compare file counts (simple drift detection)
            existing_count = existing_json.get("meta", {}).get("file_count", 0)
            new_count = json_content["meta"]["file_count"]

            if existing_count != new_count:
                print(f"⚠️  File count changed: {existing_count} → {new_count}", file=sys.stderr)
                changes_detected = True

            # Check for new violations
            existing_violations = set(v.get("file", "") for v in existing_json.get("hca_violations", []))
            new_violations = set(v["file"] for v in json_content["hca_violations"])
            brand_new = new_violations - existing_violations

            if brand_new:
                print(f"⚠️  {len(brand_new)} new HCA violations detected:", file=sys.stderr)
                for f in sorted(brand_new)[:5]:
                    print(f"     - {f}", file=sys.stderr)
                changes_detected = True

        else:
            print("⚠️  WORKSPACE-INDEX.json does not exist", file=sys.stderr)
            changes_detected = True

        if changes_detected:
            print("\n💡 Run 'python scripts/generate_workspace_index.py' to regenerate indexes", file=sys.stderr)
            return 0  # Advisory only, don't fail CI
        else:
            print("✅ Workspace index is up to date", file=sys.stderr)
            return 0

    elif args.json:
        # JSON only mode
        print(json.dumps(json_content, indent=2))
        return 0

    else:
        # Generate mode
        print(f"\n📝 Writing {OUTPUT_MD}...", file=sys.stderr)
        with open(OUTPUT_MD, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"📝 Writing {OUTPUT_JSON}...", file=sys.stderr)
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(json_content, f, indent=2)
            f.write("\n")

        today = datetime.now().strftime("%Y-%m-%d")
        print(f"\n✅ Index generation complete!", file=sys.stderr)
        print(f"\n🏷️  Remember to update README.md badge:", file=sys.stderr)
        print(f"   ![Index Updated](https://img.shields.io/badge/Index%20Updated-{today}-blue)", file=sys.stderr)

        return 0


if __name__ == "__main__":
    sys.exit(main())
