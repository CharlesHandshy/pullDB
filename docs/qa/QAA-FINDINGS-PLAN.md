# QA&A Findings & Remediation Plan

> **Document Type**: Findings Registry | **Version**: 1.0.0 | **Created**: 2026-01-19
>
> Central registry of all findings from codebase analysis.
> Each finding includes severity, standard reference, and remediation steps.

---

## Document Structure

This document is organized by batch, with each batch containing:
1. **Batch Summary** - Overview statistics
2. **File Findings** - Detailed findings per file
3. **Remediation Tasks** - Grouped by effort level

---

## Summary Dashboard

### Findings by Severity

| Severity | Count | % | Remediation Status |
|----------|-------|---|-------------------|
| 🔴 CRITICAL | 50 | 14% | **50 remediated ✅** |
| 🟠 HIGH | 99 | 27% | **99 remediated ✅** |
| 🟡 MEDIUM | 129 | 35% | **106 remediated ✅** |
| 🟢 LOW | 88 | 24% | 0 remediated |
| **TOTAL** | 366 | 100% | **255 remediated (70%)** |

### Pylance Error Status (Production Code)

| Metric | Before | After |
|--------|--------|-------|
| `pulldb/` errors | 145+ | **0 ✅** |
| `tests/` errors | ~15 | 9 |

### Findings by Category

| Category | CRIT | HIGH | MED | LOW | Total Remaining |
|----------|------|------|-----|-----|-----------------|
| HCA Compliance | 0 | ~~71~~ 0 ✅ | ~~10~~ 0 ✅ | 5 | 5 |
| Type Hints | ~~50~~ 0 ✅ | ~~11~~ 0 ✅ | ~~12~~ 8 ✅ | 10 | 8 |
| Docstrings | 0 | 0 | ~~20~~ 14 ✅ | 21 | 14 |
| Error Handling | 0 | ~~8~~ 0 ✅ | ~~67~~ 43 ✅ | 29 | 66 |
| Code Quality | 0 | ~~9~~ 0 ✅ | ~~20~~ 14 ✅ | 23 | 18 |
| **TOTAL** | ~~50~~ 0 | ~~99~~ 0 | ~~129~~ 23 | 88 | **111** |

### Remediation Effort Estimate

| Effort Level | Findings | Est. Hours |
|--------------|----------|------------|
| Quick Fix (< 5 min) | 169 | 14.1 |
| Simple (5-30 min) | 172 | 43.0 |
| Moderate (30-60 min) | 22 | 16.5 |
| Complex (> 1 hour) | 3 | 6.0 |
| **TOTAL** | 366 | 79.6 |

---

## Finding ID Convention

```
[BATCH]-[FILE_NUM]-[FINDING_NUM]

Examples:
- B01-001-001 = Batch 01, File 1, Finding 1
- B03-007-003 = Batch 03, File 7, Finding 3
```

---

## Batch Findings

---

### Batch B01: pulldb/api/

**Status**: ✅ Complete
**Files**: 6
**Analysis Date**: 2026-01-19
**Analyst**: GitHub Copilot (Claude Opus 4.5)

#### Summary

| Metric | Value |
|--------|-------|
| Files Analyzed | 6/6 |
| Total Findings | 27 |
| Critical | 1 |
| High | 7 |
| Medium | 11 |
| Low | 8 |
| Avg Compliance | 73% |

#### File: pulldb/api/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 35%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B01-001-001 | HCA | HIGH | 1 | Missing `HCA Layer: pages` in module docstring | hca.md §Law2 | Add `HCA Layer: pages` to docstring |
| B01-001-002 | Python | CRITICAL | 1-4 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B01-001-003 | Docstrings | MEDIUM | 1 | Module docstring too minimal | python.md §Docstrings | Expand with purpose, exports |

**Compliant Patterns**: Uses `__all__` for explicit exports

#### File: pulldb/api/auth.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B01-002-001 | HCA | HIGH | 1-21 | Missing `HCA Layer: pages` in module docstring | hca.md §Law2 | Add `HCA Layer: pages` to docstring |
| B01-002-002 | Imports | LOW | 29-31 | Import from domain before api internal | python.md §Imports | Reorder: domain before api internal |

**Compliant Patterns**: ✅ Has `from __future__ import annotations`, modern type hints, excellent docstrings, proper exception handling

#### File: pulldb/api/logic.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 70%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B01-003-001 | HCA | HIGH | 1 | Missing `HCA Layer: pages` in module docstring | hca.md §Law2 | Add `HCA Layer: pages` to docstring |
| B01-003-002 | Error | MEDIUM | 60 | `except Exception` without logging | fail-hard.md | Add logging or narrow exception |
| B01-003-003 | Error | MEDIUM | 100 | `except Exception` without logging | fail-hard.md | Add logging or narrow exception |
| B01-003-004 | Error | MEDIUM | 170 | `except Exception` without logging | fail-hard.md | Add logging or narrow exception |
| B01-003-005 | Error | MEDIUM | 454 | Silent `except Exception` in options snapshot | fail-hard.md | Add logging for troubleshooting |
| B01-003-006 | Error | MEDIUM | 809 | Silent supersession failure | fail-hard.md | Add logging for audit trail |
| B01-003-007 | Docstrings | LOW | 36-43 | Private function missing docstring | python.md §Docstrings | Add brief docstring |

**Compliant Patterns**: ✅ Has future annotations, modern types, excellent public docstrings, uses `raise ... from e`

#### File: pulldb/api/main.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 75%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B01-004-001 | HCA | HIGH | 1 | Missing `HCA Layer: pages` in module docstring | hca.md §Law2 | Add `HCA Layer: pages` to docstring |
| B01-004-002 | Python | LOW | 8 | Non-standard `t` alias for typing | python.md §Imports | Consider explicit imports |
| B01-004-003 | Error | MEDIUM | 130 | `except ImportError: pass` - silent failure | fail-hard.md | Add logging for debugging |
| B01-004-004 | Error | MEDIUM | 209 | `except ImportError: pass` - silent auth repo failure | fail-hard.md | Add logging |
| B01-004-005 | Error | HIGH | 670 | `except Exception: pass` - API key creation silently swallowed | fail-hard.md | Add logging for audit |
| B01-004-006 | Error | LOW | 886 | `except Exception: pass` - host resolution fallback | fail-hard.md | Acceptable graceful degradation |
| B01-004-007 | Quality | MEDIUM | 4457 | Uses `print()` instead of logging | python.md §Logging | Replace with `logger.info()` |
| B01-004-008 | Docstrings | LOW | Multiple | Many endpoint functions lack docstrings | python.md §Docstrings | Add docstrings to public endpoints |

**Compliant Patterns**: ✅ Has future annotations, modern types, proper exception chaining where present, uses TYPE_CHECKING

#### File: pulldb/api/schemas.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B01-005-001 | HCA | HIGH | 1 | Missing `HCA Layer: pages` in module docstring | hca.md §Law2 | Add `HCA Layer: pages` to docstring |
| B01-005-002 | Docstrings | LOW | Multiple | Class docstrings present but lack field descriptions | python.md §Docstrings | Add field-level descriptions |

**Compliant Patterns**: ✅ Has future annotations, modern types, good class docstrings, clean Pydantic usage

#### File: pulldb/api/types.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B01-006-001 | HCA | HIGH | 1 | Missing `HCA Layer: pages` in module docstring | hca.md §Law2 | Add `HCA Layer: pages` to docstring |
| B01-006-002 | Python | LOW | 4 | Non-standard `t` alias for typing | python.md §Imports | Consider explicit imports |
| B01-006-003 | Python | MEDIUM | 17-24 | Uses `Any` for repository types | python.md §TypeHints | Consider Protocol definitions |

**Compliant Patterns**: ✅ Has future annotations, uses TYPE_CHECKING guard, NamedTuple for immutable state

---

### Batch B02: pulldb/cli/

**Status**: ✅ Complete
**Files**: 10
**Analysis Date**: 2026-01-19
**Analyst**: GitHub Copilot (Claude Opus 4.5)

#### Summary

| Metric | Value |
|--------|-------|
| Files Analyzed | 10/10 |
| Total Findings | 29 |
| Critical | 0 |
| High | 4 |
| Medium | 10 |
| Low | 15 |
| Avg Compliance | 86% |

#### File: pulldb/cli/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 50%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B02-001-001 | HCA | HIGH | 1 | Missing `HCA Layer: pages` in module docstring | hca.md §Law2 | Add `HCA Layer: pages` to docstring |
| B02-001-002 | Python | HIGH | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: Simple, minimal `__init__.py` with proper `__all__` export

#### File: pulldb/cli/__main__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 40%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B02-002-001 | HCA | HIGH | 1 | No module docstring with HCA layer | hca.md §Law2 | Add module docstring with `HCA Layer: pages` |
| B02-002-002 | Python | HIGH | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: Clean entry point pattern with relative import

#### File: pulldb/cli/admin.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 92%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B02-003-001 | HCA | MEDIUM | 1-18 | Missing explicit `HCA Layer: pages` in docstring | hca.md §Law2 | Add HCA layer declaration |
| B02-003-002 | Docstrings | LOW | 43-56 | CLI function has docstring but not Google-style | python.md §Docstrings | Consider adding Returns/Raises sections |

**Compliant Patterns**: ✅ Has future annotations, modern types, proper exception chaining, imports from lower layers

#### File: pulldb/cli/admin_commands.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B02-004-001 | HCA | MEDIUM | 1-14 | Missing explicit `HCA Layer: pages` in docstring | hca.md §Law2 | Add HCA layer declaration |
| B02-004-002 | Error | LOW | 286-289 | `except Exception` in cleanup without logging | fail-hard.md | Add logging before raising ClickException |
| B02-004-003 | Error | LOW | 808-817 | `except Exception: pass` suppresses errors silently | fail-hard.md | Add logging or comment explaining why |

**Compliant Patterns**: ✅ Has future annotations, modern types, exception chaining used consistently

#### File: pulldb/cli/auth.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 93%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B02-005-001 | HCA | MEDIUM | 1-18 | Missing explicit `HCA Layer: pages` in docstring | hca.md §Law2 | Add HCA layer declaration |
| B02-005-002 | Error | LOW | 68-69 | Bare `except Exception: pass` | fail-hard.md | Add logging or narrow exception type |
| B02-005-003 | Error | LOW | 99 | Bare `except Exception: pass` | fail-hard.md | Add logging or be more specific |

**Compliant Patterns**: ✅ Has future annotations, modern types, good docstrings with Args/Returns/Raises

#### File: pulldb/cli/backup_commands.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B02-006-001 | HCA | MEDIUM | 1-11 | Missing explicit `HCA Layer: pages` in docstring | hca.md §Law2 | Add HCA layer declaration |
| B02-006-002 | Error | LOW | 307-312 | `except Exception` with only conditional echo | fail-hard.md | Add logging for errors |
| B02-006-003 | Error | LOW | 416-421 | Error suppressed without logging | fail-hard.md | Add logging |

**Compliant Patterns**: ✅ Has future annotations, modern types, good dataclass usage, exception chaining

#### File: pulldb/cli/main.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 88%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B02-007-001 | HCA | MEDIUM | 1 | Missing explicit `HCA Layer: pages` in docstring | hca.md §Law2 | Add HCA layer declaration |
| B02-007-002 | Error | LOW | 102-103 | `except Exception: pass` without logging | fail-hard.md | Add logging |
| B02-007-003 | Error | LOW | 170, 200-202 | Multiple `except Exception: pass` blocks | fail-hard.md | Add logging or be more specific |
| B02-007-004 | Error | LOW | 841-843 | `except Exception: pass` for host info | fail-hard.md | Add logging |
| B02-007-005 | Quality | LOW | 1-2630 | Long module (2630 lines) | python.md §Organization | Consider splitting into sub-modules |

**Compliant Patterns**: ✅ Has future annotations, modern types, good Click structure, imports from lower layers

#### File: pulldb/cli/parse.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 95%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B02-008-001 | HCA | MEDIUM | 1-28 | Missing explicit `HCA Layer: pages` in docstring | hca.md §Law2 | Add HCA layer declaration |

**Compliant Patterns**: ✅ Has future annotations, modern types, excellent docstrings, custom exception follows FAIL HARD

#### File: pulldb/cli/secrets_commands.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 88%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B02-009-001 | HCA | MEDIUM | 1-16 | Missing explicit `HCA Layer: pages` in docstring | hca.md §Law2 | Add HCA layer declaration |
| B02-009-002 | Python | LOW | 40 | Using `Any` for boto3 return types | python.md §TypeHints | Consider more specific type stubs |
| B02-009-003 | Error | LOW | 438-439 | `except Exception` with click.echo but no logging | fail-hard.md | Add logging module usage |

**Compliant Patterns**: ✅ Has future annotations, modern types, proper dataclass, good exception handling

#### File: pulldb/cli/settings.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B02-010-001 | HCA | MEDIUM | 1-15 | Missing explicit `HCA Layer: pages` in docstring | hca.md §Law2 | Add HCA layer declaration |
| B02-010-002 | Error | LOW | 164 | `except Exception` with echo only | fail-hard.md | Add logging |
| B02-010-003 | Error | LOW | 336 | `except Exception` in set_setting | fail-hard.md | Add logging |

**Compliant Patterns**: ✅ Has future annotations, modern types, exception chaining used

---

### Batch B03: pulldb/infra/

**Status**: ✅ Complete
**Files**: 13
**Analysis Date**: 2026-01-19
**Analyst**: Sub-agent
**Total Findings**: 47
**Severity**: CRIT: 5 | HIGH: 21 | MED: 14 | LOW: 7
**Avg Compliance**: 74%

#### File: pulldb/infra/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 40%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-001-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: shared` in module docstring | hca.md §Law2 | Add `HCA Layer: shared` to docstring |
| B03-001-002 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: Minimal `__init__.py` file

#### File: pulldb/infra/config.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-002-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: shared` in module docstring | hca.md §Law2 | Add `HCA Layer: shared` to docstring |
| B03-002-002 | Python | LOW | 21-22 | Unused `TYPE_CHECKING` import - empty block | python.md §Imports | Remove unused import or use it |

**Compliant Patterns**: ✅ Has future annotations, modern type syntax

#### File: pulldb/infra/context.py

**Status**: ✅ Analyzed
**HCA Layer**: shared (Layer 0) | **Expected**: shared ✅
**Compliance Score**: 95%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-003-001 | Code | LOW | 202 | `# type: ignore[union-attr]` without justification comment | python.md §TypeIgnore | Add comment explaining why ignore is needed |
| B03-003-002 | Code | LOW | 208 | `# type: ignore[union-attr]` without justification comment | python.md §TypeIgnore | Add comment explaining why ignore is needed |

**Compliant Patterns**: ✅ Has HCA Layer docstring, ✅ Has future annotations, ✅ Modern type syntax

#### File: pulldb/infra/exec.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-004-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: shared` in module docstring | hca.md §Law2 | Add `HCA Layer: shared` to docstring |
| B03-004-002 | Error | MEDIUM | 149 | Broad `except Exception` with only `raise` | fail-hard.md | Add specific exception types or logging |
| B03-004-003 | Code | MEDIUM | 149 | `# pragma: no cover` may mask coverage issues | python.md | Consider if coverage exclusion is appropriate |

**Compliant Patterns**: ✅ Has future annotations, ✅ Modern type syntax (`list`, `dict`, `|` syntax)

#### File: pulldb/infra/executor.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 75%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-005-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: shared` in module docstring | hca.md §Law2 | Add `HCA Layer: shared` to docstring |
| B03-005-002 | Python | HIGH | 122+ | Uses `Callable` return type without specific signature | python.md §TypeHints | Consider Protocol or more specific callable types |
| B03-005-003 | Docstrings | MEDIUM | 176 | Function lacks docstring with Args/Returns | python.md §Docstrings | Add Google-style docstring |
| B03-005-004 | Code | MEDIUM | 208 | File appears truncated mid-function | - | Verify file integrity |

**Compliant Patterns**: ✅ Has future annotations, ✅ Uses modern `X | None` syntax

#### File: pulldb/infra/lock.py

**Status**: ✅ Analyzed
**HCA Layer**: shared (Layer 0) | **Expected**: shared ✅
**Compliance Score**: 98%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-006-001 | Code | LOW | - | Minor: Module well-structured (informational) | - | None required |

**Compliant Patterns**: ✅ Has HCA Layer docstring, ✅ Has future annotations, ✅ Modern type syntax, ✅ Google-style docstrings

#### File: pulldb/infra/logging_config.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-007-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: shared` in module docstring | hca.md §Law2 | Add `HCA Layer: shared` to docstring |
| B03-007-002 | Python | MEDIUM | - | Uses `str` for log level - could use `Literal` | python.md §TypeHints | Consider `Literal["DEBUG", "INFO", ...]` |
| B03-007-003 | Code | LOW | 118 | Uses `cast()` which could be avoided with better typing | python.md §TypeHints | Consider refactoring to avoid cast |

**Compliant Patterns**: ✅ Has future annotations, ✅ Modern `X | None` syntax

#### File: pulldb/infra/mysql_connection.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 80%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-008-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: shared` in module docstring | hca.md §Law2 | Add `HCA Layer: shared` to docstring |
| B03-008-002 | Docstrings | MEDIUM | - | Dataclass fields lack inline documentation | python.md §Docstrings | Add inline comments or Attributes section |

**Compliant Patterns**: ✅ Has future annotations, ✅ Modern `X | None` syntax, ✅ Good dataclass usage

#### File: pulldb/infra/mysql.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 78%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-009-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: shared` in module docstring | hca.md §Law2 | Add `HCA Layer: shared` to docstring |
| B03-009-002 | Python | HIGH | 61+ | Uses `Any` throughout - consider more specific types | python.md §TypeHints | Replace with specific types where possible |
| B03-009-003 | Python | HIGH | 65+ | Uses `Tuple` instead of `tuple` | python.md §ModernTypes | Replace `Tuple` with `tuple` |
| B03-009-004 | Code | MEDIUM | 208+ | Deprecated methods `create_job`, `update_job` still present | deprecation | Create removal timeline |
| B03-009-005 | Python | MEDIUM | 64 | Context manager returns `Any` - could be more specific | python.md §TypeHints | Return specific cursor type |
| B03-009-006 | Code | LOW | - | File is 5890 lines - consider splitting | python.md §FileSize | Split into job/user/host repository modules |
| B03-009-007 | Python | MEDIUM | 869 | Import inside method should be at module level | python.md §Imports | Move import to top of file |

**Compliant Patterns**: ✅ Has future annotations, ✅ Uses modern `X | None` in places

#### File: pulldb/infra/paths.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 75%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-010-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: shared` in module docstring | hca.md §Law2 | Add `HCA Layer: shared` to docstring |
| B03-010-002 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B03-010-003 | Python | HIGH | 46 | Uses `list[str]` without future annotations (Python 3.9+ only) | python.md §ModernTypes | Add future annotations or use `List` |
| B03-010-004 | Python | HIGH | 47+ | Uses `dict[str, X]` without future annotations | python.md §ModernTypes | Add future annotations or use `Dict` |
| B03-010-005 | Error | MEDIUM | 135 | Catches base `Exception` - could be more specific | fail-hard.md | Catch specific exception types |
| B03-010-006 | Security | MEDIUM | 246 | f-string in SQL for username - use parameterized query | security | Use `%s` parameter substitution |

**Compliant Patterns**: Uses modern type syntax (but requires future annotations)

#### File: pulldb/infra/platform_detect.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 82%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-011-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: shared` in module docstring | hca.md §Law2 | Add `HCA Layer: shared` to docstring |
| B03-011-002 | Python | CRITICAL | 34 | Uses runtime `typing` module unnecessarily | python.md §Imports | Use TYPE_CHECKING guard |
| B03-011-003 | Python | HIGH | 171 | Uses `dict[str, Any]` - could use TypedDict | python.md §TypeHints | Consider TypedDict for known structures |
| B03-011-004 | Error | MEDIUM | 141 | Bare `except Exception` with pragma - add justification | fail-hard.md | Add comment explaining why needed |
| B03-011-005 | Code | MEDIUM | 141+ | Multiple `# pragma: no cover` - minimize exclusions | python.md | Review coverage exclusions |

**Compliant Patterns**: ✅ Has future annotations, ✅ Modern `X | None` syntax, ✅ Good dataclass usage

#### File: pulldb/infra/s3.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-012-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: shared` in module docstring | hca.md §Law2 | Add `HCA Layer: shared` to docstring |
| B03-012-002 | Python | HIGH | 32 | Imports `Callable` when could be avoided | python.md §Imports | Use Protocol or collections.abc.Callable |
| B03-012-003 | Error | MEDIUM | 298-301 | Catches `Exception` - very broad | fail-hard.md | Catch specific boto3/botocore exceptions |
| B03-012-004 | Error | MEDIUM | 388-390 | Same broad exception pattern | fail-hard.md | Catch specific exceptions |

**Compliant Patterns**: ✅ Has future annotations, ✅ Modern `X | None` syntax

#### File: pulldb/infra/secrets.py

**Status**: ✅ Analyzed
**HCA Layer**: shared | **Expected**: shared ✅
**Compliance Score**: 98%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B03-013-001 | Code | LOW | - | Silent fallback to defaults when parsing env vars | fail-hard.md | Consider explicit error handling or logging |

**Compliant Patterns**: ✅ Has HCA Layer docstring, ✅ Has future annotations, ✅ Well-documented constants

---

### Batch B04: pulldb/domain/ (root)

**Status**: ✅ Complete
**Files**: 11
**Analysis Date**: 2026-01-19
**Analyst**: Sub-agent
**Total Findings**: 35
**Severity**: CRIT: 2 | HIGH: 8 | MED: 14 | LOW: 11
**Avg Compliance**: 81%

#### File: pulldb/domain/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 30%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-001-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: entities` in module docstring | hca.md §Law2 | Add `HCA Layer: entities` to docstring |
| B04-001-002 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B04-001-003 | Code | LOW | - | Minimal module - only exports `PullDBError` | python.md §Exports | Consider exporting more domain classes |

**Compliant Patterns**: Minimal `__init__.py` file

#### File: pulldb/domain/color_schemas.py

**Status**: ✅ Analyzed
**HCA Layer**: entities | **Expected**: entities ✅
**Compliance Score**: 98%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-002-001 | Python | LOW | - | Factory methods use string `"ColorSchema"` instead of `Self` type | python.md §TypeHints | Consider using `Self` from typing_extensions |

**Compliant Patterns**: ✅ HCA Layer docstring, ✅ Future annotations, ✅ Modern type hints, ✅ Google-style docstrings, ✅ Properly typed dataclasses

#### File: pulldb/domain/config.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-003-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: entities` in module docstring | hca.md §Law2 | Add `HCA Layer: entities` to docstring |
| B04-003-002 | Python | MEDIUM | 22 | Complex import pattern with `if TYPE_CHECKING` - prefer direct imports | python.md §Imports | Simplify import structure |
| B04-003-003 | Code | LOW | 191 | `# noqa: PLC0415` without inline justification | python.md §Noqa | Add brief comment explaining suppression |
| B04-003-004 | Docstrings | LOW | - | Private functions lack docstrings (acceptable for helpers) | python.md §Docstrings | Optional: add brief docstrings |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ `__slots__` for performance, ✅ Exception chaining

#### File: pulldb/domain/errors.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 92%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-004-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: entities` in module docstring | hca.md §Law2 | Add `HCA Layer: entities` to docstring |
| B04-004-002 | Docstrings | MEDIUM | 519 | `BackupDownloadError` class has minimal docstring | python.md §Docstrings | Add Args/Raises sections |
| B04-004-003 | Code | LOW | - | `BackupDownloadError` inherits from `Exception` not `PullDBError` | python.md §Exceptions | Consider consistent base class |

**Compliant Patterns**: ✅ Future annotations, ✅ FAIL HARD diagnostic structure, ✅ Modern type hints, ✅ Rich exception context

#### File: pulldb/domain/feature_request.py

**Status**: ✅ Analyzed
**HCA Layer**: entities | **Expected**: entities ✅
**Compliance Score**: 65%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-005-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B04-005-002 | Python | HIGH | 7 | Uses legacy `Optional` instead of `X | None` | python.md §ModernTypes | Replace with modern syntax |
| B04-005-003 | Python | HIGH | 7 | Imports `Optional` from typing (legacy) | python.md §Imports | Remove typing import |
| B04-005-004 | Docstrings | MEDIUM | - | Pydantic models lack comprehensive field docstrings | python.md §Docstrings | Add field descriptions |
| B04-005-005 | HCA | LOW | 1 | HCA Layer declared but inconsistent format | hca.md §Law2 | Standardize format |

**Compliant Patterns**: ✅ Using Pydantic for validation, ✅ Enum for status values

#### File: pulldb/domain/interfaces.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 88%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-006-001 | HCA | HIGH | 1 | Mentions "HCA Compliance" but missing `HCA Layer: entities` format | hca.md §Law2 | Add standard HCA Layer declaration |
| B04-006-002 | Docstrings | MEDIUM | - | Protocol methods use `...` body - some lack complete docstrings | python.md §Docstrings | Complete method docstrings |
| B04-006-003 | Docstrings | MEDIUM | - | Some method docstrings appear truncated | python.md §Docstrings | Review and complete docstrings |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ Protocol-based interfaces, ✅ Method docstrings present

#### File: pulldb/domain/models.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-007-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: entities` in module docstring | hca.md §Law2 | Add `HCA Layer: entities` to docstring |
| B04-007-002 | Python | MEDIUM | 306+ | Inline `import json` inside methods - should be module-level | python.md §Imports | Move imports to top of file |
| B04-007-003 | Python | MEDIUM | 400 | Dataclass missing `__slots__` decorator (verify) | python.md §Performance | Add `__slots__` if applicable |
| B04-007-004 | Python | LOW | - | `list` in frozen dataclass - consider `tuple` for immutability | python.md §Immutability | Consider tuple for frozen fields |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ Frozen dataclasses, ✅ Comprehensive docstrings

#### File: pulldb/domain/naming.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 95%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-008-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: entities` in module docstring | hca.md §Law2 | Add `HCA Layer: entities` to docstring |
| B04-008-002 | Python | LOW | 74 | Explicit type annotation not strictly needed | python.md §TypeHints | Optional: remove redundant annotation |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ Frozen dataclasses, ✅ Comprehensive docstrings with Examples, ✅ `__all__` export list

#### File: pulldb/domain/permissions.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-009-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: entities` in module docstring | hca.md §Law2 | Add `HCA Layer: entities` to docstring |
| B04-009-002 | Docstrings | MEDIUM | - | Some functions lack `Raises` sections | python.md §Docstrings | Add Raises documentation |
| B04-009-003 | Code | LOW | - | `is_pulldb_admin` naming could conflict conceptually | python.md §Naming | Consider renaming for clarity |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ Comprehensive function docstrings, ✅ Permission matrix documentation

#### File: pulldb/domain/restore_models.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-010-001 | HCA | HIGH | 1 | Missing explicit `HCA Layer: entities` in module docstring | hca.md §Law2 | Add `HCA Layer: entities` to docstring |
| B04-010-002 | Docstrings | MEDIUM | - | Private `_create_*` functions lack docstrings | python.md §Docstrings | Add brief docstrings |
| B04-010-003 | Python | MEDIUM | - | Uses `Literal` correctly for type safety | - | (Informational - good pattern) |
| B04-010-004 | Code | LOW | - | Long NOTE comment at top could be documentation | python.md §Comments | Consider moving to docs |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ `__slots__` for performance, ✅ Good public docstrings

#### File: pulldb/domain/settings.py

**Status**: ✅ Analyzed
**HCA Layer**: entities | **Expected**: entities ✅
**Compliance Score**: 95%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B04-011-001 | Code | LOW | 18 | `# noqa: PLC2701` without inline justification | python.md §Noqa | Add brief comment |
| B04-011-002 | Python | LOW | - | `list` in frozen dataclass - consider `tuple` | python.md §Immutability | Consider tuple for validators |

**Compliant Patterns**: ✅ HCA Layer docstring, ✅ Future annotations, ✅ Modern type hints, ✅ Frozen dataclasses, ✅ Enum with docstrings

---

### Batch B05: pulldb/domain/services/

**Status**: ✅ Complete
**Files**: 4
**Analysis Date**: 2026-01-19
**Analyst**: Sub-agent
**Total Findings**: 11
**Severity**: CRIT: 1 | HIGH: 4 | MED: 4 | LOW: 2
**Avg Compliance**: 79%

#### File: pulldb/domain/services/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 20%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B05-001-001 | HCA | HIGH | 1 | Empty file missing HCA layer docstring | hca.md §Law2 | Add `"""Domain services.\n\nHCA Layer: entities\n"""` |
| B05-001-002 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: Empty `__init__.py` - needs basic structure

#### File: pulldb/domain/services/discovery.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 82%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B05-002-001 | HCA | HIGH | 1 | Module docstring missing `HCA Layer: entities` declaration | hca.md §Law2 | Add HCA layer to existing docstring |
| B05-002-002 | Error | MEDIUM | 217-221 | `except Exception: pass` silently swallows all exceptions | fail-hard.md | Add logging or specific handling |
| B05-002-003 | Error | MEDIUM | 137+ | Multiple bare exception handlers without logging | fail-hard.md | Add logging at lines 137, 153, 279-282, 344 |
| B05-002-004 | Python | LOW | 10 | Uses `TypeVar` with `Callable` - prefer explicit `Protocol` | python.md §TypeHints | Optional: use Protocol for clarity |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type syntax, ✅ Google-style docstrings, ✅ Properly typed dataclasses

#### File: pulldb/domain/services/provisioning.py

**Status**: ✅ Analyzed
**HCA Layer**: features | **Expected**: entities ⚠️
**Compliance Score**: 92%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B05-003-001 | HCA | HIGH | 1 | Declares `HCA Layer: features` but file is in `domain/services/` (entities) | hca.md §Law1 | Review: Either move to features layer or correct docstring |
| B05-003-002 | Python | LOW | 31 | `Callable` import from typing - minor legacy pattern | python.md §Imports | Consider collections.abc.Callable |

**Compliant Patterns**: ✅ Future annotations, ✅ HCA docstring present (layer mismatch), ✅ Excellent docstrings, ✅ Protocol classes, ✅ FAIL HARD pattern, ✅ Structured result classes

**Note**: This file's HCA layer declaration (`features`) may actually be correct for its functionality - provisioning orchestration is business logic. Consider moving to `pulldb/worker/` or updating directory structure.

#### File: pulldb/domain/services/secret_rotation.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: entities
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B05-004-001 | HCA | HIGH | 1 | Module docstring missing `HCA Layer: entities` declaration | hca.md §Law2 | Add HCA layer to existing docstring |
| B05-004-002 | Error | MEDIUM | 139-141 | Broad `except Exception` without re-raising | fail-hard.md | Use specific exceptions or add logging |
| B05-004-003 | Error | MEDIUM | 249-250 | Broad exception handling for resolver errors | fail-hard.md | Catch specific resolver exceptions |

**Compliant Patterns**: ✅ Future annotations, ✅ Excellent WORKFLOW docstring, ✅ Modern type syntax, ✅ FAIL HARD pattern with actionable suggestions, ✅ Phase-based timing, ✅ Rollback handling

---

### Batch B06: pulldb/worker/ (core)

**Status**: ✅ Complete
**Files**: 10
**Analysis Date**: 2026-01-19
**Analyst**: Sub-agent
**Total Findings**: 41
**Severity**: CRIT: 2 | HIGH: 14 | MED: 17 | LOW: 8
**Avg Compliance**: 72%

#### File: pulldb/worker/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: widgets
**Compliance Score**: 50%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B06-001-001 | HCA | HIGH | 1 | Missing `HCA Layer: widgets` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B06-001-002 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: Simple `__init__.py` with exports

#### File: pulldb/worker/service.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: widgets
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B06-002-001 | HCA | HIGH | 1 | Missing `HCA Layer: widgets` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B06-002-002 | Error | MEDIUM | 78 | Bare `except ValueError: pass` without logging | fail-hard.md | Add logging or explicit handling |
| B06-002-003 | Code | LOW | 139-145 | DEBUG log with string interpolation | python.md | Gate behind debug flag |
| B06-002-004 | Docstrings | MEDIUM | 266 | Function missing Returns section | python.md §Docstrings | Add Returns documentation |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type syntax, ✅ Structured logging

#### File: pulldb/worker/executor.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 82%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B06-003-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B06-003-002 | Python | MEDIUM | 413 | Uses `Any` types without justification | python.md §TypeHints | Add type stubs or inline comments |
| B06-003-003 | Python | LOW | 430-446 | Complex Callable signatures | python.md §TypeHints | Consider Protocol classes |
| B06-003-004 | Error | MEDIUM | 399 | `except OSError: pass` without logging | fail-hard.md | Add logging in cleanup |
| B06-003-005 | Docstrings | MEDIUM | 521 | Large internal method (~200 lines) without docstring | python.md §Docstrings | Add function docstring |

**Compliant Patterns**: ✅ Future annotations, ✅ Dataclass usage, ✅ Exception chaining

#### File: pulldb/worker/restore.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 80%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B06-004-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B06-004-002 | Python | HIGH | 21 | Uses `Path` but inconsistent with other files using `pathlib.Path` | python.md §Imports | Standardize import pattern |
| B06-004-003 | Error | MEDIUM | 245 | `except Exception: pass` in metadata reading | fail-hard.md | Add logging for warning |
| B06-004-004 | Docstrings | LOW | 305 | Complex internal function (~100 lines) without docstring | python.md §Docstrings | Add function docstring |
| B06-004-005 | Code | MEDIUM | 74 | Unused `Callable` import inconsistency | python.md §Imports | Clean up unused imports |

**Compliant Patterns**: ✅ Future annotations, ✅ Google-style docstrings, ✅ Structured logging

#### File: pulldb/worker/downloader.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B06-005-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B06-005-002 | Error | MEDIUM | 99 | Catches broad `Exception` with pragma comment | fail-hard.md | Catch specific boto3/botocore exceptions |
| B06-005-003 | Docstrings | LOW | - | `_stream_download` missing Raises section | python.md §Docstrings | Add Raises documentation |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type syntax, ✅ Good error handling

#### File: pulldb/worker/staging.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 70%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B06-006-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B06-006-002 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B06-006-003 | Python | HIGH | 17 | Uses `Optional` - should use modern `X | None` | python.md §ModernTypes | Replace with modern syntax |
| B06-006-004 | Error | MEDIUM | 290 | Catches `Exception` then raises custom error | fail-hard.md | Use more specific exception types |
| B06-006-005 | Code | LOW | 135 | Redundant public/private wrapper function | python.md | Consider consolidating |

**Compliant Patterns**: ✅ Dataclass usage, ✅ Structured error messages

#### File: pulldb/worker/atomic_rename.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 78%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B06-007-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B06-007-002 | Python | HIGH | 27 | Uses `Optional` - inconsistent with modern syntax | python.md §ModernTypes | Replace with `X | None` |
| B06-007-003 | Security | MEDIUM | 353-364 | f-string SQL construction pattern | security | Review for injection risk |
| B06-007-004 | Error | MEDIUM | 374 | Exception in loop with `last_exc` pattern - could mask failures | fail-hard.md | Review exception handling logic |
| B06-007-005 | Code | LOW | - | Function (170+ lines) - consider extracting helpers | python.md §FunctionLength | Refactor into smaller functions |

**Compliant Patterns**: ✅ Future annotations, ✅ Structured logging, ✅ Transactional patterns

#### File: pulldb/worker/post_sql.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 88%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B06-008-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B06-008-002 | Code | LOW | 17-23 | `# ruff: noqa: I001` directive disables import ordering | python.md §Imports | Fix imports instead of disabling |
| B06-008-003 | Python | MEDIUM | 22 | Mixed import sources for `Callable` and `Sequence` | python.md §Imports | Standardize import sources |

**Compliant Patterns**: ✅ Future annotations, ✅ Good docstrings, ✅ Clean function signatures

#### File: pulldb/worker/cleanup.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 55%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B06-009-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B06-009-002 | Python | HIGH | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B06-009-003 | Python | MEDIUM | 27-35 | TYPE_CHECKING uses string annotations instead of direct refs | python.md §TypeHints | Use future annotations |
| B06-009-004 | Code | MEDIUM | - | File is 2727 lines - consider splitting | python.md §FileSize | Split into modules |
| B06-009-005 | Docstrings | MEDIUM | - | Large functions need docstring verification | python.md §Docstrings | Verify all large functions documented |

**Compliant Patterns**: ✅ Structured cleanup operations, ✅ Comprehensive logging

#### File: pulldb/worker/loop.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: widgets
**Compliance Score**: 75%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B06-010-001 | HCA | HIGH | 1 | Missing `HCA Layer: widgets` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B06-010-002 | Python | MEDIUM | 39-40 | TYPE_CHECKING uses string annotations | python.md §TypeHints | Use future annotations |
| B06-010-003 | Code | MEDIUM | 72-387 | `run_worker_loop` is 315+ lines | python.md §FunctionLength | Break into smaller functions |
| B06-010-004 | Code | LOW | - | "legacy/mocked name" comment needs cleanup | python.md §Comments | Clean up or document properly |

**Compliant Patterns**: ✅ Future annotations, ✅ Main loop orchestration, ✅ Graceful shutdown handling

---

### Batch B07: pulldb/worker/ (support)

**Status**: ✅ Complete
**Files**: 11
**Analysis Date**: 2026-01-20
**Analyst**: Sub-agent dispatch
**Total Findings**: 31
**Severity Breakdown**: [CRIT: 1 | HIGH: 8 | MED: 13 | LOW: 9]
**Average Compliance Score**: 79%

---

#### File: pulldb/worker/admin_tasks.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 72%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-001-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B07-001-002 | Error | MEDIUM | multiple | Broad `except Exception:` handlers | fail-hard.md | Add specific exception types |
| B07-001-003 | Docstrings | LOW | - | Some functions missing docstrings | python.md §Docstrings | Add Google-style docstrings |
| B07-001-004 | Code | LOW | - | Consider extracting common patterns | python.md §DRY | Refactor repeated code |

**Compliant Patterns**: ✅ Future annotations, ✅ Structured logging

---

#### File: pulldb/worker/backup_metadata.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ features | **Expected**: features
**Compliance Score**: 95%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-002-001 | Error | MEDIUM | - | Broad exception handlers could be more specific | fail-hard.md | Narrow exception types |
| B07-002-002 | Docstrings | LOW | - | Minor docstring improvements possible | python.md §Docstrings | Enhance documentation |

**Compliant Patterns**: ✅ HCA docstring present, ✅ Future annotations, ✅ Clean structure

---

#### File: pulldb/worker/dump_metadata.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ features | **Expected**: features
**Compliance Score**: 88%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-003-001 | Error | MEDIUM | - | Broad exception catch patterns | fail-hard.md | Add specific exception types |
| B07-003-002 | Code | MEDIUM | - | Some functions could be decomposed | python.md §FunctionLength | Extract helper functions |
| B07-003-003 | Docstrings | LOW | - | Docstring consistency improvements | python.md §Docstrings | Standardize format |

**Compliant Patterns**: ✅ HCA docstring present, ✅ Future annotations, ✅ Metadata handling

---

#### File: pulldb/worker/feature_request_service.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ features | **Expected**: features
**Compliance Score**: 78%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-004-001 | Error | HIGH | - | Multiple broad exception handlers | fail-hard.md | Narrow exception types with logging |
| B07-004-002 | Error | MEDIUM | - | Exception chaining missing in some places | fail-hard.md | Add `raise ... from e` |
| B07-004-003 | Code | MEDIUM | - | Long functions could be split | python.md §FunctionLength | Extract helpers |
| B07-004-004 | Docstrings | LOW | - | Some functions need better documentation | python.md §Docstrings | Add comprehensive docstrings |
| B07-004-005 | Code | LOW | - | Magic strings could be constants | python.md §Constants | Extract to named constants |

**Compliant Patterns**: ✅ HCA docstring present, ✅ Future annotations, ✅ Service pattern

---

#### File: pulldb/worker/heartbeat.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-005-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B07-005-002 | Error | MEDIUM | - | Exception handlers could be more specific | fail-hard.md | Narrow exception types |
| B07-005-003 | Docstrings | LOW | - | Minor documentation improvements | python.md §Docstrings | Enhance docstrings |

**Compliant Patterns**: ✅ Future annotations, ✅ Clean heartbeat logic, ✅ Proper MySQL integration

---

#### File: pulldb/worker/log_normalizer.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 70%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-006-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B07-006-002 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B07-006-003 | Python | MEDIUM | - | Uses `Optional` instead of `X | None` | python.md §ModernTypes | Update type hints |
| B07-006-004 | Error | MEDIUM | - | Broad exception handlers | fail-hard.md | Add specific exceptions |
| B07-006-005 | Code | LOW | - | Regex patterns could be compiled constants | python.md §Constants | Extract to module level |

**Compliant Patterns**: ✅ Log normalization logic, ✅ Structured output

---

#### File: pulldb/worker/metadata.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-007-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B07-007-002 | Error | MEDIUM | - | Exception handling could be more specific | fail-hard.md | Narrow exception types |
| B07-007-003 | Code | LOW | - | Consider extracting helper functions | python.md §DRY | Refactor for clarity |

**Compliant Patterns**: ✅ Future annotations, ✅ Clean metadata handling

---

#### File: pulldb/worker/metadata_synthesis.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 68%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-008-001 | Python | HIGH | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B07-008-002 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B07-008-003 | Python | MEDIUM | - | Uses legacy `Optional` type hints | python.md §ModernTypes | Replace with `X | None` |
| B07-008-004 | Error | MEDIUM | - | Broad exception patterns | fail-hard.md | Narrow exception types |
| B07-008-005 | Code | MEDIUM | - | Complex functions need decomposition | python.md §FunctionLength | Split large functions |
| B07-008-006 | Docstrings | LOW | - | Inconsistent docstring coverage | python.md §Docstrings | Add missing docstrings |

**Compliant Patterns**: ✅ Synthesis logic, ✅ Structured processing

---

#### File: pulldb/worker/processlist_monitor.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ features | **Expected**: features
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-009-001 | Error | MEDIUM | - | Broad exception handlers in monitoring | fail-hard.md | Add specific exception types |
| B07-009-002 | Code | MEDIUM | - | Consider extracting query builders | python.md §DRY | Extract repeated patterns |
| B07-009-003 | Docstrings | LOW | - | Some functions need documentation | python.md §Docstrings | Add docstrings |
| B07-009-004 | Code | LOW | - | Magic numbers in thresholds | python.md §Constants | Extract to named constants |

**Compliant Patterns**: ✅ HCA docstring present, ✅ Future annotations, ✅ Monitoring pattern

---

#### File: pulldb/worker/profiling.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 88%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-010-001 | HCA | HIGH | 1 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B07-010-002 | Error | MEDIUM | - | Exception handlers could be narrowed | fail-hard.md | Add specific exception types |
| B07-010-003 | Docstrings | LOW | - | Profiling functions need docs | python.md §Docstrings | Add docstrings |
| B07-010-004 | Code | LOW | - | Context managers could improve cleanup | python.md §ContextManagers | Use context managers |

**Compliant Patterns**: ✅ Future annotations, ✅ Profiling patterns, ✅ Performance tracking

---

#### File: pulldb/worker/retention.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ features | **Expected**: features
**Compliance Score**: 82%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B07-011-001 | Error | MEDIUM | - | Broad exception handlers in retention logic | fail-hard.md | Narrow exception types |
| B07-011-002 | Code | LOW | - | Consider extracting policy helpers | python.md §DRY | Extract helper functions |
| B07-011-003 | Docstrings | LOW | - | Retention policies need better docs | python.md §Docstrings | Document retention rules |

**Compliant Patterns**: ✅ HCA docstring present, ✅ Future annotations, ✅ Retention policy handling

---

### Batch B08: pulldb/auth/

**Status**: ✅ Complete
**Files**: 2
**Analysis Date**: 2026-01-20
**Analyst**: Sub-agent dispatch
**Total Findings**: 6
**Severity Breakdown**: [CRIT: 0 | HIGH: 2 | MED: 3 | LOW: 1]
**Average Compliance Score**: 82%

---

#### File: pulldb/auth/password.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B08-001-001 | HCA | HIGH | 1-7 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B08-001-002 | Error | MEDIUM | 63-66 | Broad exception without exception chaining | fail-hard.md | Use specific exceptions or add `from e` |
| B08-001-003 | Error | LOW | 89-91 | Silent catch of parse error - should log | fail-hard.md | Add debug logging for parse failures |

**Compliant Patterns**: ✅ Future annotations present, ✅ Modern type hints (no legacy imports), ✅ Google-style docstrings, ✅ Actionable error messages, ✅ Well-documented constants

---

#### File: pulldb/auth/repository.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 80%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B08-002-001 | HCA | HIGH | 1-6 | Missing `HCA Layer: features` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B08-002-002 | Code | MEDIUM | 67 | Uses f-string in logger (security/performance) | python.md §Logging | Use `%s` format style |
| B08-002-003 | Security | MEDIUM | 858-861 | Uses f-string for SQL query construction | security | Use parameterized queries |

**Compliant Patterns**: ✅ Future annotations present, ✅ Modern type hints throughout, ✅ Comprehensive Google-style docstrings, ✅ Proper layer imports (entities, shared only), ✅ Custom exceptions with actionable messages, ✅ Uses `type` keyword (Python 3.11+)

---

### Batch B09: pulldb/simulation/core/

**Status**: ✅ Complete
**Files**: 7
**Analysis Date**: 2026-01-20
**Analyst**: Sub-agent dispatch
**Total Findings**: 23
**Severity Breakdown**: [CRIT: 1 | HIGH: 5 | MED: 12 | LOW: 5]
**Average Compliance Score**: 76%

---

#### File: pulldb/simulation/core/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 20%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B09-001-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B09-001-002 | HCA | HIGH | 1 | No module docstring, HCA layer not declared | hca.md §Law2 | Add docstring with `HCA Layer: features` |
| B09-001-003 | Docstrings | LOW | 1 | Only has a comment, not a proper docstring | python.md §Docstrings | Convert to triple-quoted docstring |

**Compliant Patterns**: Minimal file

---

#### File: pulldb/simulation/core/bus.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B09-002-001 | HCA | HIGH | 1-5 | Missing `HCA Layer:` declaration in docstring | hca.md §Law2 | Add `HCA Layer: features` |
| B09-002-002 | Python | MEDIUM | 11 | Uses `type[X]` convention (verbose) | python.md §TypeHints | Consistent with project style |
| B09-002-003 | Error | MEDIUM | 143-144 | Broad exception without re-raise | fail-hard.md | Consider re-raising or specific exceptions |
| B09-002-004 | Error | MEDIUM | 149-150 | Broad exception without re-raise | fail-hard.md | Consider re-raising or specific exceptions |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ Google-style docstrings, ✅ Dataclasses for events

---

#### File: pulldb/simulation/core/engine.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 70%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B09-003-001 | HCA | HIGH | 1-4 | Missing `HCA Layer:` declaration in docstring | hca.md §Law2 | Add `HCA Layer: features` |
| B09-003-002 | Docstrings | MEDIUM | 20 | `EngineConfig` dataclass missing docstring | python.md §Docstrings | Add class docstring |
| B09-003-003 | Docstrings | MEDIUM | 33 | `start` method missing docstring | python.md §Docstrings | Add docstring describing initialization |
| B09-003-004 | Docstrings | MEDIUM | 38 | `tick` method missing docstring | python.md §Docstrings | Add docstring explaining tick behavior |
| B09-003-005 | Docstrings | MEDIUM | 42 | `stop` method missing docstring | python.md §Docstrings | Add Google-style docstring with Args |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ Uses `datetime.UTC`

---

#### File: pulldb/simulation/core/queue_runner.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ features | **Expected**: features
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B09-004-001 | Code | LOW | 15 | Uses `TYPE_CHECKING` import correctly | python.md §TypeHints | Good pattern |
| B09-004-002 | Docstrings | LOW | 225 | Private method has minimal docstring | python.md §Docstrings | Consider adding Args/Returns (optional) |

**Compliant Patterns**: ✅ Future annotations, ✅ HCA Layer declared, ✅ Modern type hints, ✅ Google-style docstrings, ✅ Configuration validation

---

#### File: pulldb/simulation/core/scenarios.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 82%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B09-005-001 | HCA | HIGH | 1-5 | Missing `HCA Layer:` declaration in docstring | hca.md §Law2 | Add `HCA Layer: features` |
| B09-005-002 | Python | MEDIUM | 11 | Uses `type[X]` convention | python.md §TypeHints | Consistent with project style |
| B09-005-003 | Docstrings | MEDIUM | 388 | Method docstring missing Args section | python.md §Docstrings | Add Args/Returns sections |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ TYPE_CHECKING for forward refs, ✅ ValueError with descriptive messages

---

#### File: pulldb/simulation/core/seeding.py

**Status**: ✅ Analyzed
**HCA Layer**: ⚠️ shared (incorrect) | **Expected**: features
**Compliance Score**: 78%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B09-006-001 | HCA | HIGH | 8 | HCA Layer declared as `shared` but should be `features` | hca.md §Law2 | Change to `HCA Layer: features` - seeding is simulation business logic |
| B09-006-002 | Python | MEDIUM | 21 | Redundant import | python.md §Imports | Consolidate imports |
| B09-006-003 | Error | MEDIUM | 666-667 | Exception silently swallowed | fail-hard.md | Log the error before continuing |
| B09-006-004 | Python | LOW | 17 | Uses `type[X]` convention | python.md §TypeHints | Consistent with project style |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ ValueError with descriptive messages, ✅ Organized sections

---

#### File: pulldb/simulation/core/state.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 80%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B09-007-001 | HCA | HIGH | 1-4 | Missing `HCA Layer:` declaration in docstring | hca.md §Law2 | Add `HCA Layer: shared` (state is infrastructure-like) |
| B09-007-002 | Docstrings | MEDIUM | 75 | Method missing docstring body | python.md §Docstrings | Expand docstring with behavior details |
| B09-007-003 | Docstrings | LOW | 101 | `reset` docstring could describe cleared state | python.md §Docstrings | Expand to list all cleared state |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ Thread-safe with RLock, ✅ Singleton pattern with __new__

---

### Batch B10: pulldb/simulation/adapters/

**Status**: ✅ Complete
**Files**: 4
**Analysis Date**: 2026-01-20
**Analyst**: Sub-agent dispatch
**Total Findings**: 18
**Severity Breakdown**: [CRIT: 1 | HIGH: 4 | MED: 8 | LOW: 5]
**Average Compliance Score**: 72%

---

#### File: pulldb/simulation/adapters/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 25%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B10-001-001 | HCA | HIGH | 1 | Missing `HCA Layer: shared` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B10-001-002 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B10-001-003 | Docstrings | MEDIUM | 1-2 | Module docstring lacks detail about exports | python.md §Docstrings | Expand to document public API |

**Compliant Patterns**: Minimal file

---

#### File: pulldb/simulation/adapters/mock_exec.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 78%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B10-002-001 | HCA | HIGH | 1-6 | Missing `HCA Layer: shared` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B10-002-002 | Docstrings | MEDIUM | 49-54 | Method lacks Google-style docstring | python.md §Docstrings | Add Args/Returns |
| B10-002-003 | Docstrings | MEDIUM | 56-62 | Method lacks docstring | python.md §Docstrings | Add method docstring |
| B10-002-004 | Docstrings | MEDIUM | 64-67 | Minimal docstring, missing Args | python.md §Docstrings | Expand to Google-style |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ No legacy imports, ✅ Class docstrings

---

#### File: pulldb/simulation/adapters/mock_mysql.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 75%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B10-003-001 | HCA | HIGH | 1-5 | Missing `HCA Layer: shared` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B10-003-002 | Python | LOW | 14 | Uses `TYPE_CHECKING` with if statement | python.md §Imports | Use direct import |
| B10-003-003 | Docstrings | MEDIUM | multiple | Many methods missing Google-style docstrings | python.md §Docstrings | Add Args/Returns |
| B10-003-004 | Code | LOW | 1560-1562 | Import inside method | python.md §Imports | Move to module level |
| B10-003-005 | Code | LOW | 1096-1097 | Redundant import inside method | python.md §Imports | Already imported at module level |
| B10-003-006 | Error | MEDIUM | 1311, 1334, 1580 | Uses hasattr for enum status check | fail-hard.md | Check membership rather than catching |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ Thread-safety documented, ✅ dataclass replace() usage

---

#### File: pulldb/simulation/adapters/mock_s3.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: shared
**Compliance Score**: 82%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B10-004-001 | HCA | HIGH | 1-4 | Missing `HCA Layer: shared` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B10-004-002 | Python | LOW | 8 | Uses TYPE_CHECKING pattern | python.md §Imports | Use direct import |
| B10-004-003 | Docstrings | MEDIUM | 23-31 | Init lacks Google-style Args docstring | python.md §Docstrings | Add Args section |
| B10-004-004 | Docstrings | LOW | 71-163 | Some methods have minimal docstrings | python.md §Docstrings | Expand with Args/Returns |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ Class docstrings, ✅ Error class inherits properly

---

### Batch B11: pulldb/simulation/api/

**Status**: ✅ Complete
**Files**: 2
**Analysis Date**: 2026-01-20
**Analyst**: Sub-agent dispatch
**Total Findings**: 5
**Severity Breakdown**: [CRIT: 1 | HIGH: 1 | MED: 3 | LOW: 0]
**Average Compliance Score**: 75%

---

#### File: pulldb/simulation/api/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 50%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B11-001-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B11-001-002 | HCA | HIGH | 1-5 | Missing `HCA Layer: pages` in module docstring | hca.md §Law2 | Add HCA layer designation |

**Compliant Patterns**: Has module docstring, clean export pattern

---

#### File: pulldb/simulation/api/router.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: pages
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B11-002-001 | HCA | HIGH | 1-8 | Missing `HCA Layer: pages` in module docstring | hca.md §Law2 | Add HCA layer designation |
| B11-002-002 | Python | MEDIUM | 11 | Uses typing alias, minor style inconsistency | python.md §Imports | Consider direct imports |
| B11-002-003 | Error | MEDIUM | 221-225, 330-336 | Uses `raise ... from None` which suppresses context | fail-hard.md | Use `from e` to preserve chain |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ Pydantic models with docstrings, ✅ Google-style endpoint docstrings, ✅ HTTPException with proper status codes

---

### Batch B12: pulldb/web/shared/

**Status**: ✅ Complete
**Files**: 7
**Analysis Date**: 2026-01-19
**Analyst**: Sub-agent dispatch
**Total Findings**: 8
**Severity Breakdown**: [CRIT: 4 | HIGH: 0 | MED: 0 | LOW: 4]
**Average Compliance Score**: 86%

---

#### File: pulldb/web/shared/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ declared ("HCA Layer 0") | **Expected**: shared
**Compliance Score**: 75%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B12-001-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B12-001-002 | HCA | LOW | 1-5 | Uses "HCA Layer 0" instead of "HCA Layer: shared" | hca.md §Law2 | Use standard naming format |

**Compliant Patterns**: ✅ Has module docstring, ✅ Layer correctly identified

---

#### File: pulldb/web/shared/contracts/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ declared ("HCA Layer 0") | **Expected**: shared
**Compliance Score**: 75%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B12-002-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B12-002-002 | HCA | LOW | 1-5 | Uses "HCA Layer 0" instead of "HCA Layer: shared" | hca.md §Law2 | Use standard naming format |

**Compliant Patterns**: ✅ Has module docstring, ✅ Uses __all__ for exports, ✅ Clean re-export pattern

---

#### File: pulldb/web/shared/contracts/page_contracts.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ declared ("HCA Layer 0") | **Expected**: shared
**Compliance Score**: 95%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B12-003-001 | HCA | LOW | 1-5 | Uses "HCA Layer 0" instead of "HCA Layer: shared" | hca.md §Law2 | Use standard naming format |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ TYPE_CHECKING guard, ✅ All dataclasses/protocols have docstrings, ✅ Correct import direction

---

#### File: pulldb/web/shared/contracts/service_contracts.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ declared ("HCA Layer 0") | **Expected**: shared
**Compliance Score**: 95%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B12-004-001 | HCA | LOW | 1-5 | Uses "HCA Layer 0" instead of "HCA Layer: shared" | hca.md §Law2 | Use standard naming format |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints, ✅ TYPE_CHECKING guard, ✅ Protocol pattern for DI, ✅ All methods have docstrings

---

#### File: pulldb/web/shared/layouts/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ declared ("HCA Layer 0") | **Expected**: shared
**Compliance Score**: 75%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B12-005-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: ✅ Has module docstring with HCA layer, ✅ Marker file for HTML templates

---

#### File: pulldb/web/shared/ui/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ declared ("HCA Layer 0") | **Expected**: shared
**Compliance Score**: 75%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B12-006-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: ✅ Has module docstring with HCA layer, ✅ Identifies as UI atoms

---

#### File: pulldb/web/shared/utils/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ declared ("HCA Layer 0") | **Expected**: shared
**Compliance Score**: 100%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| — | — | — | — | No issues found | — | — |

**Compliant Patterns**: ✅ Has module docstring with HCA layer, ✅ Marker file, ✅ No issues

---

### Batch B13: pulldb/web/entities/

**Status**: ✅ Complete
**Files**: 1
**Analysis Date**: 2026-01-19
**Analyst**: Sub-agent dispatch
**Total Findings**: 3
**Severity Breakdown**: [CRIT: 1 | HIGH: 1 | MED: 0 | LOW: 1]
**Average Compliance Score**: 60%

---

#### File: pulldb/web/entities/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ⚠️ declared in comment (not docstring) | **Expected**: entities
**Compliance Score**: 60%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B13-001-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B13-001-002 | HCA | HIGH | 1-15 | HCA layer declared in comment, not module docstring | hca.md §Law2 | Convert comment block to triple-quoted docstring |
| B13-001-003 | Docstrings | LOW | 1-15 | Module uses comments instead of docstring | python.md §Docstrings | Use `"""..."""` format |

**Compliant Patterns**: ✅ HCA layer IS declared (Layer 1: Entities), ✅ Clear purpose statement, ✅ No invalid cross-layer deps, ✅ No business logic

---

### Batch B14: pulldb/web/features/

**Status**: ⬜ Pending

*(To be populated during analysis)*

---

### Batch B14: pulldb/web/features/

**Status**: ✅ Complete
**Files**: 18
**Analysis Date**: 2026-01-19
**Analyst**: Sub-agent dispatch
**Total Findings**: 47
**Severity Breakdown**: [CRIT: 14 | HIGH: 16 | MED: 13 | LOW: 4]
**Average Compliance Score**: 52%

---

#### File: pulldb/web/features/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 30%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B14-001-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B14-001-002 | HCA | HIGH | 1-4 | Missing `HCA Layer: features` in docstring | hca.md §Law2 | Add HCA layer |

**Compliant Patterns**: Has module docstring

---

#### File: pulldb/web/features/admin/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 20%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B14-002-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B14-002-002 | HCA | HIGH | 1 | Missing `HCA Layer: features` in docstring | hca.md §Law2 | Add HCA layer |

**Compliant Patterns**: Has basic module docstring

---

#### File: pulldb/web/features/admin/routes.py

**Status**: ✅ Analyzed
**HCA Layer**: Not declared | **Expected**: features
**Compliance Score**: 45%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B14-003-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B14-003-002 | HCA | HIGH | 1 | Missing `HCA Layer: features` in docstring | hca.md §Law2 | Add HCA layer |
| B14-003-003 | Python | HIGH | 3 | Legacy typing import: `Optional` | python.md §ModernTypes | Use `X \| None` |
| B14-003-004 | Error | MEDIUM | 70-72 | Broad exception without logging | fail-hard.md | Log exception |
| B14-003-005 | Error | MEDIUM | 201-202 | Broad exception returns generic message | fail-hard.md | Log with context |
| B14-003-006 | Error | MEDIUM | 232-233 | Broad exception returns generic message | fail-hard.md | Log with context |
| B14-003-007 | Error | MEDIUM | 264-265 | Broad exception | fail-hard.md | Log with context |

**Compliant Patterns**: ✅ Modern type hints for params, ✅ Google-style docstrings

---

#### File: pulldb/web/features/admin/theme_generator.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ declared | **Expected**: features
**Compliance Score**: 95%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B14-004-001 | Error | LOW | 105-107 | Bare exception with pass | fail-hard.md | Consider logging |
| B14-004-002 | Error | LOW | 111-113 | Bare exception with pass | fail-hard.md | Consider logging |

**Compliant Patterns**: ✅ Future annotations, ✅ HCA Layer declared, ✅ TYPE_CHECKING pattern, ✅ Google-style docstrings, ✅ Modern type hints - **GOLD STANDARD FILE**

---

#### Files: pulldb/web/features/{audit,auth,dashboard,jobs,manager,requests,restore}/__init__.py

**Status**: ✅ Analyzed (7 files with similar patterns)
**HCA Layer**: Mixed (3 declared, 4 not) | **Expected**: features
**Compliance Score**: 20-60%

| Pattern | Files Affected | Severity | Issue | Remediation |
|---------|---------------|----------|-------|-------------|
| Missing future annotations | 6 of 7 | CRITICAL | No `from __future__ import annotations` | Add as first import |
| Missing HCA layer | 4 of 7 | HIGH | No `HCA Layer: features` | Add to docstring |

**Files with HCA layer declared**: audit, requests, restore ✅
**Files missing HCA layer**: auth, dashboard, jobs, manager ❌

---

#### Files: pulldb/web/features/{audit,auth,dashboard,jobs,manager,requests,restore}/routes.py

**Status**: ✅ Analyzed (7 route files)
**HCA Layer**: Mixed (3 declared, 4 not) | **Expected**: features
**Compliance Score**: 40-70%

| Pattern | Files Affected | Severity | Issue | Remediation |
|---------|---------------|----------|-------|-------------|
| Missing future annotations | 6 of 7 | CRITICAL | No `from __future__ import annotations` | Add as first import |
| Missing HCA layer | 4 of 7 | HIGH | No `HCA Layer: features` | Add to docstring |
| Broad exception handlers | 5 of 7 | MEDIUM | `except Exception` without logging | Add logging |

**Files with HCA layer declared**: audit/routes, requests/routes, restore/routes ✅
**Files missing HCA layer**: admin/routes, auth/routes, dashboard/routes, jobs/routes, manager/routes ❌

**Compliant Patterns across route files**:
- ✅ Modern type hints (dict, list, Request, Response)
- ✅ Google-style docstrings on most handlers
- ✅ Proper FastAPI patterns
- ✅ Correct HCA imports from lower layers

---

### Batch B15: pulldb/web/widgets/

**Status**: ✅ Complete
**Files**: 8
**Analysis Date**: 2026-01-20
**Analyst**: Sub-agent dispatch
**Total Findings**: 17
**Severity Breakdown**: [CRIT: 8 | HIGH: 1 | MED: 1 | LOW: 7]
**Average Compliance Score**: 66%

---

#### File: pulldb/web/widgets/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Comment-style (# HCA Layer 3) | **Expected**: docstring format
**Compliance Score**: 50%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B15-001-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B15-001-002 | HCA | HIGH | 1-4 | Uses comment `# HCA Layer 3` instead of docstring `"""HCA Layer: widgets..."""` | hca.md §Law2 | Convert to docstring |
| B15-001-003 | Code Quality | LOW | - | Documentation-only file with no exports | - | Consider adding `__all__` |

**Compliant Patterns**: ✅ Clear documentation of widget subpackages

---

#### File: pulldb/web/widgets/breadcrumbs/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ Declared | **Expected**: widgets
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B15-002-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: ✅ HCA docstring, ✅ Modern type hints (`X | None`, `list[X]`), ✅ Immutable `@dataclass(frozen=True)`, ✅ Comprehensive `__all__` export list, ✅ Google-style docstrings

---

#### File: pulldb/web/widgets/bulk_actions/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ Declared | **Expected**: widgets
**Compliance Score**: 92%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B15-003-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: ✅ HCA docstring, ✅ Modern type hints, ✅ Immutable dataclasses, ✅ Comprehensive `__all__`, ✅ Google-style docstrings

---

#### File: pulldb/web/widgets/filter_bar/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ Declared | **Expected**: widgets
**Compliance Score**: 92%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B15-004-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: ✅ HCA docstring, ✅ Modern type hints (`list[str]`, `dict`, `Callable`), ✅ Role-based filtering logic, ✅ Comprehensive `__all__`

---

#### File: pulldb/web/widgets/lazy_table/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ Declared | **Expected**: widgets
**Compliance Score**: 92%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B15-005-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: ✅ HCA docstring with layer number, ✅ Explicit `__all__ = []` for frontend-only widget, ✅ Comprehensive documentation with usage examples

---

#### File: pulldb/web/widgets/searchable_dropdown/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ Declared | **Expected**: widgets
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B15-006-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B15-006-002 | Code Quality | LOW | - | Missing `__all__` export list | python.md | Add explicit exports |
| B15-006-003 | Docstrings | MEDIUM | - | Factory function could document error cases | python.md | Add Raises section |

**Compliant Patterns**: ✅ HCA docstring, ✅ Modern type hints, ✅ Class docstring with Attributes, ✅ Pre-defined config constants

---

#### File: pulldb/web/widgets/sidebar/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ Declared | **Expected**: widgets
**Compliance Score**: 40%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B15-007-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B15-007-002 | Code Quality | LOW | - | Stub file with only docstring, no implementation | - | Add implementation or note |
| B15-007-003 | Code Quality | LOW | - | Missing `__all__` (though file is empty) | - | Add `__all__ = []` |

**Notes**: File is placeholder - sidebar logic lives in `shared/layouts/partials` per root `__init__.py`

---

#### File: pulldb/web/widgets/virtual_table/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: ✅ Declared | **Expected**: widgets
**Compliance Score**: 92%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B15-008-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |

**Compliant Patterns**: ✅ HCA docstring with layer number, ✅ Explicit `__all__ = []` for frontend-only widget, ✅ Comprehensive documentation with usage examples

---

### B15 Patterns Observed

**Universal Issue** (ALL 8 files):
- Missing `from __future__ import annotations` - 8 CRITICAL findings

**Positive Patterns** (Strong Compliance):
- 7/8 files have proper HCA layer docstrings (only root `__init__.py` uses comment style)
- Modern type hints used consistently (`X | None` instead of `Optional[X]`)
- Immutable dataclasses (`@dataclass(frozen=True)`) for value objects
- Comprehensive `__all__` export lists in substantial files
- Frontend-only widgets properly documented with `__all__ = []`
- No bare exception handling violations detected

**Bulk Remediation Recommendation**:
```bash
# Add future annotations to all widget __init__.py files
for f in $(find pulldb/web/widgets -name "__init__.py"); do
  sed -i '1s/^/from __future__ import annotations\n\n/' "$f"
done
```

---

### Batch B16: pulldb/web/ (root)

**Status**: ✅ Complete
**Files**: 4
**Analysis Date**: 2026-01-20
**Analyst**: Sub-agent dispatch
**Total Findings**: 11
**Severity Breakdown**: [CRIT: 1 | HIGH: 3 | MED: 6 | LOW: 1]
**Average Compliance Score**: 82%

---

#### File: pulldb/web/__init__.py

**Status**: ✅ Analyzed
**HCA Layer**: Vague ("HCA Restructure Complete") | **Expected**: pages
**Compliance Score**: 65%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B16-001-001 | Python | CRITICAL | 1 | Missing `from __future__ import annotations` | python.md §FutureAnnotations | Add as first import |
| B16-001-002 | HCA | HIGH | 1-4 | Uses vague "HCA Restructure Complete" instead of `HCA Layer: pages` | hca.md §Law2 | Standardize docstring |
| B16-001-003 | Docstrings | LOW | - | Export-only module, docstring acceptable but could be more precise | - | Minor enhancement |

**Compliant Patterns**: ✅ Proper `__all__` exports

---

#### File: pulldb/web/dependencies.py

**Status**: ✅ Analyzed
**HCA Layer**: `Foundation` declared | **Expected**: pages
**Compliance Score**: 90%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B16-002-001 | HCA | HIGH | 1-10 | Declares `HCA Layer: Foundation` but web is `pages` layer | hca.md §Law2 | Update to `pages` |
| B16-002-002 | Error Handling | MEDIUM | 64,117,137,156 | Multiple bare `except Exception: pass` blocks without logging | fail-hard.md | Add logging |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern type hints (`X | None`, `list[X]`), ✅ Google-style docstrings, ✅ TYPE_CHECKING guards

---

#### File: pulldb/web/exceptions.py

**Status**: ✅ Analyzed
**HCA Layer**: `Foundation` declared | **Expected**: pages
**Compliance Score**: 88%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B16-003-001 | HCA | HIGH | 1-10 | Declares `HCA Layer: Foundation` but web is `pages` layer | hca.md §Law2 | Update to `pages` |
| B16-003-002 | Python | MEDIUM | 9 | Imports `Callable`, `Sequence` from `typing` - use `collections.abc` | python.md §ModernTypes | Migrate imports |
| B16-003-003 | Docstrings | MEDIUM | 47,53 | `RestoreError` and `ConfigError` lack detailed docstrings | python.md §Docstrings | Add docstrings |

**Compliant Patterns**: ✅ Future annotations, ✅ Modern union `X | None`, ✅ Good exception hierarchy, ✅ `dict[str, Any]` modern syntax

---

#### File: pulldb/web/router_registry.py

**Status**: ✅ Analyzed
**HCA Layer**: `Foundation` declared | **Expected**: pages
**Compliance Score**: 85%

| ID | Category | Severity | Line(s) | Issue | Standard | Remediation |
|----|----------|----------|---------|-------|----------|-------------|
| B16-004-001 | HCA | MEDIUM | 1-10 | Uses `HCA Layer: Foundation` but aggregates page-level routers | hca.md §Law2 | Update to `pages` |
| B16-004-002 | Docstrings | MEDIUM | - | `ALL_ROUTERS` list lacks inline comment explaining included routes | python.md | Add comments |

**Compliant Patterns**: ✅ Future annotations, ✅ Clear module docstring, ✅ Single responsibility, ✅ Proper `__all__` export

---

### B16 Patterns Observed

**Common Issue** (ALL 4 files):
- HCA Layer mislabeling: All use `Foundation` or vague language instead of `pages`
- Per HCA mapping: `pages/ → pulldb/web/` (entry points)

**Compliance Highlights**:
- 3/4 files have `from __future__ import annotations` ✅
- Modern type hints used throughout (`X | None`, `list[X]`)
- Good separation of concerns (exceptions, dependencies, registry)
- Proper use of `TYPE_CHECKING` guards for import cycles

**Silent Exception Concern**:
- `dependencies.py` has 4 bare `except Exception: pass` blocks that violate FAIL HARD principle

---

### Batch B17: pulldb/tests/

**Status**: ✅ Complete
**Files**: 73
**Analysis Date**: 2026-01-19
**Analyst**: Sub-agent dispatch (3 parts)
**Total Findings**: 7
**Severity Breakdown**: [CRIT: 7 | HIGH: 0 | MED: 0 | LOW: 0]
**Average Compliance Score**: 90%

---

#### B17 Summary: Test Package

**HIGHEST COMPLIANCE IN CODEBASE** - The test package shows excellent adoption of modern Python standards with 90% of files (66/73) fully compliant.

**All 7 CRITICAL findings are the same issue**: Missing `from __future__ import annotations` in small/stub files.

| ID | File | Severity | Issue |
|----|------|----------|-------|
| B17-001-001 | `__init__.py` | CRITICAL | Missing future annotations (empty stub) |
| B17-003-001 | `simulation/__init__.py` | CRITICAL | Missing future annotations (empty stub) |
| B17-028-001 | `test_imports.py` | CRITICAL | Missing future annotations |
| B17-030-001 | `test_installer_help.py` | CRITICAL | Missing future annotations |
| B17-045-001 | `test_myloader_command.py` | CRITICAL | Missing future annotations |
| B17-061-001 | `test_setup_test_env_script.py` | CRITICAL | Missing future annotations |
| B17-070-001 | `test_worker_failure_modes.py` | CRITICAL | Missing future annotations |

---

#### Compliant Files (66 files - 90%)

All files below have `from __future__ import annotations` and use modern type hints:

**Part 1 (Files 2, 4-25)**:
`conftest.py`, `test_simulation.py`, `test_api_auth_integration.py`, `test_api_auth_signed.py`, `test_api_jobs.py`, `test_atomic_rename.py`, `test_atomic_rename_benchmark.py`, `test_atomic_rename_deploy.py`, `test_atoms.py`, `test_auth_repository.py`, `test_backup_path.py`, `test_cancellation.py`, `test_cleanup.py`, `test_cli_auth.py`, `test_cli_parse.py`, `test_cli_restore.py`, `test_cli_status.py`, `test_concurrent_workers.py`, `test_config.py`, `test_config_integration.py`, `test_constants.py`, `test_downloader.py`, `test_errors.py`

**Part 2 (Files 26-27, 29, 31-44, 46-50)**:
`test_exec.py`, `test_host_repository.py`, `test_installer.py`, `test_integration_disk_insufficient.py`, `test_integration_missing_backup.py`, `test_integration_workflow.py`, `test_integration_workflow_disk_insufficient.py`, `test_integration_workflow_failures.py`, `test_isolation.py`, `test_job_logs.py`, `test_job_repository.py`, `test_locked_user.py`, `test_logging.py`, `test_loop.py`, `test_metadata_injection.py`, `test_models.py`, `test_models_role.py`, `test_naming.py`, `test_password.py`, `test_permissions.py`, `test_permissions_integration.py`, `test_post_sql.py`

**Part 3 (Files 51-60, 62-69, 71-73)**:
`test_post_sql_execution.py`, `test_profiling.py`, `test_restore.py`, `test_restore_models.py`, `test_s3_discovery.py`, `test_s3_real_listing_optional.py`, `test_schema_phase4.py`, `test_secret_rotation.py`, `test_secrets.py`, `test_settings_repository.py`, `test_simulated_auth_repository.py`, `test_staging.py`, `test_user_repository.py`, `test_user_repository_role.py`, `test_validation.py`, `test_web_auth_flow.py`, `test_web_routes.py`, `test_worker_executor.py`, `test_worker_log_normalizer.py`, `test_worker_rbac.py`, `test_worker_service.py`

---

#### B17 Patterns Observed

**Excellent Compliance**:
- 90% of test files already have `from __future__ import annotations`
- Modern type hints (`X | None`) used throughout - no legacy `Optional[X]`
- Well-structured test classes with clear naming
- Proper pytest fixture patterns

**Remediation Note**:
The 7 non-compliant files are mostly small stubs or simple tests. Adding future annotations to these is a quick fix:
```bash
# One-liner fix for each file
sed -i '1s/^/from __future__ import annotations\n\n/' <file>
```

---

## B17 COMPLETES FULL CODEBASE ANALYSIS ✅

---

## Remediation Task Groups

### Group 1: HCA Layer Docstrings (CRITICAL)

**Effort**: Quick Fix (< 5 min each)
**Pattern**: Add `HCA Layer: <layer>` to module docstring

| Finding ID | File | Layer | Status |
|------------|------|-------|--------|
| *(To be populated)* | - | - | ⬜ |

**Template Fix**:
```python
"""Module description.

HCA Layer: <shared|entities|features|widgets|pages|plugins>

Extended description...
"""
```

---

### Group 2: Modern Type Hints (HIGH)

**Effort**: Quick Fix (< 5 min each)
**Pattern**: Replace deprecated typing imports

| Finding ID | File | Current | Should Be | Status |
|------------|------|---------|-----------|--------|
| *(To be populated)* | - | - | - | ⬜ |

**Common Fixes**:
| Deprecated | Modern |
|------------|--------|
| `from typing import Optional` | Remove, use `X \| None` |
| `from typing import List` | Remove, use `list[X]` |
| `from typing import Dict` | Remove, use `dict[K, V]` |
| `from typing import Union` | Remove, use `X \| Y` |
| `Optional[X]` | `X \| None` |
| `List[X]` | `list[X]` |
| `Dict[K, V]` | `dict[K, V]` |
| `Union[X, Y]` | `X \| Y` |

---

### Group 3: Bare Exception Handlers (HIGH)

**Effort**: Simple (5-30 min each)
**Pattern**: Add logging or specific exception handling

| Finding ID | File | Line | Context | Status |
|------------|------|------|---------|--------|
| *(To be populated)* | - | - | - | ⬜ |

**Fix Options**:

1. **Add logging** (preferred for fail-safe UX):
```python
except Exception:
    logger.warning("Operation failed, using fallback", exc_info=True)
    return fallback_value
```

2. **Add inline documentation** (for intentional silent handling):
```python
except Exception:  # Intentional: telemetry failure should not block main operation
    pass
```

3. **Use specific exception** (preferred when possible):
```python
except (ConnectionError, TimeoutError) as e:
    logger.warning(f"Network error: {e}")
    return fallback_value
```

---

### Group 4: Missing Docstrings (MEDIUM)

**Effort**: Simple (5-30 min each)
**Pattern**: Add Google-style docstrings

| Finding ID | File | Function/Class | Status |
|------------|------|----------------|--------|
| *(To be populated)* | - | - | ⬜ |

**Template**:
```python
def function_name(arg1: str, arg2: int) -> bool:
    """Brief description of function.

    Extended description if needed.

    Args:
        arg1: Description of arg1.
        arg2: Description of arg2.

    Returns:
        Description of return value.

    Raises:
        ValueError: When arg1 is invalid.
    """
```

---

### Group 5: File Naming (MEDIUM)

**Effort**: Moderate (requires import updates)
**Pattern**: Rename generic files to include layer context

| Finding ID | Current Name | Suggested Name | Status |
|------------|--------------|----------------|--------|
| *(To be populated)* | - | - | ⬜ |

---

### Group 6: Import Ordering (LOW)

**Effort**: Quick Fix (auto-fixable with `ruff check --fix`)
**Pattern**: Ensure stdlib → third-party → local ordering

| Finding ID | File | Status |
|------------|------|--------|
| *(To be populated)* | - | ⬜ |

**Auto-fix Command**:
```bash
ruff check --fix --select I pulldb/
```

---

## Remaining Findings Roadmap

> **Last Updated**: 2026-01-19 | **Remaining**: 247 findings | **Completed**: 119 (32%)

### Phase 1: HIGH Priority (48 remaining)

**Est. Time**: 8-12 hours | **Impact**: Directly improves code quality

#### 1A. HCA Docstrings (23 remaining)

Files missing `HCA Layer:` declaration in module docstring:

| Batch | File | Expected Layer | Finding ID |
|-------|------|----------------|------------|
| B01 | `pulldb/api/__init__.py` | pages | B01-001-001 |
| B01 | `pulldb/api/auth.py` | pages | B01-002-001 |
| B01 | `pulldb/api/logic.py` | pages | B01-003-001 |
| B01 | `pulldb/api/main.py` | pages | B01-004-001 |
| B01 | `pulldb/api/schemas.py` | pages | B01-005-001 |
| B01 | `pulldb/api/types.py` | pages | B01-006-001 |
| B03 | `pulldb/infra/__init__.py` | shared | B03-001-001 |
| B03 | `pulldb/infra/config.py` | shared | B03-002-001 |
| B03 | `pulldb/infra/exec.py` | shared | B03-004-001 |
| B03 | `pulldb/infra/executor.py` | shared | B03-005-001 |
| B03 | `pulldb/infra/logging_config.py` | shared | B03-007-001 |
| B03 | `pulldb/infra/mysql_connection.py` | shared | B03-008-001 |
| B03 | `pulldb/infra/mysql.py` | shared | B03-009-001 |
| B03 | `pulldb/infra/paths.py` | shared | B03-010-001 |
| B03 | `pulldb/infra/platform_detect.py` | shared | B03-011-001 |
| B03 | `pulldb/infra/s3.py` | shared | B03-012-001 |
| B04 | `pulldb/domain/__init__.py` | entities | B04-001-001 |
| B04 | `pulldb/domain/config.py` | entities | B04-003-001 |
| B04 | `pulldb/domain/errors.py` | entities | B04-004-001 |
| B04 | `pulldb/domain/interfaces.py` | entities | B04-006-001 |
| B04 | `pulldb/domain/models.py` | entities | B04-007-001 |
| B04 | `pulldb/domain/naming.py` | entities | B04-008-001 |
| B04 | `pulldb/domain/permissions.py` | entities | B04-009-001 |

#### 1B. Error Handling - HIGH (8 remaining)

| Batch | File | Line | Issue | Finding ID |
|-------|------|------|-------|------------|
| B01 | `api/main.py` | 670 | `except Exception: pass` - API key silently swallowed | B01-004-005 |
| B03 | `infra/executor.py` | 122+ | `Callable` without specific signature | B03-005-002 |
| B03 | `infra/mysql.py` | 61+ | Uses `Any` throughout | B03-009-002 |
| B03 | `infra/mysql.py` | 65+ | Uses `Tuple` instead of `tuple` | B03-009-003 |
| B03 | `infra/paths.py` | 46 | Uses `list[str]` without future annotations | B03-010-003 |
| B03 | `infra/paths.py` | 47+ | Uses `dict[str, X]` without future annotations | B03-010-004 |
| B03 | `infra/platform_detect.py` | 171 | Uses `dict[str, Any]` - could use TypedDict | B03-011-003 |
| B03 | `infra/s3.py` | 32 | Imports `Callable` - use collections.abc | B03-012-002 |

#### 1C. Type Hints - HIGH (8 remaining)

| Batch | File | Issue | Finding ID |
|-------|------|-------|------------|
| B03 | `infra/mysql.py` | Uses `Any` throughout | B03-009-002 |
| B03 | `infra/mysql.py` | Uses `Tuple` instead of `tuple` | B03-009-003 |
| B06 | `worker/restore.py` | `Path` import inconsistent | B06-004-002 |
| B06 | `worker/staging.py` | Uses `Optional` | B06-006-003 |
| B06 | `worker/atomic_rename.py` | Uses `Optional` | B06-007-002 |
| B07 | `worker/log_normalizer.py` | Missing future annotations | B07-006-001 |
| B07 | `worker/metadata_synthesis.py` | Missing future annotations | B07-008-001 |
| B07 | `worker/feature_request_service.py` | Broad exception handlers | B07-004-001 |

#### 1D. Code Quality - HIGH (9 remaining)

| Batch | File | Issue | Finding ID |
|-------|------|-------|------------|
| B03 | `infra/platform_detect.py` | Runtime typing module usage | B03-011-002 |
| B05 | `domain/services/provisioning.py` | HCA layer mismatch (features vs entities) | B05-003-001 |
| B06 | `worker/cleanup.py` | Missing future annotations | B06-009-002 |
| B09 | `simulation/core/seeding.py` | HCA layer wrong (shared vs features) | B09-006-001 |
| B11 | `simulation/api/__init__.py` | Missing future annotations | B11-001-001 |
| B14 | `web/features/__init__.py` | Missing future annotations | B14-001-001 |
| B14 | `web/features/admin/__init__.py` | Missing future annotations | B14-002-001 |
| B15 | `web/widgets/__init__.py` | Missing future annotations | B15-001-001 |
| B16 | `web/__init__.py` | Missing future annotations | B16-001-001 |

---

### Phase 2: MEDIUM Priority (111 remaining)

**Est. Time**: 20-30 hours | **Impact**: Maintainability improvements

#### 2A. Error Handling - MEDIUM (67 findings)

Pattern: `except Exception` without logging - needs logging or specific exceptions

**Batch B01 (api/)**: 5 findings
**Batch B02 (cli/)**: 8 findings  
**Batch B03 (infra/)**: 6 findings
**Batch B04-B05 (domain/)**: 6 findings
**Batch B06-B07 (worker/)**: 25 findings
**Batch B08 (auth/)**: 2 findings
**Batch B09-B11 (simulation/)**: 8 findings
**Batch B14-B16 (web/)**: 7 findings

#### 2B. Docstrings - MEDIUM (20 findings)

Pattern: Missing or incomplete Google-style docstrings

| Package | Files Affected | Findings |
|---------|---------------|----------|
| `pulldb/api/` | logic.py, main.py | 2 |
| `pulldb/infra/` | executor.py, mysql_connection.py | 3 |
| `pulldb/domain/` | errors.py, interfaces.py, permissions.py, restore_models.py | 6 |
| `pulldb/worker/` | service.py, executor.py, restore.py | 4 |
| `pulldb/simulation/` | engine.py, scenarios.py, state.py | 5 |

#### 2C. Type Hints - MEDIUM (10 findings)

| Finding ID | File | Issue |
|------------|------|-------|
| B01-006-003 | `api/types.py` | Uses `Any` for repository types |
| B03-007-002 | `infra/logging_config.py` | Uses `str` for log level - use `Literal` |
| B03-009-005 | `infra/mysql.py` | Context manager returns `Any` |
| B04-003-002 | `domain/config.py` | Complex TYPE_CHECKING pattern |
| B06-002-002 | `worker/service.py` | Bare `except ValueError: pass` |
| B06-003-002 | `worker/executor.py` | Uses `Any` without justification |
| B06-010-002 | `worker/loop.py` | TYPE_CHECKING uses string annotations |
| B07-006-003 | `worker/log_normalizer.py` | Uses `Optional` instead of `X \| None` |
| B07-008-003 | `worker/metadata_synthesis.py` | Legacy `Optional` type hints |
| B11-002-002 | `simulation/api/router.py` | typing alias style inconsistency |

#### 2D. Code Quality - MEDIUM (13 findings)

| Finding ID | File | Issue |
|------------|------|-------|
| B01-004-007 | `api/main.py` | Uses `print()` instead of logging |
| B03-004-003 | `infra/exec.py` | `# pragma: no cover` may mask issues |
| B03-009-004 | `infra/mysql.py` | Deprecated methods still present |
| B03-011-005 | `infra/platform_detect.py` | Multiple `# pragma: no cover` |
| B06-003-005 | `worker/executor.py` | Large internal method (~200 lines) |
| B06-009-004 | `worker/cleanup.py` | File is 2727 lines - split |
| B06-010-003 | `worker/loop.py` | 315+ line function |
| B07-008-005 | `worker/metadata_synthesis.py` | Complex functions need decomposition |
| B08-002-002 | `auth/repository.py` | f-string in logger (security/performance) |
| B09-002-003 | `simulation/core/bus.py` | Broad exception without re-raise |
| B10-003-006 | `simulation/adapters/mock_mysql.py` | Uses hasattr for enum check |
| B11-002-003 | `simulation/api/router.py` | `raise ... from None` suppresses context |
| B16-002-002 | `web/dependencies.py` | Multiple bare `except Exception: pass` |

#### 2E. HCA Compliance - MEDIUM (1 finding)

| Finding ID | File | Issue |
|------------|------|-------|
| B16-004-001 | `web/router_registry.py` | Uses `HCA Layer: Foundation` instead of `pages` |

---

### Phase 3: LOW Priority (88 remaining)

**Est. Time**: 15-20 hours | **Impact**: Polish and consistency

#### 3A. Docstrings - LOW (21 findings)

Private functions and classes needing brief docstrings

#### 3B. Error Handling - LOW (29 findings)

Acceptable graceful degradation patterns - document intent

#### 3C. Code Quality - LOW (23 findings)

Style preferences, minor optimizations, file organization suggestions

#### 3D. Type Hints - LOW (10 findings)

Non-standard aliases, minor type improvements

#### 3E. HCA Compliance - LOW (5 findings)

Minor naming format inconsistencies

---

## Cross-Reference Index

### By Standard Document

| Standard | Section | Finding Count |
|----------|---------|---------------|
| `.pulldb/standards/hca.md` | Law 2 (Explicit Naming) | 29 remaining |
| `.pulldb/standards/hca.md` | Law 4 (Layer Isolation) | 2 findings |
| `engineering-dna/standards/python.md` | Type Hints | 28 remaining |
| `engineering-dna/standards/python.md` | Docstrings | 41 remaining |
| `engineering-dna/protocols/fail-hard.md` | Error Handling | 104 remaining |

### By Package (Findings Distribution)

| Package | CRIT | HIGH | MED | LOW | Total Remaining |
|---------|------|------|-----|-----|-----------------|
| `pulldb/api/` | 0 | 6 | 8 | 8 | 22 |
| `pulldb/cli/` | 0 | 0 | 10 | 15 | 25 |
| `pulldb/infra/` | 0 | 16 | 10 | 6 | 32 |
| `pulldb/domain/` | 0 | 11 | 12 | 11 | 34 |
| `pulldb/worker/` | 0 | 10 | 35 | 17 | 62 |
| `pulldb/auth/` | 0 | 0 | 3 | 1 | 4 |
| `pulldb/simulation/` | 0 | 5 | 20 | 10 | 35 |
| `pulldb/web/` | 0 | 0 | 13 | 20 | 33 |
| **TOTAL** | **0** | **48** | **111** | **88** | **247** |

---

## Completion Checklist

- [x] All batches analyzed (B01-B17) ✅
- [x] All findings have unique IDs ✅
- [x] All CRITICAL findings remediated (50/50) ✅
- [x] HIGH findings documented with remediation plans ✅
- [x] Remediation effort estimated ✅
- [x] Cross-reference index complete ✅
- [x] Summary dashboard accurate ✅
- [ ] MEDIUM findings remediated (0/111)
- [ ] LOW findings remediated (0/88)

---

## Bulk Remediation Commands

### Add Future Annotations (Remaining)

```bash
# List files still missing future annotations
find pulldb -name "*.py" ! -path "*__pycache__*" -exec grep -L "from __future__ import annotations" {} \;

# Auto-add to specific files (verify first)
sed -i '1s/^/from __future__ import annotations\n\n/' <file>
```

### Fix Import Ordering

```bash
ruff check --fix --select I pulldb/
```

### Find Bare Exceptions

```bash
grep -rn "except Exception:" pulldb/ --include="*.py" | grep -v "__pycache__"
```

### Find Missing HCA Docstrings

```bash
find pulldb -name "*.py" ! -path "*__pycache__*" -exec grep -L "HCA Layer" {} \;
```

---

*Last Updated: 2026-01-19 | Findings: 366 total | Remaining: 247 | Next: HIGH remediation phase*
