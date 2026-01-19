# QA&A Codebase Analysis - Orchestration Prompt

> **Document Type**: Orchestration Framework | **Version**: 1.0.0 | **Created**: 2026-01-19
>
> Master prompt for orchestrating sub-agent analysis of the pullDB codebase against QA&A standards.
> This document is used iteratively until complete codebase analysis is achieved.

---

## Purpose

This prompt orchestrates systematic quality analysis of the pullDB codebase using sub-agents. The orchestrator (you) dispatches focused analysis tasks, collects findings, and maintains centralized documentation. **NO CODE IS MODIFIED** - only analysis and documentation.

---

## Reference Documents (Load Before Each Session)

| Document | Path | Purpose |
|----------|------|---------|
| **QA&A Role** | `docs/QA-AND-A-ROLE-RESPONSIBILITIES.md` | Standards and checklists |
| **Analysis Report** | `docs/QA-V1.1.0-ANALYSIS-REPORT.md` | Baseline findings |
| **Master State** | `docs/qa/QAA-MASTER-STATE.md` | Progress tracking |
| **Findings Plan** | `docs/qa/QAA-FINDINGS-PLAN.md` | Detailed findings & remediation |
| **HCA Standard** | `.pulldb/standards/hca.md` | HCA 6 Laws reference |
| **Python Standard** | `engineering-dna/standards/python.md` | Python code standards |
| **FAIL HARD** | `engineering-dna/protocols/fail-hard.md` | Error handling standard |

---

## Orchestration Protocol

### Session Start Checklist

```
□ Read QAA-MASTER-STATE.md to determine current progress
□ Identify next unanalyzed batch from the queue
□ Load relevant standards for the batch type
□ Dispatch sub-agent with focused prompt
□ Collect and validate findings
□ Update QAA-MASTER-STATE.md with progress
□ Append findings to QAA-FINDINGS-PLAN.md
□ Repeat until batch complete or session ends
```

### Sub-Agent Dispatch Template

Use this template when launching sub-agents for code analysis:

```
## Sub-Agent Task: [BATCH_ID] - [PACKAGE/MODULE]

### Context
You are a QA analyst reviewing pullDB code for v1.1.0 compliance.
Standards are defined in engineering-dna and .pulldb/ directories.
**DO NOT MODIFY ANY CODE** - only analyze and report findings.

### Files to Analyze
[LIST OF FILES - max 5-10 per batch]

### Analysis Checklist

For EACH file, evaluate and report:

#### 1. HCA Compliance
- [ ] Has `HCA Layer: <layer>` in module docstring?
- [ ] File is in correct HCA layer directory?
- [ ] Imports only from same or lower layers?
- [ ] File name is explicit (includes layer context)?
- [ ] No circular dependencies?

#### 2. Python Standards
- [ ] Has `from __future__ import annotations`?
- [ ] Uses modern type hints (`dict`, `list`, `X | None`)?
- [ ] No deprecated `typing` imports (`Dict`, `List`, `Optional`, `Union`)?
- [ ] Import ordering: stdlib → third-party → local?
- [ ] Alphabetized within import groups?

#### 3. Docstrings
- [ ] Module has docstring with purpose?
- [ ] Public functions have Google-style docstrings?
- [ ] Args/Returns/Raises sections where applicable?
- [ ] Classes have attribute documentation?

#### 4. Error Handling (FAIL HARD)
- [ ] No bare `except:` or `except Exception:` without logging?
- [ ] Uses `raise ... from e` for exception chaining?
- [ ] Error messages include actionable context?
- [ ] Domain errors follow FAIL HARD diagnostic structure?

#### 5. Code Quality
- [ ] No `# type: ignore` without explanation comment?
- [ ] No `TODO` or `FIXME` without issue reference?
- [ ] No hardcoded secrets or credentials?
- [ ] Logging uses `logging` module (not `print`)?

### Output Format

Return findings in this EXACT format for each file:

```markdown
### [filename.py]

**Path**: `pulldb/[package]/[filename].py`
**HCA Layer**: [detected layer] | **Expected**: [correct layer]
**Compliance Score**: [0-100]%

#### Findings

| ID | Category | Severity | Line(s) | Issue | Standard Reference | Remediation |
|----|----------|----------|---------|-------|-------------------|-------------|
| F001 | HCA | CRITICAL | 1-10 | Missing HCA Layer docstring | hca.md §Law2 | Add `HCA Layer: [layer]` to module docstring |
| F002 | Types | HIGH | 15 | Uses `Optional[str]` | python.md §TypeHints | Change to `str | None` |
| ... | ... | ... | ... | ... | ... | ... |

#### Compliant Patterns (What's Good)
- [List positive findings worth preserving]

#### Summary
- **Critical**: [count]
- **High**: [count]
- **Medium**: [count]
- **Low**: [count]
- **Estimated Effort**: [X hours]
```

### Completion Criteria
All files analyzed with zero ambiguous findings.
```

---

## Analysis Batches

### Batch Queue (Priority Order)

| Batch ID | Package | Files | Status | Priority | Rationale |
|----------|---------|-------|--------|----------|-----------|
| B01 | `pulldb/api/` | 5 | ⬜ Pending | P1 | User-facing, high visibility |
| B02 | `pulldb/cli/` | 10 | ⬜ Pending | P1 | User-facing, high visibility |
| B03 | `pulldb/infra/` | 13 | ⬜ Pending | P1 | Core infrastructure |
| B04 | `pulldb/domain/` (root) | 11 | ⬜ Pending | P1 | Core data models |
| B05 | `pulldb/domain/services/` | 4 | ⬜ Pending | P1 | Misplaced features |
| B06 | `pulldb/worker/` (core) | 10 | ⬜ Pending | P2 | Core features |
| B07 | `pulldb/worker/` (support) | 11 | ⬜ Pending | P2 | Support features |
| B08 | `pulldb/auth/` | 2 | ⬜ Pending | P2 | Auth infrastructure |
| B09 | `pulldb/simulation/core/` | 6 | ⬜ Pending | P3 | Simulation core |
| B10 | `pulldb/simulation/adapters/` | 3 | ⬜ Pending | P3 | Mock adapters |
| B11 | `pulldb/simulation/api/` | 1 | ⬜ Pending | P3 | Simulation API |
| B12 | `pulldb/web/shared/` | ~8 | ⬜ Pending | P3 | Web shared layer |
| B13 | `pulldb/web/entities/` | ~5 | ⬜ Pending | P3 | Web entities |
| B14 | `pulldb/web/features/` | ~15 | ⬜ Pending | P3 | Web features |
| B15 | `pulldb/web/widgets/` | ~10 | ⬜ Pending | P3 | Web widgets |
| B16 | `pulldb/web/` (root) | ~5 | ⬜ Pending | P3 | Web foundation |
| B17 | `pulldb/tests/` | 73 | ⬜ Pending | P4 | Test files |

**Status Legend**: ⬜ Pending | 🔄 In Progress | ✅ Complete | ⏸️ Blocked

---

## Severity Definitions

| Severity | Definition | v1.1.0 Impact |
|----------|------------|---------------|
| **CRITICAL** | Blocks v1.1.0 release. Must fix. | HCA docstring missing, architectural violation |
| **HIGH** | Should fix for v1.1.0. Quality degradation. | Deprecated types, bare exceptions without logging |
| **MEDIUM** | Fix in v1.1.x. Maintainability concern. | Generic file names, missing private docstrings |
| **LOW** | Backlog. Nice to have. | Style preferences, minor optimizations |

---

## Orchestrator Commands

### Start New Session
```
1. Read docs/qa/QAA-MASTER-STATE.md
2. Find first batch with status "Pending"
3. Update status to "In Progress"
4. Dispatch sub-agent with batch files
5. Process results
```

### Continue Session
```
1. Read docs/qa/QAA-MASTER-STATE.md
2. Find batch with status "In Progress"
3. Dispatch sub-agent for remaining files
4. Process results
5. If batch complete, mark "Complete" and move to next
```

### Process Sub-Agent Results
```
1. Validate findings format matches template
2. Assign unique finding IDs (F001, F002, ...)
3. Append to docs/qa/QAA-FINDINGS-PLAN.md
4. Update batch statistics in QAA-MASTER-STATE.md
5. Update summary counts
```

### Generate Progress Report
```
1. Read QAA-MASTER-STATE.md
2. Calculate completion percentage
3. Summarize findings by severity
4. Identify blockers
5. Estimate remaining effort
```

---

## Quality Gates

Before marking any batch "Complete":

- [ ] All files in batch have findings recorded
- [ ] Each finding has unique ID, severity, and remediation
- [ ] No "TBD" or placeholder entries
- [ ] Findings cross-referenced to standard documents
- [ ] Batch statistics updated in master state

---

## Example Sub-Agent Dispatch

```markdown
## Sub-Agent Task: B01 - pulldb/api/

### Context
You are a QA analyst reviewing pullDB code for v1.1.0 compliance.
**DO NOT MODIFY ANY CODE** - only analyze and report findings.

### Files to Analyze
1. pulldb/api/__init__.py
2. pulldb/api/auth.py
3. pulldb/api/logic.py
4. pulldb/api/main.py
5. pulldb/api/schemas.py
6. pulldb/api/types.py

### Standards Reference
- HCA: `.pulldb/standards/hca.md` - These are PAGES layer files
- Python: `engineering-dna/standards/python.md`
- Errors: `engineering-dna/protocols/fail-hard.md`

### Analysis Checklist
[Full checklist from template above]

### Output Format
[Format template from above]

Return comprehensive findings for ALL 6 files.
```

---

## Session Log Format

After each session, append to QAA-MASTER-STATE.md:

```markdown
### Session: YYYY-MM-DD HH:MM

**Batches Processed**: B01, B02
**Files Analyzed**: 15
**Findings Added**: 47
**Critical**: 12 | High: 18 | Medium: 12 | Low: 5
**Next Batch**: B03
**Notes**: [Any observations or blockers]
```

---

## Completion Criteria

The analysis is complete when:

1. All 17 batches have status "Complete"
2. Every Python file in `pulldb/` has findings documented
3. QAA-FINDINGS-PLAN.md contains remediation for all CRITICAL/HIGH findings
4. Summary statistics are accurate and reconciled
5. Effort estimates are provided for remediation phases

---

## Document Maintenance

| Document | Update Frequency | Responsible |
|----------|------------------|-------------|
| QAA-ORCHESTRATION-PROMPT.md | As needed (process improvements) | Orchestrator |
| QAA-MASTER-STATE.md | Every session | Orchestrator |
| QAA-FINDINGS-PLAN.md | Every batch completion | Orchestrator |

---

*This prompt enables systematic, traceable quality analysis across the entire pullDB codebase.*
