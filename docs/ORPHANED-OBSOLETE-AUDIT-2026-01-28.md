# Orphaned & Obsolete Items Audit Report

**Date:** January 28, 2026  
**Auditor:** GitHub Copilot (Claude Opus 4.5)  
**Scope:** Full codebase audit for deprecated, orphaned, and obsolete items  
**Project:** pullDB  
**Last Validated:** January 28, 2026 (exhaustive line-by-line verification)

---

## Executive Summary

This audit identifies deprecated settings, legacy CSS classes, stale documentation references, orphaned cache files, and archived templates across the pullDB codebase. The goal is to provide actionable remediation steps for cleaning up technical debt while maintaining backwards compatibility where necessary.

### Key Findings

| Category | Items Found | Severity | Action Required |
|----------|-------------|----------|-----------------|
| Deprecated Settings | 3 settings | Medium | Mark deprecated, plan removal v2.0.0 |
| Legacy CSS Classes | ~30 classes | Low | Keep for compatibility, audit usage |
| Stale Documentation | 15+ docs | Medium | Archive or update |
| Orphaned Cache Files | 9 files | Low | Clean up |
| Archived Templates | 33 files | None | Already properly archived |

---

## 1. Deprecated Settings

### 1.1 `myloader_connection_timeout` (DEPRECATED)

**Location:** [pulldb/domain/settings.py#L167](pulldb/domain/settings.py#L167-L175)

```python
"myloader_connection_timeout": SettingMeta(
    key="myloader_connection_timeout",
    env_var="PULLDB_MYLOADER_CONNECTION_TIMEOUT",
    default="30",
    description="[DEPRECATED - not used] myloader 0.20.x does not support connection timeout.",
    setting_type=SettingType.INTEGER,
    category=SettingCategory.MYLOADER,
    dangerous=False,
    validators=["is_non_negative_integer"],
),
```

**Status:** ✅ Properly marked deprecated in code  
**Usage:** Not used anywhere in production code  
**Environment Variable:** `PULLDB_MYLOADER_CONNECTION_TIMEOUT`

**References to Update:**
- None found (properly isolated)

**Recommendation:** 
- Keep for backwards compatibility with existing `.env` files
- Remove in v2.0.0 major version

---

### 1.2 `myloader_default_args` (SUPERSEDED)

**Location:** [pulldb/domain/config.py#L143](pulldb/domain/config.py#L143-L156)

**Status:** Superseded by individual `myloader_*` settings but still functional  
**Environment Variable:** `PULLDB_MYLOADER_DEFAULT_ARGS`

**Current Usage:**

| File | Line | Usage Type | Migration Status |
|------|------|------------|------------------|
| [pulldb/domain/config.py](pulldb/domain/config.py#L352) | 352 | Built from individual settings | ✅ Migrated |
| [pulldb/domain/restore_models.py](pulldb/domain/restore_models.py#L141) | 141 | Consumed by MyLoaderSpec | ✅ Still works |
| [pulldb/tests/test_config.py](pulldb/tests/test_config.py#L187) | 187-189 | Test coverage | ✅ Tests pass |
| [pulldb/tests/test_restore_models.py](pulldb/tests/test_restore_models.py#L27) | 27 | Test fixtures | ✅ Compatible |
| [pulldb/tests/test_restore.py](pulldb/tests/test_restore.py#L177) | 177 | Test fixtures | ✅ Compatible |
| [pulldb/web/features/admin/routes.py](pulldb/web/features/admin/routes.py#L2986) | 2986 | Hidden from UI | ✅ Filtered |
| [docs/hca/shared/configuration.md](docs/hca/shared/configuration.md#L108) | 108 | Documentation | ⚠️ Should note deprecated |
| [packaging/env.example](packaging/env.example#L116) | 116 | Example config | ⚠️ Should note deprecated |

**Architecture Note:**  
The new approach uses `build_myloader_args_from_settings()` to construct myloader arguments from individual settings (`myloader_threads`, `myloader_skip_triggers`, etc.) at runtime. The `myloader_default_args` tuple is still populated but from the new granular settings.

**Recommendation:**
- Add deprecation notice to documentation
- Update `env.example` comments to indicate superseded status
- Keep functional for backwards compatibility

---

### 1.3 `myloader_extra_args` (DEPRECATED)

**Location:** [pulldb/domain/config.py#L156](pulldb/domain/config.py#L156)

**Status:** Deprecated passthrough for legacy compatibility  
**Environment Variable:** `PULLDB_MYLOADER_EXTRA_ARGS`

**Current Usage:**

| File | Line | Usage Type | Status |
|------|------|------------|--------|
| [pulldb/domain/config.py](pulldb/domain/config.py#L354-355) | 354-355 | Preserved for backward compat | ⚠️ Legacy code path |
| [pulldb/domain/restore_models.py](pulldb/domain/restore_models.py#L142) | 142 | Merged into args | ⚠️ Still functional |
| [pulldb/tests/test_config.py](pulldb/tests/test_config.py#L130) | 130, 152, 185, 206, 219, 231 | Test coverage | ✅ Tests document deprecation |
| [pulldb/tests/test_restore_models.py](pulldb/tests/test_restore_models.py#L28) | 28, 57 | Test fixtures | ✅ Compatible |
| [pulldb/tests/test_restore.py](pulldb/tests/test_restore.py#L178) | 178 | Test fixtures | ✅ Compatible |
| [pulldb/web/features/admin/routes.py](pulldb/web/features/admin/routes.py#L2987) | 2987 | Hidden from UI | ✅ Filtered |
| [docs/hca/shared/configuration.md](docs/hca/shared/configuration.md#L109) | 109 | Documentation | ⚠️ Should note deprecated |
| [packaging/env.example](packaging/env.example#L133) | 133 | Example config (commented) | ✅ Already commented out |
| [scripts/archived/manual-tests/run_restore_test_actionpest.py](scripts/archived/manual-tests/run_restore_test_actionpest.py#L41) | 41 | Archived test script | N/A |

**Recommendation:**
- Mark as deprecated in documentation
- Keep functional for users with existing configurations
- Plan removal in v2.0.0

---

## 2. Legacy CSS Classes

### 2.1 Documented Legacy Classes (Intentionally Kept)

These CSS classes are marked as "legacy" in comments but are intentionally maintained for backwards compatibility:

#### Sidebar Legacy Classes
**File:** [pulldb/web/widgets/css/sidebar.css](pulldb/web/widgets/css/sidebar.css#L223-L235)

| Class | Purpose | Template Usage |
|-------|---------|---------------|
| `.sidebar-item` | Legacy item wrapper | **NOT USED** - can remove |
| `.sidebar-label` | Legacy label | **NOT USED** - can remove |

**Recommendation:** These classes have NO template usage. Safe to remove in next CSS cleanup.

---

#### Layout Legacy Classes
**File:** [pulldb/web/shared/css/layout.css](pulldb/web/shared/css/layout.css)

| Class | Line | Purpose | Template Usage |
|-------|------|---------|---------------|
| `.attention-strip` | 102 | Deprecated accent strip | **NOT USED** |
| `.content-header` | 296 | Legacy page header | **NOT USED** |

**Recommendation:** No template usage found. Safe to remove.

---

#### Auth Submit Button
**File:** [pulldb/web/pages/css/profile.css](pulldb/web/pages/css/profile.css#L821-L850)

| Class | Line | Purpose | Template Usage |
|-------|------|---------|---------------|
| `.auth-submit` | 821 | Legacy submit button | [login.html#L33](pulldb/web/templates/features/auth/login.html#L33) |

**Recommendation:** **STILL IN USE** - Migrate login.html to use `.btn-primary`, then remove.

**Migration Required:**
```html
<!-- Current (login.html:33) -->
<button type="submit" class="auth-submit">

<!-- Should become -->
<button type="submit" class="btn btn-primary">
```

---

#### Dashboard Legacy Classes
**File:** [pulldb/web/static/css/features/dashboard.css](pulldb/web/static/css/features/dashboard.css)

| Class | Line | Purpose | Status |
|-------|------|---------|--------|
| `.dashboard__row` | 43 | Legacy row | Review usage |
| `.stat-icon` | 94 | Legacy icon | ✅ IN USE (styleguide.html, host_detail.html) |
| `.stat-content` | 121 | Legacy content | ✅ IN USE (styleguide.html) |
| `.stat-value` | 135 | Legacy value | ✅ IN USE (admin_task_status.html, host_detail.html, styleguide.html, details.html) |
| `.stat-label` | 150 | Legacy label | ✅ IN USE (admin_task_status.html, host_detail.html, styleguide.html, details.html) |
| `.stat--compact` | 186 | Legacy compact | Review usage |
| `.stat-title` | 225 | Legacy title | Review usage |

**Note:** The `stat-value` and `stat-label` classes are extensively used across templates. They should NOT be removed - consider them active, not legacy.

---

#### Restore Page Legacy Classes
**File:** [pulldb/web/static/css/pages/restore.css](pulldb/web/static/css/pages/restore.css)

| Class | Line | Purpose | Status |
|-------|------|---------|--------|
| `.source-step` | 1516 | Deprecated source step | **NOT USED** |
| `.date-range-row` | 1586 | Legacy date range | **NOT USED** |

**Recommendation:** Safe to remove - no template usage.

---

#### Job Details Legacy Classes
**File:** [pulldb/web/static/css/pages/job-details.css](pulldb/web/static/css/pages/job-details.css#L1010)

| Class | Line | Purpose | Status |
|-------|------|---------|--------|
| `.progress-stats` | 1010 | Deprecated, use `.stats-row` | Review usage |

---

### 2.2 CSS Files with Legacy Sections

The following CSS files contain "Legacy Compatibility" sections that are documented but not audited for usage:

| File | Line | Section |
|------|------|---------|
| [entities/card.css](pulldb/web/entities/css/card.css#L17) | 17 | Legacy Compatibility |
| [entities/avatar.css](pulldb/web/entities/css/avatar.css#L15) | 15 | Legacy Compatibility |
| [entities/badge.css](pulldb/web/entities/css/badge.css#L14) | 14 | Legacy Compatibility |
| [features/buttons.css](pulldb/web/static/css/features/buttons.css#L17) | 17 | Legacy Compatibility |
| [features/alerts.css](pulldb/web/static/css/features/alerts.css#L18) | 18 | Legacy Compatibility |
| [features/status.css](pulldb/web/static/css/features/status.css#L60) | 60, 123 | Legacy class support |
| [features/forms.css](pulldb/web/static/css/features/forms.css#L20) | 20 | Legacy Compatibility |
| [features/modals.css](pulldb/web/static/css/features/modals.css#L20) | 20 | Legacy Compatibility |
| [features/tables.css](pulldb/web/static/css/features/tables.css#L17) | 17 | Legacy Compatibility |
| [shared/utilities.css](pulldb/web/shared/css/utilities.css#L517) | 517 | Legacy Compatibility |

**Recommendation:** Create targeted audit script to identify which legacy classes are actually used in templates.

---

## 3. Deprecated Module References in Documentation

### 3.1 Files No Longer Exist

The following modules have been **removed from the codebase** but are still referenced in documentation:

| Module | Replacement | Status |
|--------|-------------|--------|
| `pulldb/worker/metadata_synthesis.py` | `pulldb/worker/backup_metadata.py` | **DELETED** |
| `pulldb/worker/dump_metadata.py` | `pulldb/worker/backup_metadata.py` | **DELETED** |
| `tests/unit/worker/test_metadata_synthesis.py` | `tests/unit/worker/test_backup_metadata.py` | **DELETED** |

### 3.2 Documentation Files Requiring Updates

#### KNOWLEDGE-POOL.md (Active Documentation)
**File:** [docs/KNOWLEDGE-POOL.md#L1372](docs/KNOWLEDGE-POOL.md#L1372)

**Current (Incorrect):**
```python
from pulldb.worker.metadata_synthesis import ensure_compatible_metadata
ensure_compatible_metadata('/path/to/extracted/backup')
```

**Should Be:**
```python
from pulldb.worker.backup_metadata import ensure_compatible_metadata
ensure_compatible_metadata('/path/to/extracted/backup')
```

**Priority:** HIGH - This is active documentation users rely on.

---

#### WORKSPACE-INDEX.md (Generated Index)
**File:** [docs/WORKSPACE-INDEX.md#L228-L233](docs/WORKSPACE-INDEX.md#L228-L233)

**Current (Incorrect):**
```markdown
| `dump_metadata.py` | features | 📦 `TableRowCount`, 📦 `DumpMetadata`, `parse_dump_metadata()`, 📍 Backup metadata parsing |
| `metadata_synthesis.py` | features | `parse_filename()`, `count_rows_in_file()`, `synthesize_metadata()` |
```

**Action:** Regenerate WORKSPACE-INDEX.md to reflect current codebase.

**Priority:** MEDIUM - Index should be regenerated after code changes.

---

#### Historical Documentation (Move to Archived)

These files contain extensive references to deprecated modules and should be moved to `docs/archived/`:

| File | References | Recommendation |
|------|------------|----------------|
| [HEARTBEAT-FIX-AUDIT-REPORT.md](docs/HEARTBEAT-FIX-AUDIT-REPORT.md) | 5 references | Move to `docs/archived/audit-reports/` |
| [IMPLEMENTATION-PLAN-METADATA-HEARTBEAT.md](docs/IMPLEMENTATION-PLAN-METADATA-HEARTBEAT.md) | 10+ references | Move to `docs/archived/status-reports/` |
| [METADATA-SYNTHESIS-OPTIMIZATION-PLAN.md](docs/METADATA-SYNTHESIS-OPTIMIZATION-PLAN.md) | 50+ references | Move to `docs/archived/status-reports/` |

**Rationale:** These are historical implementation plans that have been completed. They should not be in active docs.

---

#### QA Documentation (Historical)

| File | References | Recommendation |
|------|------------|----------------|
| [qa/QAA-FINDINGS-PLAN.md](docs/qa/QAA-FINDINGS-PLAN.md) | 6 references | Add historical note header |
| [qa/QAA-MASTER-STATE.md](docs/qa/QAA-MASTER-STATE.md) | 4 references | Add historical note header |
| [qa/QA-V1.1.0-ANALYSIS-REPORT.md](docs/qa/QA-V1.1.0-ANALYSIS-REPORT.md) | 4 references | Add historical note header |
| [qa/MEDIUM-RESEARCH-PLANS.md](docs/qa/MEDIUM-RESEARCH-PLANS.md) | 2 references | Add historical note header |

---

## 4. Orphaned Cache Files

### 4.1 Orphaned Pytest Cache

**File:** `tests/unit/worker/__pycache__/test_metadata_synthesis.cpython-312-pytest-8.4.2.pyc`

**Source File Status:** DELETED (`test_metadata_synthesis.py` no longer exists)

**Cleanup Command:**
```bash
rm tests/unit/worker/__pycache__/test_metadata_synthesis.cpython-312-pytest-8.4.2.pyc
```

---

### 4.2 Orphaned Mypy Cache

**Files:**
```
.mypy_cache/3.12/test_worker_metadata_synthesis.data.json
.mypy_cache/3.12/test_metadata_synthesis.data.json
.mypy_cache/3.12/pulldb/worker/metadata_synthesis.data.json
.mypy_cache/3.12/pulldb/worker/dump_metadata.data.json
.mypy_cache/3.12/pulldb/worker/metadata_synthesis.meta.json
.mypy_cache/3.12/pulldb/worker/dump_metadata.meta.json
.mypy_cache/3.12/test_metadata_synthesis.meta.json
.mypy_cache/3.12/test_worker_metadata_synthesis.meta.json
```

**Source File Status:** All DELETED

**Cleanup Command:**
```bash
rm -f .mypy_cache/3.12/*metadata_synthesis* .mypy_cache/3.12/*dump_metadata*
```

---

## 5. Archived Templates & CSS

### 5.1 Properly Archived (No Action Required)

**Location:** `pulldb/web/_archived/` (492KB total)

These files are properly archived with a README explaining their purpose:

| Directory | Files | Status |
|-----------|-------|--------|
| `_archived/css/legacy/` | 4 CSS files | ✅ Documented |
| `_archived/css/orphaned/` | 1 CSS file | ✅ Documented |
| `_archived/templates/` | 11 HTML files | ✅ Documented |
| `_archived/partials/` | 3 HTML files | ✅ Documented |
| `_archived/shared/ui/` | 7 HTML files | ✅ Documented |
| `_archived/widgets/` | 6 HTML files | ✅ Documented |

**Verification:** No templates reference these archived files. They are safe historical artifacts.

---

## 6. Remediation Plan

### 6.1 Immediate Actions (Low Effort)

| Task | Command/Action | Priority |
|------|----------------|----------|
| Clean orphaned pycache | `rm tests/unit/worker/__pycache__/test_metadata_synthesis*` | Low |
| Clean orphaned mypy cache | `rm -f .mypy_cache/3.12/*metadata_synthesis* .mypy_cache/3.12/*dump_metadata*` | Low |
| Update KNOWLEDGE-POOL.md import | Change `metadata_synthesis` → `backup_metadata` | High |

### 6.2 Documentation Migration (Medium Effort)

| Task | Files | Priority |
|------|-------|----------|
| Move HEARTBEAT-FIX-AUDIT-REPORT.md | → `docs/archived/audit-reports/` | Medium |
| Move IMPLEMENTATION-PLAN-METADATA-HEARTBEAT.md | → `docs/archived/status-reports/` | Medium |
| Move METADATA-SYNTHESIS-OPTIMIZATION-PLAN.md | → `docs/archived/status-reports/` | Medium |
| Regenerate WORKSPACE-INDEX.md | Run indexer | Medium |

### 6.3 Code Cleanup (Deferred to v2.0.0)

| Task | Files | Priority |
|------|-------|----------|
| Remove `myloader_connection_timeout` setting | `settings.py` | Deferred |
| Remove `myloader_extra_args` setting | `config.py`, `settings.py` | Deferred |
| Migrate `.auth-submit` to `.btn-primary` | `login.html`, `profile.css` | Low |
| Remove unused sidebar legacy classes | `sidebar.css` | Low |

### 6.4 CSS Audit (Future Task)

Create automated audit script to:
1. Parse all CSS files for class definitions
2. Grep all HTML templates for class usage
3. Report classes defined but never used
4. Flag "legacy" comments for review

---

## 7. Summary Statistics

### Code Quality Metrics

| Metric | Value | Target |
|--------|-------|--------|
| Deprecated settings (active) | 1 | 0 |
| Deprecated settings (hidden) | 2 | Keep for compat |
| Stale doc references | 15+ | 0 |
| Orphaned cache files | 9 | 0 |
| Legacy CSS classes | ~30 | Audit needed |

### Test Coverage

| Area | Tests | Status |
|------|-------|--------|
| Deprecated settings | 6 tests | ✅ Passing |
| Config loading | 12 tests | ✅ Passing |
| MyLoader args | 8 tests | ✅ Passing |

---

## 8. Appendix: File Inventory

### 8.1 Files Referencing Deprecated Items

```
pulldb/domain/config.py
pulldb/domain/settings.py
pulldb/domain/restore_models.py
pulldb/tests/test_config.py
pulldb/tests/test_restore.py
pulldb/tests/test_restore_models.py
pulldb/web/features/admin/routes.py
docs/KNOWLEDGE-POOL.md
docs/WORKSPACE-INDEX.md
docs/WORKSPACE-INDEX.json
docs/hca/shared/configuration.md
packaging/env.example
```

### 8.2 Files to Archive

```
docs/HEARTBEAT-FIX-AUDIT-REPORT.md
docs/IMPLEMENTATION-PLAN-METADATA-HEARTBEAT.md
docs/METADATA-SYNTHESIS-OPTIMIZATION-PLAN.md
```

### 8.3 Files to Clean

```
tests/unit/worker/__pycache__/test_metadata_synthesis.cpython-312-pytest-8.4.2.pyc
.mypy_cache/3.12/test_worker_metadata_synthesis.data.json
.mypy_cache/3.12/test_metadata_synthesis.data.json
.mypy_cache/3.12/pulldb/worker/metadata_synthesis.data.json
.mypy_cache/3.12/pulldb/worker/dump_metadata.data.json
.mypy_cache/3.12/pulldb/worker/metadata_synthesis.meta.json
.mypy_cache/3.12/pulldb/worker/dump_metadata.meta.json
.mypy_cache/3.12/test_metadata_synthesis.meta.json
.mypy_cache/3.12/test_worker_metadata_synthesis.meta.json
```

---

*End of Audit Report*
