# GUI Migration Project

> **Status**: Planning Complete  
> **Created**: 2025-12-15  
> **Scope**: 14 PRs, 45-55 hours estimated effort  
> **Goal**: Unified HCA-compliant GUI with icon system, dark mode, and admin-configurable themes

---

## Quick Start for New Chat

**Read these files IN ORDER before starting work:**

1. `00-CONTEXT.md` — What to load before any work
2. `01-EXECUTIVE-SUMMARY.md` — Problem, solution, scope
3. `02-ARCHITECTURE.md` — Decisions already made
4. `03-PR-BREAKDOWN.md` — All 14 PRs with dependencies
5. `04-IMPLEMENTATION.md` — Step-by-step instructions per PR
6. `05-TESTING.md` — How to validate each PR
7. `06-TROUBLESHOOTING.md` — Common issues and fixes
8. `appendix/` — Code samples, icon inventory, CSS mappings

---

## Directory Structure (HCA-Organized)

```
.pulldb/gui-migration/
├── README.md                    # This file - entry point
├── 00-CONTEXT.md               # Context loading instructions
├── 01-EXECUTIVE-SUMMARY.md     # Problem + solution overview
├── 02-ARCHITECTURE.md          # Architecture decisions
├── 03-PR-BREAKDOWN.md          # PR list with dependencies
├── 04-IMPLEMENTATION.md        # Step-by-step per PR
├── 05-TESTING.md               # Testing protocol
├── 06-TROUBLESHOOTING.md       # Common issues
└── appendix/
    ├── A-theme-endpoint.md     # Generated CSS endpoint code
    ├── B-icon-macros.md        # Icon macro implementation
    ├── C-icon-inventory.md     # All 101 icons by HCA layer
    ├── D-dark-mode-colors.md   # Color mapping tables
    └── E-template-structure.md # Target file structure
```

---

## Critical Reminders

1. **FAIL HARD**: Never silently degrade. If something breaks, stop and report.
2. **HCA Compliance**: All templates MUST be under `features/{feature}/`
3. **Session Logging**: Log significant work to `.pulldb/SESSION-LOG.md`
4. **QA Template**: PR 5 MUST port QA Template functionality (critical gap!)

---

## Effort Summary

| Phase | PRs | Effort |
|-------|-----|--------|
| Tooling | PR 0 | 2-4 hours |
| Foundation | PR 1 | 6-8 hours |
| Features | PR 2-6, 10 | 18-22 hours |
| Admin | PR 7-9 | 12-17 hours |
| Polish | PR 11-13 | 5-8 hours |
| **Total** | **14 PRs** | **45-55 hours** |
