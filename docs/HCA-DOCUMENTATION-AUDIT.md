# HCA Documentation Audit & Reorganization Plan

> **Full Audit** — Documentation restructuring to enforce HCA methodology  
> **Created**: December 3, 2025  
> **Branch**: `feature/documentation-reorganization`  
> **Status**: PLANNING

---

## Executive Summary

pullDB partially implements HCA (Hierarchical Containment Architecture) in its codebase but the documentation structure does **NOT** follow HCA principles. This audit identifies the gaps and provides a comprehensive plan to reorganize documentation so that:

1. **The directory structure IS the documentation architecture**
2. **The path IS the documentation**
3. **All future development adheres to HCA methodology**

---

## Part 1: Current State Analysis

### 1.1 Code Architecture (Good ✅)

The pullDB codebase **correctly implements HCA** with clear layer separation:

```
pulldb/
  ├── domain/      ← Layer 0: Core business objects (entities)
  │   ├── models.py
  │   ├── interfaces.py  
  │   ├── errors.py
  │   └── config.py
  │
  ├── infra/       ← Layer 1: Infrastructure adapters (shared/technical)
  │   ├── mysql.py
  │   ├── s3.py
  │   ├── secrets.py
  │   ├── exec.py
  │   └── factory.py
  │
  ├── api/         ← Layer 2: API Service (feature layer)
  │   └── main.py
  │
  ├── worker/      ← Layer 2: Worker Service (feature layer)
  │   ├── service.py
  │   ├── executor.py
  │   ├── restore.py
  │   ├── downloader.py
  │   └── staging.py
  │
  ├── cli/         ← Layer 3: CLI Interface (UI/presentation)
  │   └── main.py
  │
  ├── web/         ← Layer 3: Web Interface (UI/presentation)
  │   └── features/
  │
  └── simulation/  ← Testing infrastructure (parallel hierarchy)
      ├── adapters/
      └── core/
```

**HCA Compliance Score: 85%** - Good layer separation, dependencies flow correctly.

### 1.2 Documentation Architecture (Poor ❌)

The current docs structure **violates multiple HCA laws**:

```
docs/                          ← FLAT STRUCTURE (violates Law 2)
  ├── architecture.md          ← Floating atom
  ├── cli-reference.md         ← Floating atom
  ├── getting-started.md       ← Floating atom
  ├── mysql-schema.md          ← Floating atom
  ├── KNOWLEDGE-POOL.md        ← Correct location
  ├── START-HERE.md            ← Good entry point but structure below is flat
  ├── FAIL-HARD.md             ← Template file, not categorized
  │
  ├── archived/                ← 60+ files, many obsolete
  │   ├── aws-setup.md.OBSOLETE
  │   ├── milestone-2-plan.md
  │   └── ... (massive junk drawer)
  │
  ├── design/                  ← Only 1 file
  ├── generated/               ← Auto-generated
  ├── IngestMe/                ← HCA source docs (not integrated!)
  │   └── HCA/
  ├── policies/                ← Good categorization
  └── terraform/               ← Good categorization
```

**Problems Identified:**

| HCA Law | Violation | Severity |
|---------|-----------|----------|
| Law 1: Atoms at Bottom | Docs floating at top level, not in component dirs | HIGH |
| Law 2: Containers Only Contain | `docs/` has 15+ floating files | HIGH |
| Law 4: Names Tell Story | Generic names (START-HERE, FAIL-HARD) | MEDIUM |
| Law 5: Single Source | Duplicate/obsolete files in archived/ | HIGH |
| Law 6: Contracts | No clear interface between doc categories | MEDIUM |

### 1.3 Copilot Instructions (Partial ⚠️)

```
.github/
  ├── copilot-instructions.md           ← Good entry point
  ├── copilot-instructions-behavior.md  ← Task overlay
  ├── copilot-instructions-python.md    ← Task overlay  
  ├── copilot-instructions-testing.md   ← Task overlay
  └── copilot-instructions-status.md    ← Task overlay
```

**Issues:**
- HCA is mentioned in `.pulldb/CONTEXT.md` but NOT in copilot-instructions
- No explicit HCA validation checklist
- No reference to `docs/IngestMe/HCA/` documents

---

## Part 2: Target State (HCA-Compliant)

### 2.1 New Documentation Hierarchy

```
docs/
  ├── README.md                           ← Entry point (replaces START-HERE.md)
  │
  ├── methodology/                        ← Layer 0: SHARED/UNIVERSAL
  │   ├── README.md                       ← Index for methodology
  │   ├── hca/                            ← HCA documentation (from IngestMe)
  │   │   ├── README.md                   ← HCA overview
  │   │   ├── hierarchical-containment-architect.md
  │   │   ├── hca-agent-activation.md
  │   │   └── hca-agent-training.md
  │   ├── fail-hard/
  │   │   ├── README.md
  │   │   └── fail-hard-template.md
  │   └── knowledge-pool/
  │       ├── README.md
  │       ├── KNOWLEDGE-POOL.md
  │       └── KNOWLEDGE-POOL.json
  │
  ├── architecture/                       ← Layer 1: ENTITIES/DOMAIN
  │   ├── README.md                       ← Architecture index
  │   ├── system-overview/
  │   │   └── architecture.md
  │   ├── data-model/
  │   │   └── mysql-schema.md
  │   ├── components/
  │   │   ├── api-service.md
  │   │   ├── worker-service.md
  │   │   └── cli-client.md
  │   └── diagrams/
  │       └── (architecture diagrams)
  │
  ├── guides/                             ← Layer 2: FEATURES (user actions)
  │   ├── README.md                       ← Guides index
  │   ├── user/                           ← End-user guides
  │   │   ├── getting-started.md
  │   │   └── cli-reference.md
  │   ├── admin/                          ← Administrator guides
  │   │   ├── admin-guide.md
  │   │   └── deployment.md
  │   ├── developer/                      ← Contributor guides
  │   │   └── development.md
  │   └── infrastructure/                 ← Infra engineer guides
  │       ├── aws-setup.md
  │       └── terraform/
  │
  ├── operations/                         ← Layer 2: FEATURES (ops actions)
  │   ├── README.md
  │   └── runbooks/
  │       ├── runbook-restore.md
  │       ├── runbook-failure.md
  │       └── runbook-throttle.md
  │
  ├── reference/                          ← Layer 3: DETAILED SPECS
  │   ├── README.md
  │   ├── policies/                       ← IAM policies
  │   └── schemas/                        ← JSON schemas, SQL scripts
  │
  ├── debug/                              ← Session/debug documents
  │   ├── DEBUG-PROJECT-REVIEW.md
  │   ├── DEBUG-SIMULATION-REVIEW.md
  │   └── DEBUG-MOCK-AUDIT.md
  │
  └── archived/                           ← Deprecated (to be cleaned)
      └── (only truly historical docs)
```

### 2.2 Updated .github/copilot-instructions.md

Add HCA section to enforce methodology in all AI-assisted development:

```markdown
## HCA Enforcement (MANDATORY)

All code and documentation changes MUST follow Hierarchical Containment Architecture:

### The Six Laws (Validate Every Change)

1. **ATOMS AT BOTTOM**: Files go in component directories, never floating
2. **CONTAINERS ONLY CONTAIN**: Directories group related items, have index/README
3. **DEPENDENCIES FLOW DOWN**: Import from same layer or below, NEVER above
4. **NAMES TELL STORY**: Specific names, no generic (utils, helpers, common)
5. **SINGLE SOURCE OF TRUTH**: One canonical location per concept
6. **CONTRACTS FOR COMMUNICATION**: Interfaces for cross-module interaction

### Layer Model (pullDB-specific)

| Layer | Location | Contents |
|-------|----------|----------|
| 0: Domain | `pulldb/domain/` | models, interfaces, errors |
| 1: Infrastructure | `pulldb/infra/` | mysql, s3, secrets, exec |
| 2: Services | `pulldb/api/`, `pulldb/worker/` | API, Worker features |
| 3: Presentation | `pulldb/cli/`, `pulldb/web/` | CLI, Web UI |
| ∥: Testing | `pulldb/simulation/` | Mock infrastructure |

### Pre-Commit HCA Check

Before any code change, verify:
□ File is in correct layer directory
□ Path reads as logical hierarchy  
□ No upward dependencies
□ Name is specific (not generic)
□ No duplicate code (reference shared/ instead)

### Reference Documents

- `docs/methodology/hca/` - Full HCA specification
- `docs/IngestMe/HCA/hca-agent-activation.md` - Agent activation prompt
```

---

## Part 3: Migration Tasks

### Phase 1: Create New Structure (No Breaking Changes)

| Task | Priority | Effort | Description |
|------|----------|--------|-------------|
| T-001 | HIGH | 15m | Create `docs/methodology/` with README |
| T-002 | HIGH | 15m | Move HCA docs from `IngestMe/` to `methodology/hca/` |
| T-003 | HIGH | 10m | Create `docs/architecture/` with README |
| T-004 | HIGH | 10m | Create `docs/guides/` with subdirectories |
| T-005 | HIGH | 10m | Create `docs/operations/` with README |
| T-006 | HIGH | 10m | Create `docs/reference/` with README |
| T-007 | MEDIUM | 10m | Create `docs/debug/` and move DEBUG-*.md files |

### Phase 2: Migrate Existing Documents

| Task | Priority | From | To |
|------|----------|------|-----|
| T-010 | HIGH | `docs/architecture.md` | `docs/architecture/system-overview/architecture.md` |
| T-011 | HIGH | `docs/mysql-schema.md` | `docs/architecture/data-model/mysql-schema.md` |
| T-012 | HIGH | `docs/getting-started.md` | `docs/guides/user/getting-started.md` |
| T-013 | HIGH | `docs/cli-reference.md` | `docs/guides/user/cli-reference.md` |
| T-014 | HIGH | `docs/admin-guide.md` | `docs/guides/admin/admin-guide.md` |
| T-015 | HIGH | `docs/deployment.md` | `docs/guides/admin/deployment.md` |
| T-016 | HIGH | `docs/development.md` | `docs/guides/developer/development.md` |
| T-017 | MEDIUM | `docs/KNOWLEDGE-POOL.*` | `docs/methodology/knowledge-pool/` |
| T-018 | MEDIUM | `docs/FAIL-HARD.md` | `docs/methodology/fail-hard/fail-hard-template.md` |
| T-019 | MEDIUM | `docs/policies/` | `docs/reference/policies/` |
| T-020 | LOW | `docs/terraform/` | `docs/guides/infrastructure/terraform/` |

### Phase 3: Update Entry Point

| Task | Priority | Description |
|------|----------|-------------|
| T-030 | HIGH | Replace `START-HERE.md` with `README.md` using new hierarchy |
| T-031 | HIGH | Update all internal doc links to new paths |
| T-032 | MEDIUM | Update `.github/copilot-instructions.md` with HCA section |
| T-033 | MEDIUM | Update `.pulldb/CONTEXT.md` to reference new structure |

### Phase 4: Clean Up Archived

| Task | Priority | Description |
|------|----------|-------------|
| T-040 | LOW | Audit `docs/archived/` - keep only truly historical |
| T-041 | LOW | Delete `.OBSOLETE` files |
| T-042 | LOW | Move still-relevant archived docs to proper locations |

---

## Part 4: Updated Copilot Instructions

Add this section to `.github/copilot-instructions.md`:

```markdown
## HCA Methodology (MANDATORY)

pullDB follows **Hierarchical Containment Architecture (HCA)** for all code AND documentation.

### The Fundamental Truth
> The directory structure IS the architecture. The path IS the documentation.

### HCA Reference Documents
**Read before making architectural decisions:**
- `docs/methodology/hca/hierarchical-containment-architect.md` - Full specification
- `docs/methodology/hca/hca-agent-activation.md` - Agent activation prompt
- `docs/methodology/hca/hca-agent-training.md` - Validation exercises

### Layer Validation Checklist
Before creating/moving ANY file:

```
□ What layer does this belong to?
  - domain/ (models, interfaces, errors)
  - infra/ (mysql, s3, secrets, exec)  
  - api/ or worker/ (service features)
  - cli/ or web/ (presentation)
  - simulation/ (testing infrastructure)
  - docs/methodology/ (universal patterns)
  - docs/architecture/ (system design)
  - docs/guides/ (how-to by role)
  - docs/operations/ (runbooks)
  - docs/reference/ (detailed specs)

□ Is the path a logical hierarchy?
  - docs/guides/user/cli-reference.md ✅
  - docs/cli-reference.md ❌ (floating atom)

□ Are dependencies flowing down (not up)?
  - domain imports nothing from pulldb
  - infra imports only from domain
  - api/worker import from domain + infra
  - cli/web import from all below

□ Is the name specific?
  - "authentication-handler.md" ✅
  - "utils.md" ❌ (generic)
```

### Documentation HCA Mapping

| Doc Type | Layer | Location |
|----------|-------|----------|
| Universal methodology | shared | `docs/methodology/` |
| Architecture specs | entities | `docs/architecture/` |
| How-to guides | features | `docs/guides/{role}/` |
| Operational runbooks | features | `docs/operations/` |
| Technical reference | reference | `docs/reference/` |
| Debug/session notes | session | `docs/debug/` |
```

---

## Part 5: Validation Checklist

After migration, verify:

### Structure Validation
- [ ] No floating files in `docs/` root (except README.md)
- [ ] Every directory has a README.md or index
- [ ] Path of any doc tells you what it contains
- [ ] No generic names (utils, helpers, misc, common)

### Link Validation  
- [ ] All internal doc links work
- [ ] `docs/README.md` links to all major sections
- [ ] `.github/copilot-instructions.md` references HCA docs

### HCA Compliance
- [ ] HCA docs moved from `IngestMe/` to `methodology/hca/`
- [ ] Copilot instructions include HCA enforcement section
- [ ] `.pulldb/CONTEXT.md` updated with new doc paths

### Cleanup Validation
- [ ] `docs/archived/` contains only truly historical docs
- [ ] No `.OBSOLETE` files remain
- [ ] `docs/IngestMe/` removed after migration

---

## Part 6: Implementation Order

```
Phase 1: Structure (30 min)
├─ T-001: Create docs/methodology/
├─ T-002: Move HCA docs  
├─ T-003: Create docs/architecture/
├─ T-004: Create docs/guides/
├─ T-005: Create docs/operations/
├─ T-006: Create docs/reference/
└─ T-007: Create docs/debug/

Phase 2: Migration (45 min)
├─ T-010 through T-020: Move existing docs
└─ Verify all files in correct locations

Phase 3: Integration (30 min)
├─ T-030: Create new docs/README.md
├─ T-031: Update internal links
├─ T-032: Update copilot-instructions.md
└─ T-033: Update .pulldb/CONTEXT.md

Phase 4: Cleanup (30 min)
├─ T-040: Audit archived/
├─ T-041: Delete obsolete
└─ T-042: Move relevant archived docs

Total: ~2.5 hours
```

---

## Appendix A: File Movement Map

| Current Path | New Path | Notes |
|-------------|----------|-------|
| `docs/START-HERE.md` | `docs/README.md` | Rewrite as index |
| `docs/architecture.md` | `docs/architecture/system-overview/architecture.md` | |
| `docs/mysql-schema.md` | `docs/architecture/data-model/mysql-schema.md` | |
| `docs/getting-started.md` | `docs/guides/user/getting-started.md` | |
| `docs/cli-reference.md` | `docs/guides/user/cli-reference.md` | |
| `docs/admin-guide.md` | `docs/guides/admin/admin-guide.md` | |
| `docs/deployment.md` | `docs/guides/admin/deployment.md` | |
| `docs/development.md` | `docs/guides/developer/development.md` | |
| `docs/KNOWLEDGE-POOL.md` | `docs/methodology/knowledge-pool/KNOWLEDGE-POOL.md` | |
| `docs/KNOWLEDGE-POOL.json` | `docs/methodology/knowledge-pool/KNOWLEDGE-POOL.json` | |
| `docs/FAIL-HARD.md` | `docs/methodology/fail-hard/fail-hard-template.md` | |
| `docs/WORKSPACE-INDEX.md` | `docs/architecture/workspace-index/WORKSPACE-INDEX.md` | |
| `docs/WORKSPACE-INDEX.json` | `docs/architecture/workspace-index/WORKSPACE-INDEX.json` | |
| `docs/IngestMe/HCA/*` | `docs/methodology/hca/*` | Move all HCA docs |
| `docs/DEBUG-*.md` | `docs/debug/DEBUG-*.md` | Move debug docs |
| `docs/policies/` | `docs/reference/policies/` | Move IAM policies |
| `docs/terraform/` | `docs/guides/infrastructure/terraform/` | Move terraform |
| `design/runbook-*.md` | `docs/operations/runbooks/runbook-*.md` | Move runbooks |

---

## Appendix B: Archived Cleanup Recommendations

Files to **DELETE** (obsolete):
- `*.OBSOLETE` files
- `milestone-*-plan.md` (historical)
- `phase-*-plan.md` (superseded)
- Duplicate setup guides

Files to **MOVE** to proper location:
- `coding-standards.md` → `docs/methodology/`
- `security-model.md` → `docs/architecture/security/`
- `backup-formats.md` → `docs/reference/`

Files to **KEEP** in archived (historical reference):
- `README-old.md`
- `TRUTH-MATRIX.md`
- Status reports

---

*Audit completed December 3, 2025*
*Ready for implementation on branch: feature/documentation-reorganization*
