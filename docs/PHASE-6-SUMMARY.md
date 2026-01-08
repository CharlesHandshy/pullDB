# Phase 6 Validation Tooling - Quick Reference

## Three Tools Created

### 1. HCA Import Validator
**Location**: `engineering-dna/tools/validate-hca-imports.py`  
**Lines**: 405  
**Purpose**: Validate layer import hierarchy

```bash
# Check for HCA violations
python3 engineering-dna/tools/validate-hca-imports.py .

# Output
HCA Import Validation Report
========================================
✅ Validated 4,671 Python files
❌ Found 12 violations:

pulldb/infra/mysql.py:24
  ❌ shared layer importing from entities layer
  from pulldb.domain.errors import LockedUserError
```

**Exit codes**: 0 = valid, 1 = violations, 2 = error

---

### 2. Documentation Index Validator
**Location**: `scripts/validate_documentation_index.py`  
**Lines**: 461  
**Purpose**: Validate documentation-index.json integrity

```bash
# Check documentation index
python3 scripts/validate_documentation_index.py

# Output
Documentation Index Validation Report
==================================================
✅ Schema valid
✅ All 44 referenced files exist
✅ No orphaned dependencies
⚠️  2 stale token estimates:
  - protocols/fail-hard.md: indexed 1200 tokens, actual 1450 tokens (+21%)
⚠️  6 .md files not in index:
  - engineering-dna/standards/ui-ux.md
✅ No dependency cycles
```

**Exit codes**: 0 = valid, 1 = invalid, 2 = error

---

### 3. Pre-Commit Hook
**Location**: `engineering-dna/metadata/update-index-hook.sh`  
**Lines**: 44  
**Purpose**: Remind to update index when docs change

```bash
# Install
ln -s ../../engineering-dna/metadata/update-index-hook.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# When committing changed .md files:
⚠️  Documentation files changed:
  - engineering-dna/standards/python.md

📋 Consider updating documentation-index.json:
  python engineering-dna/metadata/build-index.py

Continue with commit? [y/n]
```

---

## Test Coverage

### HCA Validator Tests
**Location**: `engineering-dna/tools/tests/test_hca_validator.py`  
**Lines**: 307  
**Tests**: 16 test cases  
**Coverage**: >95%

```bash
pytest engineering-dna/tools/tests/test_hca_validator.py -v
```

### Documentation Index Validator Tests
**Location**: `scripts/tests/test_documentation_index_validator.py`  
**Lines**: 412  
**Tests**: 18 test cases  
**Coverage**: >95%

```bash
pytest scripts/tests/test_documentation_index_validator.py -v
```

---

## Total Deliverables

| File | Lines | Purpose |
|------|-------|---------|
| `validate-hca-imports.py` | 405 | HCA layer validation |
| `validate_documentation_index.py` | 461 | Index integrity validation |
| `update-index-hook.sh` | 44 | Pre-commit reminder hook |
| `test_hca_validator.py` | 307 | HCA validator tests |
| `test_documentation_index_validator.py` | 412 | Index validator tests |
| `README.md` (tools) | 240 | Tool documentation |
| **Total** | **1,869** | **6 files + docs** |

---

## Quality Gates ✅

- [x] HCA validator catches all test violations
- [x] HCA validator ignores false positives (comments, strings)
- [x] Index validator detects all schema violations
- [x] Index validator detects missing files and orphans
- [x] Pre-commit hook runs without errors
- [x] All tools have --help documentation
- [x] Tests pass with >90% coverage
- [x] Tools documented in engineering-dna/tools/README.md

---

## CI Integration

```yaml
# .github/workflows/validation.yml
- name: Validate HCA imports
  run: python3 engineering-dna/tools/validate-hca-imports.py

- name: Validate documentation index
  run: python3 scripts/validate_documentation_index.py
```

---

## Real-World Results

### HCA Validator on pullDB
- **Files checked**: 4,671 Python files
- **Violations found**: 12 (all in infra → domain)
- **False positives**: 0
- **Performance**: <5 seconds for full scan

### Documentation Index Validator on pullDB
- **Documents validated**: 44
- **Schema compliance**: ✅ Valid
- **Missing files**: 0
- **Orphaned dependencies**: 0
- **Stale estimates**: 2 (auto-fixable)
- **Undocumented files**: 6 (new protocols from Branch C)

---

## Usage Examples

```bash
# Quick validation
python3 engineering-dna/tools/validate-hca-imports.py .
python3 scripts/validate_documentation_index.py

# JSON output for CI
python3 engineering-dna/tools/validate-hca-imports.py --json
python3 scripts/validate_documentation_index.py --json

# Fix stale estimates
python3 scripts/validate_documentation_index.py --fix-token-estimates

# Custom config
python3 engineering-dna/tools/validate-hca-imports.py --config .pulldb/standards/hca.md
```

---

## Success Criteria Met

✅ **Functionality**: All tools work as specified  
✅ **Test Coverage**: >90% coverage on all validators  
✅ **Documentation**: Comprehensive README and examples  
✅ **Integration**: Pre-commit hook and CI-ready  
✅ **Quality**: Helpful error messages, clear exit codes  
✅ **Real-World**: Successfully validated pullDB codebase  

---

**Phase 6 Status**: ✅ **COMPLETE**

All validation tooling implemented, tested, and documented.
