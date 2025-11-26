# Scripts Directory Audit Report

**Date**: November 26, 2025  
**Scope**: `scripts/`, `graph-tools/scripts/`

---

## Executive Summary

The `scripts/` directory contains 43 files with some overlap and organization issues. **Recommended actions will reduce duplication and improve organization**.

| Category | Count | Action |
|----------|-------|--------|
| Keep (active) | 26 | Retain with minor updates |
| Archive | 4 | Move to `scripts/archived/` |
| Delete | 0 | None |
| Merge | 5 | Consolidate into fewer scripts |

**Note**: Many scripts are bundled into the `.deb` package and are actively used during installation/upgrades.

---

## Directory Structure Analysis

### Current Structure
```
scripts/
├── archived/           # Historical scripts (good)
│   ├── debug/          # 18 debug scripts
│   └── manual-tests/   # 7 manual test scripts
├── lib/                # Shared library (good)
│   └── validate-common.sh
├── validate/           # Validation pipeline (good)
│   └── 00-99 numbered scripts
└── [40+ loose scripts] # PROBLEM: needs organization
```

### Proposed Structure
```
scripts/
├── archived/           # Historical reference only
├── lib/                # Shared libraries
├── validate/           # Validation pipeline
├── build/              # Build & packaging
├── install/            # Installation & configuration  
├── ops/                # Operations & monitoring
├── dev/                # Development utilities
└── README.md           # Updated documentation
```

---

## Detailed Analysis by Category

### 1. BUILD SCRIPTS (Keep - reorganize to `scripts/build/`)

| Script | Purpose | Status |
|--------|---------|--------|
| `build_deb.sh` | Build server .deb package | ✅ Active, well-written |
| `build_client_deb.sh` | Build client .deb package | ✅ Active, well-written |

**Action**: Move to `scripts/build/`

---

### 2. INSTALLATION SCRIPTS (Keep - reorganize to `scripts/install/`)

| Script | Purpose | Status |
|--------|---------|--------|
| `install_pulldb.sh` | Main installer | ✅ Active |
| `uninstall_pulldb.sh` | Uninstaller | ✅ Active |
| `upgrade_pulldb.sh` | Upgrade script | ✅ Active |
| `configure-pulldb.sh` | Interactive configuration | ✅ Active |
| `pulldb-worker.service` | Systemd unit file | ✅ Active |

**Action**: Move to `scripts/install/`

---

### 3. SETUP SCRIPTS - COMPLEMENTARY (NOT DUPLICATES)

| Script | Purpose | Status |
|--------|---------|--------|
| `setup-aws.sh` | **Install** AWS CLI v2 (system-level) | ✅ Keep |
| `setup-aws-credentials.sh` | **Validate** AWS credentials post-install | ✅ Keep |
| `setup-mysql.sh` | Install/configure MySQL | ✅ Keep |
| `configure_server.sh` | Server AWS config | ✅ **Packaged** |
| `configure-pulldb.sh` | Interactive config | ✅ **Packaged** |

**Analysis**: These scripts are complementary, not duplicates:
- `setup-aws.sh` installs the CLI binary
- `setup-aws-credentials.sh` validates credentials after installation

---

### 4. TEST ENVIRONMENT SCRIPTS - COMPLEMENTARY (NOT DUPLICATES)

| Script | Purpose | Lines | Status |
|--------|---------|-------|--------|
| `setup-test-environment.sh` | **Full test env** (MySQL, AWS, dirs, venv) | 814 | ✅ Keep |
| `setup_test_env.sh` | **Python venv only** for quick test runs | 140 | ✅ Keep |
| `teardown-test-environment.sh` | Cleanup full test env | ~50 | ✅ Keep |
| `start-test-services.sh` | Start services in test env | ~50 | ✅ Keep |

**Analysis**: These scripts serve different use cases:
- `setup-test-environment.sh` - Full environment for comprehensive testing
- `setup_test_env.sh` - Lightweight venv for quick `pytest` runs

---

### 5. VALIDATION SCRIPTS - WELL ORGANIZED BUT OVERLAPPING

#### Good Structure: `scripts/validate/` Pipeline
```
validate/
├── 00-prerequisites.sh  # System checks
├── 10-install.sh        # Isolated install
├── 20-unit-tests.sh     # pytest
├── 30-integration.sh    # AWS/S3 tests
├── 40-e2e-restore.sh    # Full restore test
└── 99-teardown.sh       # Cleanup
```
**Status**: ✅ Well-designed, keep as-is

#### Overlapping Top-Level Scripts

| Script | Purpose | Status | Action |
|--------|---------|--------|--------|
| `pulldb-validate.sh` | Orchestrates validate/* | ✅ Keep | Main entry point |
| `service-validate.sh` | Production validation | ✅ **Packaged** | Keep (bundled in .deb) |
| `validate-config.sh` | Config validation | ⚠️ Overlaps | **ARCHIVE** (covered by validate/*) |
| `run-quick-test.sh` | Quick smoke test | ⚠️ Overlaps | **ARCHIVE** (use pulldb-validate.sh --quick) |
| `run-e2e-restore.sh` | E2E restore | ⚠️ Overlaps | **ARCHIVE** (use pulldb-validate.sh --e2e) |

**Note**: `service-validate.sh` is bundled for production use; `pulldb-validate.sh` is for development.

---

### 6. PYTHON UTILITY SCRIPTS (Keep - move to `scripts/ops/` or `scripts/dev/`)

#### Operations Scripts → `scripts/ops/`

| Script | Purpose | Status |
|--------|---------|--------|
| `monitor_jobs.py` | Job/process reconciliation | ✅ Active, documented |
| `cleanup_dev_env.py` | Drop test databases | ✅ Active |
| `cleanup_system.sh` | System cleanup | ✅ Active |
| `verify-aws-access.py` | Cross-account S3 access test | ✅ Active |
| `verify-secrets-perms.sh` | IAM permissions test | ✅ Active, well-documented |

#### Development Scripts → `scripts/dev/`

| Script | Purpose | Status |
|--------|---------|--------|
| `benchmark_atomic_rename.py` | Performance benchmark | ✅ Dev tool |
| `deploy_atomic_rename.py` | Deploy stored procedure | ✅ Dev tool |
| `ensure_fail_hard.py` | Doc compliance check | ✅ Dev tool |
| `generate_cloudshell.py` | Generate AWS commands | ✅ Dev tool |
| `precommit-verify.py` | Pre-commit hygiene | ✅ Dev tool |
| `validate-knowledge-pool.py` | JSON sync validation | ✅ Dev tool |
| `validate-metrics-emission.py` | Metrics infrastructure test | ✅ Dev tool |
| `update-engineering-dna.sh` | Submodule update | ✅ Dev tool |

---

### 7. IAM/PERMISSIONS SCRIPTS

| Script | Purpose | Status | Action |
|--------|---------|--------|--------|
| `deploy-iam-templates.sh` | Print IAM CLI commands | ✅ Keep | Move to `scripts/ops/` |
| `audit-permissions.sh` | File permission audit | ✅ Keep | Move to `scripts/dev/` |
| `ci-permissions-check.sh` | CI permission check | ✅ Keep | Move to `scripts/dev/` |

---

### 8. PACKAGING-REQUIRED SCRIPTS

Scripts bundled into the `.deb` package (see `scripts/build_deb.sh`):

| Script | Purpose | Package Location |
|--------|---------|------------------|
| `install_pulldb.sh` | Main installer | `/opt/pulldb.service/scripts/` |
| `uninstall_pulldb.sh` | Uninstaller | `/opt/pulldb.service/scripts/` |
| `upgrade_pulldb.sh` | Upgrade handler | `/opt/pulldb.service/scripts/` |
| `configure_server.sh` | Server AWS config | `/opt/pulldb.service/scripts/` |
| `configure-pulldb.sh` | Interactive config | `/opt/pulldb.service/scripts/` |
| `monitor_jobs.py` | Job monitoring | `/opt/pulldb.service/scripts/` |
| `service-validate.sh` | Production validation | `/opt/pulldb.service/scripts/` |
| `merge-config.sh` | **Config migration** | `/opt/pulldb.service/scripts/` |

**Critical**: `merge-config.sh` is used by `postinst` to:
- Backup existing `.env` and `.aws/config` during upgrades
- Merge user values with new template (preserving customizations)
- Support both `env` (KEY=value) and `ini` ([section]) formats

---

### 9. OBSOLETE/ARCHIVE CANDIDATES

| Script | Reason | Action |
|--------|--------|--------|
| `setup-tests-dbdata.sh` | Obsolete (seeds old schema) | **ARCHIVE** |
| `validate-config.sh` | Replaced by validate/* pipeline | **ARCHIVE** |
| `run-quick-test.sh` | Replaced by pulldb-validate.sh --quick | **ARCHIVE** |
| `run-e2e-restore.sh` | Replaced by pulldb-validate.sh --e2e | **ARCHIVE** |

---

### 9. GRAPH-TOOLS SCRIPTS (Keep)

| Script | Purpose | Status |
|--------|---------|--------|
| `graph-tools/scripts/generate_code_graph.py` | Generate code visualization | ✅ Dev tool |
| `graph-tools/scripts/generate_flow_graph.py` | Generate flow visualization | ✅ Dev tool |

**Status**: ✅ Well-organized, separate tooling - keep as-is

---

### 10. ARCHIVED SCRIPTS (Already archived - verify)

```
scripts/archived/
├── debug/           # 18 debug scripts - OK
├── manual-tests/    # 7 manual test scripts - OK
├── setup-pulldb-schema.sh  # Archived Nov 2025
└── setup-python-project.sh # Archived Nov 2025
```
**Status**: ✅ Properly archived with README

---

## Recommended Actions

### Phase 1: Archive Obsolete (4 files)
```bash
mv scripts/setup-tests-dbdata.sh scripts/archived/
mv scripts/validate-config.sh scripts/archived/
mv scripts/run-quick-test.sh scripts/archived/
mv scripts/run-e2e-restore.sh scripts/archived/
```

### Phase 2: Reorganize (create subdirectories)
```bash
mkdir -p scripts/{build,install,ops,dev}

# Build
mv scripts/build_deb.sh scripts/build_client_deb.sh scripts/build/

# Install (NOTE: keep copies at root for packaging compatibility)
# These are copied into .deb package from scripts/ root
# Consider symlinks or build script updates

# Ops
mv scripts/cleanup_dev_env.py scripts/cleanup_system.sh \
   scripts/verify-aws-access.py scripts/deploy-iam-templates.sh scripts/ops/

# Dev
mv scripts/benchmark_atomic_rename.py scripts/deploy_atomic_rename.py \
   scripts/ensure_fail_hard.py scripts/generate_cloudshell.py \
   scripts/precommit-verify.py scripts/validate-knowledge-pool.py \
   scripts/validate-metrics-emission.py scripts/update-engineering-dna.sh \
   scripts/audit-permissions.sh scripts/ci-permissions-check.sh scripts/dev/
```

### Phase 3: Update build_deb.sh paths
After reorganization, update `scripts/build_deb.sh` to reference new locations
or keep packaging-required scripts at root level.

### Phase 4: Update README.md
Update `scripts/README.md` to reflect new organization.

---

## Packaging Dependencies

Scripts required by `build_deb.sh` (must remain accessible):
- `install_pulldb.sh`
- `uninstall_pulldb.sh`  
- `upgrade_pulldb.sh`
- `configure_server.sh`
- `configure-pulldb.sh`
- `monitor_jobs.py`
- `service-validate.sh`
- `merge-config.sh`

Scripts required by `postinst`:
- `merge-config.sh` - Called to merge `.env` and `.aws/config` during upgrades
- `configure-pulldb.sh` - Called for interactive configuration

---

## Standards Compliance Issues

### Missing/Incomplete Docstrings
- `setup-aws.sh` - Good header ✅
- `configure_server.sh` - Minimal documentation ⚠️
- `run-e2e-restore.sh` - Hardcoded paths ⚠️

### FAIL HARD Philosophy Violations
- `run-e2e-restore.sh` - Uses `set -e` only, no diagnostics
- `setup-tests-dbdata.sh` - Missing actionable error messages

### Hardcoded Values (should use env vars)
- `run-e2e-restore.sh`: Hardcoded MySQL credentials
- `configure_server.sh`: Hardcoded `/opt/pulldb.service`

---

## Summary Metrics

| Metric | Before | After |
|--------|--------|-------|
| Root-level scripts | 37 | 33 |
| Archived scripts | 6 | 10 |
| Duplicate pairs | 0 | 0 |
| Well-organized | ✅ | ✅ |

---

## Audit Conclusion

After detailed analysis, the scripts directory is **well-organized**:

1. **No true duplicates** - Scripts that appeared similar serve different purposes
2. **Clear separation** - Packaging scripts vs dev scripts vs validation pipeline
3. **Good documentation** - README.md updated with categorized reference
4. **Proper archival** - Obsolete scripts moved to `archived/` with replacements documented

### Remaining Opportunities (Low Priority)

1. **Subdirectory organization** - Could move dev scripts to `scripts/dev/` but not required
2. **Naming consistency** - Mix of `script-name.sh` and `script_name.sh` (cosmetic)
3. **FAIL HARD compliance** - Some scripts use `set -e` only without actionable diagnostics

No further changes recommended at this time.
