# Release Notes - v0.0.10

**Release Date**: 2025-12-15  
**Type**: Pre-GUI Migration Baseline

---

## Purpose

This release establishes a **stable rollback point** before beginning the GUI migration project. If the GUI migration encounters issues, this tagged release provides a known-good state to return to.

## Version Jump Explanation

Versions **0.0.8** and **0.0.9** were internal development iterations that were never formally released to production. This release (v0.0.10) consolidates all development work since v0.0.7 into a stable baseline.

---

## What's Included

### GUI Migration Planning (`.pulldb/gui-migration/`)

A comprehensive 14-PR migration plan with 45-55 hours estimated effort:

| Document | Description |
|----------|-------------|
| `README.md` | Entry point and quick start |
| `00-CONTEXT.md` | Context loading instructions for AI agents |
| `01-EXECUTIVE-SUMMARY.md` | Problem statement, solution, critical gaps |
| `02-ARCHITECTURE.md` | Finalized architecture decisions |
| `03-PR-BREAKDOWN.md` | All 14 PRs with dependency graph |
| `04-IMPLEMENTATION.md` | Step-by-step instructions per PR |
| `05-TESTING.md` | Testing protocol and checklists |
| `06-TROUBLESHOOTING.md` | Common issues and rollback procedures |
| `appendix/` | Code samples, icon inventory, color mappings |

**Key Findings from Audit**:
- 101 unique icons (not 45 estimated) across 354 instances
- 10,193 lines inline CSS (not 600 estimated) across 36 blocks
- QA Template feature completely missing from `features/restore/restore.html`

### Audit Scripts (`scripts/`)

| Script | Purpose |
|--------|---------|
| `audit_inline_svgs.py` | Find all inline SVGs, categorize by HCA layer |
| `audit_inline_css.py` | Find `<style>` blocks, prioritize extraction |
| `validate_template_paths.py` | Enforce HCA-compliant template paths |

### E2E Tests in CI

- Added `playwright` and `pytest-playwright` to `requirements-test.txt`
- Release workflow now runs E2E tests with Playwright + Chromium
- Tests use simulation mode (`PULLDB_MODE=SIMULATION`) for isolation

### Infrastructure Updates

- MySQL user separation documentation in `.pulldb/extensions/`
- Debian packages synced to v0.0.10

---

## Upgrade Instructions

Standard package upgrade:

```bash
# For .deb installations
sudo apt update
sudo apt install --only-upgrade pulldb

# For development
git fetch --tags
git checkout v0.0.10
pip install -e .
```

---

## Rollback Instructions

If needed during GUI migration:

```bash
git checkout v0.0.10
pip install -e .
# Restart services as needed
```

---

## Next Steps

After this release, GUI migration work begins with:
1. **PR 0**: Tooling verification and icon categorization
2. **PR 1**: Foundation (icons + CSS + accessibility)
3. **PRs 2-6, 10**: Feature migrations (parallelizable)
4. **PRs 7-9**: Admin suite
5. **PRs 11-13**: Polish and documentation

See `.pulldb/gui-migration/README.md` for full details.
