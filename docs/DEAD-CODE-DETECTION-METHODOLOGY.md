# Dead Code Detection Methodology for pullDB

> **RIGOROUS** - Designed for 100% confidence in dead code identification

## The Fundamental Truth

**There is ONLY ONE way to be 100% certain code is dead:**

1. Remove it
2. Run the full test suite (unit + integration + e2e)
3. Run the application in all modes (CLI, API, Web, Worker)
4. Verify all documented features still work
5. Check for runtime errors in production-like environment

Everything else is **heuristics with false positive risks**.

---

## Phase 1: Identify ALL Entry Points

### 1.1 Primary Entry Points (MUST trace from these)

```
┌─────────────────────────────────────────────────────────────────────┐
│ ENTRY POINT TYPE      │ FILE/PATTERN                   │ TRACES TO │
├───────────────────────┼────────────────────────────────┼───────────┤
│ CLI Main              │ pulldb/cli/main.py             │ All CLI   │
│ API Main              │ pulldb/api/__init__.py         │ All API   │
│ Web Router Registry   │ pulldb/web/router_registry.py  │ All Web   │
│ Worker Service        │ pulldb/worker/service.py       │ All Jobs  │
│ Worker Loop           │ pulldb/worker/loop.py          │ All Exec  │
│ Test Files            │ tests/**/*.py                  │ Test-only │
│ Scripts               │ scripts/*.py                   │ One-off   │
│ Audit Module          │ pulldb/audit/__main__.py       │ Audit CLI │
└───────────────────────┴────────────────────────────────┴───────────┘
```

### 1.2 Secondary Entry Points (Framework-wired)

| Pattern | Framework | How Wired | Cannot be "unused" |
|---------|-----------|-----------|-------------------|
| `@router.get("/path")` | FastAPI | HTTP routing | Reachable via HTTP |
| `@router.post("/path")` | FastAPI | HTTP routing | Reachable via HTTP |
| `@click.command()` | Click | CLI subcommands | Reachable via CLI |
| `@app.command()` | Typer | CLI subcommands | Reachable via CLI |
| `{{ function() }}` | Jinja2 | Template calls | Reachable via render |
| `hx-get="/path"` | HTMX | Frontend calls | Reachable via JS |
| `__all__ = [...]` | Python | Public API | Intentional export |

### 1.3 Hidden Entry Points (Easy to Miss)

```python
# These are NOT dead even if no Python imports them:

# 1. Jinja2 template functions (called from HTML)
#    Check: templates/**/*.html for {{ function_name() }}

# 2. JavaScript fetch calls
#    Check: static/**/*.js for fetch("/api/...", "/web/...")

# 3. HTMX attributes
#    Check: templates/**/*.html for hx-get, hx-post, hx-delete

# 4. CSS class references (for utility functions that generate classes)
#    Check: static/**/*.css, templates/**/*.html

# 5. Configuration-driven loading
#    Check: config files for class/function names as strings

# 6. Pickle/JSON serialization (classes instantiated from saved data)
#    Check: Any persistence layer
```

---

## Phase 2: Static Analysis Tools

### 2.1 Tool Stack (In Order of Reliability)

| Tool | What It Finds | False Positive Risk | Use For |
|------|---------------|---------------------|---------|
| **vulture** | Unused code | MEDIUM (misses dynamic) | First pass |
| **pylance** | Unused imports | HIGH (misses re-exports) | IDE hints only |
| **dead** | Dead code | MEDIUM | Second opinion |
| **custom grep** | String references | LOW | Dynamic dispatch |
| **coverage.py** | Unexecuted code | LOW (if tests are good) | Runtime verification |

### 2.2 Vulture Configuration

```bash
# Install
pip install vulture

# Create whitelist for known false positives
cat > .vulture_whitelist.py << 'EOF'
# FastAPI route handlers (decorated, not called directly)
# These are wired by decorators, not Python imports

# Jinja2 template globals
# Added to app.jinja_env.globals

# Click/Typer commands
# Wired by decorator

# __all__ exports (intentional public API)

# Test fixtures (used by pytest magic)

# Pydantic validators (called by framework)
EOF

# Run with whitelist
vulture pulldb/ --min-confidence 80 --exclude "**/tests/**,**/_archived/**"
```

### 2.3 Coverage-Based Dead Code Detection

```bash
# Run ALL tests with coverage
pytest --cov=pulldb --cov-report=html --cov-report=json tests/

# Find files with 0% coverage (potential dead modules)
python -c "
import json
with open('coverage.json') as f:
    data = json.load(f)
for file, stats in data['files'].items():
    if stats['summary']['percent_covered'] == 0:
        print(f'ZERO COVERAGE: {file}')
    elif stats['summary']['percent_covered'] < 10:
        print(f'LOW COVERAGE ({stats[\"summary\"][\"percent_covered\"]:.0f}%): {file}')
"
```

---

## Phase 3: The Rigorous Detection Algorithm

### 3.1 Decision Tree

```
                        ┌─────────────────────────┐
                        │ Is symbol in __all__?   │
                        └───────────┬─────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │ YES                           │ NO
                    ▼                               ▼
        ┌───────────────────────┐     ┌─────────────────────────┐
        │ INTENTIONAL PUBLIC API│     │ Check static imports    │
        │ NOT DEAD (by design)  │     └───────────┬─────────────┘
        └───────────────────────┘                 │
                                    ┌─────────────┴─────────────┐
                                    │ IMPORTED                  │ NOT IMPORTED
                                    ▼                           ▼
                        ┌───────────────────────┐ ┌─────────────────────────┐
                        │ Check if USED after   │ │ Check dynamic patterns  │
                        │ import (not just      │ │ getattr, globals, etc.  │
                        │ re-exported)          │ └───────────┬─────────────┘
                        └───────────┬───────────┘             │
                                    │             ┌───────────┴───────────┐
                    ┌───────────────┴───────────┐ │ FOUND                 │ NOT FOUND
                    │ USED          │ NOT USED  │ ▼                       ▼
                    ▼               ▼           │ ┌───────────────┐ ┌─────────────┐
            ┌───────────┐   ┌───────────────┐   │ │ MAYBE USED    │ │ Check       │
            │ NOT DEAD  │   │ Check if      │   │ │ dynamically   │ │ templates   │
            └───────────┘   │ re-export for │   │ │ VERIFY MANUALLY│ │ & JS        │
                            │ __init__.py   │   │ └───────────────┘ └──────┬──────┘
                            └───────┬───────┘   │                          │
                                    │           │          ┌───────────────┴───────────┐
                    ┌───────────────┴───────┐   │          │ FOUND                     │ NOT FOUND
                    │ IS RE-EXPORT          │ NO│          ▼                           ▼
                    ▼                       ▼   │  ┌───────────────┐       ┌───────────────────┐
            ┌───────────────┐   ┌───────────────┐  │ USED BY       │       │ CANDIDATE DEAD    │
            │ INTENTIONAL   │   │ LIKELY DEAD   │  │ FRONTEND      │       │ REMOVE & TEST     │
            │ PUBLIC API    │   │ VERIFY BY     │  │ NOT DEAD      │       └───────────────────┘
            └───────────────┘   │ REMOVAL       │  └───────────────┘
                                └───────────────┘
```

### 3.2 Automated Detection Script

```python
#!/usr/bin/env python3
"""Dead code detector for pullDB with dynamic dispatch awareness."""

import ast
import re
from pathlib import Path
from typing import Set, Dict, List
from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str
    file: Path
    line: int
    kind: str  # 'function', 'class', 'variable'
    is_exported: bool = False  # In __all__
    is_decorated: bool = False  # Has decorators
    static_refs: Set[str] = field(default_factory=set)
    dynamic_refs: Set[str] = field(default_factory=set)
    template_refs: Set[str] = field(default_factory=set)
    js_refs: Set[str] = field(default_factory=set)


class DeadCodeDetector:
    """Multi-pass dead code detection with dynamic dispatch awareness."""
    
    def __init__(self, root: Path):
        self.root = root
        self.symbols: Dict[str, Symbol] = {}
        self.entry_points: Set[str] = set()
        self.false_positive_patterns = [
            r"^test_",  # Test functions
            r"^Test",   # Test classes
            r"^fixture_",  # Pytest fixtures
            r"^__",     # Dunder methods
        ]
    
    def analyze(self) -> List[Symbol]:
        """Run full analysis pipeline."""
        # Pass 1: Collect all defined symbols
        self._collect_symbols()
        
        # Pass 2: Find static references
        self._find_static_refs()
        
        # Pass 3: Find dynamic references (getattr, globals, etc.)
        self._find_dynamic_refs()
        
        # Pass 4: Find template references
        self._find_template_refs()
        
        # Pass 5: Find JavaScript references
        self._find_js_refs()
        
        # Pass 6: Identify entry points
        self._identify_entry_points()
        
        # Pass 7: Build reachability graph from entry points
        reachable = self._compute_reachable()
        
        # Pass 8: Filter candidates
        candidates = []
        for name, sym in self.symbols.items():
            if name in reachable:
                continue
            if sym.is_exported:
                continue  # Intentional public API
            if sym.is_decorated:
                continue  # Framework-wired (routes, commands)
            if any(re.match(p, sym.name) for p in self.false_positive_patterns):
                continue
            if sym.dynamic_refs or sym.template_refs or sym.js_refs:
                continue  # Has non-static references
            candidates.append(sym)
        
        return sorted(candidates, key=lambda s: (s.file, s.line))
    
    def _collect_symbols(self):
        """Collect all function/class definitions."""
        for py_file in self.root.rglob("*.py"):
            if "_archived" in str(py_file) or "__pycache__" in str(py_file):
                continue
            try:
                tree = ast.parse(py_file.read_text())
            except SyntaxError:
                continue
            
            # Check for __all__
            exports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "__all__":
                            if isinstance(node.value, ast.List):
                                exports = {
                                    elt.s for elt in node.value.elts
                                    if isinstance(elt, ast.Constant)
                                }
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sym = Symbol(
                        name=node.name,
                        file=py_file,
                        line=node.lineno,
                        kind="function",
                        is_exported=node.name in exports,
                        is_decorated=bool(node.decorator_list),
                    )
                    self.symbols[f"{py_file}:{node.name}"] = sym
                elif isinstance(node, ast.ClassDef):
                    sym = Symbol(
                        name=node.name,
                        file=py_file,
                        line=node.lineno,
                        kind="class",
                        is_exported=node.name in exports,
                        is_decorated=bool(node.decorator_list),
                    )
                    self.symbols[f"{py_file}:{node.name}"] = sym
    
    # ... additional methods for each pass
```

---

## Phase 4: Manual Verification Protocol

### 4.1 Before Declaring Dead

For EACH candidate identified by automated tools:

```
□ 1. GREP CHECK: Search entire codebase for the symbol name
     grep -r "symbol_name" --include="*.py" --include="*.html" --include="*.js"
     
□ 2. TEMPLATE CHECK: Search Jinja2 templates
     grep -r "symbol_name" pulldb/web/templates/
     
□ 3. JAVASCRIPT CHECK: Search JS files
     grep -r "symbol_name" pulldb/web/static/
     
□ 4. STRING CHECK: Search for string-based references
     grep -r "'symbol_name'\|\"symbol_name\"" pulldb/
     
□ 5. DYNAMIC CHECK: Search for getattr patterns that could load it
     grep -r "getattr.*symbol\|globals.*symbol" pulldb/
     
□ 6. IMPORT CHECK: Verify no __init__.py re-exports it
     grep -r "from.*import.*symbol_name" pulldb/**/__init__.py
     
□ 7. TEST CHECK: Is it ONLY used in tests? That might be intentional.
     
□ 8. DOCUMENTATION CHECK: Is it referenced in docs as public API?
     grep -r "symbol_name" docs/
```

### 4.2 The Removal Test (Gold Standard)

```bash
#!/bin/bash
# safe_removal_test.sh - The ONLY 100% certain method

SYMBOL_FILE="$1"
BACKUP_DIR=".dead_code_backup_$(date +%s)"

echo "=== DEAD CODE REMOVAL TEST ==="
echo "Testing removal of: $SYMBOL_FILE"

# 1. Create backup
mkdir -p "$BACKUP_DIR"
cp "$SYMBOL_FILE" "$BACKUP_DIR/"

# 2. Remove the code (or comment it out)
# ... manual step or script

# 3. Run static checks
echo "Running static checks..."
python -m py_compile pulldb/**/*.py || { echo "SYNTAX ERROR"; exit 1; }

# 4. Run type checker
echo "Running type checker..."
mypy pulldb/ --ignore-missing-imports || { echo "TYPE ERROR"; exit 1; }

# 5. Run unit tests
echo "Running unit tests..."
pytest tests/unit/ -x || { echo "UNIT TEST FAILED"; exit 1; }

# 6. Run integration tests
echo "Running integration tests..."
pytest tests/integration/ -x || { echo "INTEGRATION TEST FAILED"; exit 1; }

# 7. Start services and verify
echo "Starting services..."
# ... start CLI, API, Web, Worker
# ... run smoke tests

# 8. If all pass, code was dead
echo "✓ All tests passed - code is confirmed dead"
```

---

## Phase 5: pullDB-Specific Checks

### 5.1 FastAPI Route Check

```python
# All routes must be reachable from router_registry.py
# Check: Every @router.* decorated function should be included

from pulldb.web.router_registry import main_router

def list_all_routes(router, prefix=""):
    """List all registered routes."""
    routes = []
    for route in router.routes:
        if hasattr(route, 'path'):
            routes.append(f"{prefix}{route.path} -> {route.endpoint.__name__}")
        if hasattr(route, 'routes'):
            routes.extend(list_all_routes(route, prefix + getattr(route, 'path', '')))
    return routes

# Compare against grep of all @router.* decorators
```

### 5.2 Jinja2 Template Function Check

```python
# All functions added to jinja_env.globals must be used in templates
# Check: grep templates for each global

import subprocess

def check_template_globals():
    """Find unused Jinja2 globals."""
    # 1. Find all registered globals (from dependencies.py or similar)
    # 2. For each global, grep templates
    # 3. Report any not found in templates
    pass
```

### 5.3 Worker Service Check

```python
# Worker phases must all be reachable from service.py/loop.py
# Check: Each phase function in worker/ should be called
```

### 5.4 CLI Command Check

```python
# All @click.command() functions must be added to a group
# Check: Each command decorator should have corresponding add_command()
```

---

## Phase 6: Confidence Levels

### Classification System

| Confidence | Criteria | Action |
|------------|----------|--------|
| **100% DEAD** | Removed, all tests pass, manual verification done | Delete permanently |
| **99% DEAD** | No static refs, no dynamic refs, no template refs, no JS refs | Safe to remove with monitoring |
| **90% DEAD** | No static refs, but has potential dynamic patterns nearby | Review manually, then remove |
| **70% DEAD** | Only imported but never called | Could be public API, ask maintainer |
| **50% MAYBE** | Complex dynamic dispatch, unclear | Do NOT remove without deep analysis |
| **KEEP** | In `__all__`, decorated, or documented API | Not dead, intentional |

---

## Phase 7: Automated CI Check

```yaml
# .github/workflows/dead-code-check.yml
name: Dead Code Detection

on:
  pull_request:
  schedule:
    - cron: '0 0 * * 0'  # Weekly

jobs:
  dead-code:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Install tools
        run: pip install vulture coverage
      
      - name: Run vulture
        run: |
          vulture pulldb/ --min-confidence 90 \
            --exclude "**/tests/**,**/_archived/**" \
            > vulture_report.txt || true
          
          if [ -s vulture_report.txt ]; then
            echo "::warning::Potential dead code found"
            cat vulture_report.txt
          fi
      
      - name: Coverage check
        run: |
          pytest --cov=pulldb --cov-report=json tests/
          python scripts/check_zero_coverage.py
```

---

## Quick Reference: Safe vs Unsafe to Remove

### ✅ SAFE to Remove (High Confidence)

- Private functions (`_helper()`) with zero references
- Classes never instantiated and not in `__all__`
- Import statements that import unused symbols
- Commented-out code (unless marked `# TODO: restore for feature X`)
- Duplicate implementations (verify which is actually used)

### ⚠️ VERIFY Before Removing

- Functions only called from tests (might be test utilities)
- Classes that could be instantiated via string-based factory
- Anything with `# noqa` or `# type: ignore` - might indicate intentional patterns
- Code in `__init__.py` files (often re-exports)
- Decorated functions (framework might wire them)

### ❌ DO NOT Remove Without Deep Analysis

- Anything in `__all__`
- Anything with `@router.*`, `@app.*`, `@click.*` decorators
- Anything referenced in config files
- Anything referenced in Jinja2 templates
- Anything referenced in JavaScript/CSS
- Anything with `getattr()` patterns nearby
- Pydantic validators (`@validator`, `@field_validator`)
- SQLAlchemy event listeners
- Signal handlers

---

## Summary: The 100% Confidence Process

```
1. RUN AUTOMATED TOOLS (vulture, coverage)
         ↓
2. FILTER FALSE POSITIVES (decorators, __all__, dynamic)
         ↓
3. MANUAL VERIFICATION (grep all references)
         ↓
4. REMOVAL TEST (delete + run full test suite)
         ↓
5. MONITOR PRODUCTION (if applicable)
         ↓
6. CONFIRMED DEAD → DELETE PERMANENTLY
```

**Remember**: The only way to be 100% certain is to remove the code and verify nothing breaks. Everything else is probability estimation.
