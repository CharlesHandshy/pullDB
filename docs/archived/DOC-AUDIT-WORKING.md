# Documentation Audit Working Document

**Date**: November 29, 2025
**Purpose**: Track documentation consolidation for Phase 4 merge readiness

---

## Classification Key

- **ESSENTIAL**: Active, accurate, must keep
- **UPDATE**: Keep but needs updates for v0.0.8
- **MERGE**: Consolidate into other doc
- **ARCHIVE**: Move to docs/archived/
- **DELETE**: Remove entirely

---

## docs/ Top-Level Files (36 files)

| File | Lines | Classification | Action |
|------|-------|---------------|--------|
| AWS-SETUP.md | 892 | ESSENTIAL | UPDATE - current v0.0.8 |
| FAIL-HARD.md | ~100 | MERGE | → engineering-dna has this |
| KNOWLEDGE-POOL.md | 391 | ESSENTIAL | Keep - operational facts |
| KNOWLEDGE-POOL.json | - | ESSENTIAL | Keep - machine-readable |
| TRUTH-MATRIX.md | ~50 | DELETE | Obsolete tracking doc |
| WORKER-ATOM-EVALUATION.md | 79 | ARCHIVE | Historical validation |
| WORKSPACE-INDEX.md | 678 | UPDATE | Refresh for Phase 4 |
| WORKSPACE-INDEX.json | - | UPDATE | Regenerate |
| appalachian_workflow_plan.md | 166 | ARCHIVE | Historical lessons |
| backup-formats.md | ~100 | ESSENTIAL | Keep - reference |
| cloudshell-commands-summary.md | 516 | ARCHIVE | Historical AWS setup |
| coding-standards.md | 1186 | MERGE | → constitution.md |
| concurrency-controls.md | ~100 | ESSENTIAL | Keep - Phase 2 feature |
| drift-resolution-checklist.md | ~50 | DELETE | Obsolete |
| engineering-dna-dev.md | ~100 | ARCHIVE | Adoption complete |
| installation.md | 537 | MERGE | → getting-started.md |
| job-logs.md | ~50 | MERGE | → cli-reference.md |
| mysql-schema.md | 371 | ESSENTIAL | Keep - schema reference |
| mysql-setup.md | 480 | MERGE | → getting-started.md |
| phase-4-implementation.md | 536 | ARCHIVE | Implementation complete |
| phase-4-testing-plan.md | ~150 | ARCHIVE | Testing complete |
| plan-metadata-synthesis.md | ~100 | ARCHIVE | Historical design |
| pulldb-admin-cli.md | 549 | MERGE | → cli-reference.md |
| pulldb-cli.md | 535 | MERGE | → cli-reference.md |
| pulldb-migrate.md | 427 | MERGE | → admin-guide.md |
| pulldb-services.md | 558 | MERGE | → deployment.md |
| pulldb_program_flow_workbook.md | ~200 | ARCHIVE | Historical |
| python-project-setup.md | ~100 | MERGE | → development.md |
| research-myloader-unification.md | ~100 | ARCHIVE | Research complete |
| restore-execution.md | ~150 | MERGE | → architecture.md |
| scheduled-cleanup.md | ~100 | MERGE | → admin-guide.md |
| schema-migration.md | ~100 | MERGE | → admin-guide.md |
| scripts-audit-report.md | 331 | ARCHIVE | Audit complete |
| security-controls.md | ~150 | MERGE | → deployment.md |
| test-environment.md | 469 | MERGE | → testing.md |
| test-plan-progress-2025-11-14.md | 96 | ARCHIVE | Historical |
| testing.md | 685 | UPDATE | Keep - comprehensive |
| vscode-diagnostics.md | ~50 | DELETE | Obsolete troubleshooting |

---

## design/ Files (20 files)

| File | Lines | Classification | Action |
|------|-------|---------------|--------|
| PHASE1-PLANNING.md | 294 | ARCHIVE | Phase 1 complete |
| README.md | ~50 | DELETE | Outdated |
| apptype-analysis.md | ~100 | ARCHIVE | Research complete |
| configuration-map.md | ~100 | ARCHIVE | Historical |
| engineering-dna-adoption.md | ~100 | ARCHIVE | Adoption complete |
| implementation-notes.md | ~100 | ARCHIVE | Historical |
| milestone-2-plan.md | 774 | ARCHIVE | Milestone complete |
| mysql-user-separation.md | ~100 | ARCHIVE | Implemented in .pulldb/ |
| phase-3-plan.md | 334 | ARCHIVE | Phase 3 complete |
| reference-analysis.md | ~100 | ARCHIVE | Research complete |
| restore-workflow-questionnaire.md | ~50 | DELETE | Obsolete |
| roadmap.md | 444 | UPDATE | Keep - active roadmap |
| runbook-failure.md | ~100 | ESSENTIAL | Keep - operational |
| runbook-restore.md | ~100 | ESSENTIAL | Keep - operational |
| runbook-throttle.md | ~50 | MERGE | → runbook-failure.md |
| security-model.md | ~100 | MERGE | → docs/security-controls.md |
| staging-rename-pattern.md | 918 | ARCHIVE | Implemented |
| system-overview.md | ~200 | MERGE | → docs/architecture.md |
| two-service-architecture.md | 511 | MERGE | → docs/architecture.md |
| worker_build_plan.md | ~200 | ARCHIVE | Build complete |

---

## Proposed New Documentation Structure

```
docs/
├── README.md                    # Quick navigation guide
├── getting-started.md           # Installation, AWS setup, MySQL setup
├── architecture.md              # System design, components, data flow
├── cli-reference.md             # All CLI commands and options
├── admin-guide.md               # Maintenance, migrations, cleanup
├── deployment.md                # Services, systemd, security
├── development.md               # Contributing, testing, coding standards
├── testing.md                   # Test guide (existing, updated)
├── mysql-schema.md              # Schema reference (existing)
├── backup-formats.md            # Backup format reference (existing)
├── concurrency-controls.md      # Phase 2 feature doc (existing)
├── KNOWLEDGE-POOL.md            # Operational facts (existing)
├── KNOWLEDGE-POOL.json          # Machine-readable facts
├── WORKSPACE-INDEX.md           # Code index (existing, updated)
├── WORKSPACE-INDEX.json         # Machine-readable index
└── archived/                    # Historical documents
    ├── README.md                # Archive index
    ├── phase-plans/             # Phase 0-4 planning docs
    ├── status-reports/          # Existing status reports
    ├── research/                # Research and analysis docs
    └── aws-legacy/              # Old AWS setup docs
```

---

## design/ Reorganization

```
design/
├── roadmap.md                   # Active roadmap (keep updated)
├── runbooks/                    # Operational runbooks
│   ├── failure-recovery.md      # Merged runbook
│   └── restore-procedures.md    
└── archived/                    # Everything else
```

---

## Consolidation Actions (Priority Order)

### Phase 1: Create Core Docs
1. Create `docs/getting-started.md` from installation.md + mysql-setup.md + AWS-SETUP.md essentials
2. Create `docs/architecture.md` from system-overview.md + two-service-architecture.md + restore-execution.md
3. Create `docs/cli-reference.md` from pulldb-cli.md + pulldb-admin-cli.md + job-logs.md
4. Create `docs/admin-guide.md` from pulldb-migrate.md + scheduled-cleanup.md + schema-migration.md
5. Create `docs/deployment.md` from pulldb-services.md + security-controls.md
6. Create `docs/development.md` from python-project-setup.md + coding-standards.md essentials

### Phase 2: Archive Historical
1. Move phase plans to docs/archived/phase-plans/
2. Move research docs to docs/archived/research/
3. Move legacy AWS docs to docs/archived/aws-legacy/

### Phase 3: Update & Clean
1. Update README.md with new structure
2. Update constitution.md
3. Delete obsolete files
4. Validate all links

---

## Files to DELETE (5 files)

1. `docs/TRUTH-MATRIX.md` - Obsolete tracking
2. `docs/drift-resolution-checklist.md` - Obsolete
3. `docs/vscode-diagnostics.md` - Obsolete troubleshooting
4. `design/README.md` - Outdated
5. `design/restore-workflow-questionnaire.md` - Obsolete
