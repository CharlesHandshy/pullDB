# 01 — Executive Summary

---

## The Problem

pullDB's web interface has fragmented into an inconsistent state:

| Issue | Severity | Details |
|-------|----------|---------|
| Two parallel template systems | High | Root-level AND `features/` templates |
| **10,193 lines** inline CSS | High | Spread across 36 `<style>` blocks |
| **101 inline SVG** icons | Medium | No reusability, scattered everywhere |
| Bootstrap 5 dependency | Medium | Only in login.html, causes conflicts |
| No dark mode | Medium | User preference ignored |
| QA Template missing | **Critical** | `features/restore/` lacks QA Template! |

---

## The Solution

Transform into a unified, HCA-compliant design system:

1. **Icon macro system** — 101 icons organized by HCA layer
2. **Dark mode** — CSS variables with `[data-theme="dark"]`
3. **Admin-configurable themes** — Global settings, generated CSS endpoint
4. **Consolidated templates** — Everything under `features/{feature}/`
5. **Zero Bootstrap** — Pure design-system CSS
6. **QA Template parity** — Port missing functionality

---

## Critical Gaps Discovered

### Gap 1: Icon Count Underestimated
- **Original estimate**: 45 icons
- **Actual**: **101 unique icons**, 354 instances
- **Action**: 40 "unknown" icons need manual categorization in PR 0

### Gap 2: Inline CSS Massively Underestimated
- **Original estimate**: ~600 lines
- **Actual**: **10,193 lines** across 36 blocks
- **Top offenders**:
  - `admin/hosts.html`: 1,109 lines
  - `dashboard.html`: 590 lines
  - `admin/settings.html`: 573 lines

### Gap 3: QA Template Feature Missing
- Root `restore.html` has full QA Template support
- `features/restore/restore.html` has **ZERO** QA Template code
- **Action**: PR 5 must port this functionality (not just move files)

---

## Scope

| Metric | Value |
|--------|-------|
| PRs | 14 |
| Estimated Hours | 45-55 |
| Files to Move | ~30 templates |
| CSS to Extract | 10,193 lines |
| Icons to Convert | 354 instances → macros |
| Templates to Delete | ~15 duplicates |
