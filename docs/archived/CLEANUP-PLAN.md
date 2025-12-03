# Archived Documentation Cleanup Plan

> Triage of 62 files in `docs/archived/`

## Action Categories

### 1. DELETE (Marked OBSOLETE) - 4 files

Files explicitly marked obsolete:
- `aws-cross-account-setup.md.OBSOLETE`
- `aws-iam-setup.md.OBSOLETE`
- `aws-service-role-setup.md.OBSOLETE`
- `aws-setup.md.OBSOLETE`

**Action**: Delete immediately

### 2. DELETE (Superseded) - ~20 files

Files superseded by current documentation:
- `installation.md` → superseded by `getting-started.md`
- `pulldb-cli.md` → superseded by `cli-reference.md`
- `pulldb-admin-cli.md` → superseded by `admin-guide.md`
- `mysql-setup.md` → superseded by `deployment.md`
- `testing.md` → superseded by `development.md`
- `coding-standards.md` → superseded by `engineering-dna/`
- `python-project-setup.md` → superseded by `development.md`
- Phase/milestone plans (completed):
  - `milestone-2-plan.md`
  - `phase-3-plan.md`
  - `phase-4-implementation.md`
  - `phase-4-testing-plan.md`
  - `PHASE1-PLANNING.md`

**Action**: Delete after confirming no unique content

### 3. MIGRATE TO HCA - ~15 files

Files with valuable content to migrate:
- `backup-formats.md` → `docs/hca/plugins/` (myloader formats)
- `concurrency-controls.md` → `docs/hca/features/`
- `security-model.md` → `docs/hca/shared/`
- `staging-rename-pattern.md` → `docs/hca/features/staging.md`
- `restore-execution.md` → `docs/hca/features/restore.md`
- `two-service-architecture.md` → `docs/hca/widgets/architecture.md`

**Action**: Review and merge into HCA structure

### 4. KEEP AS HISTORICAL - ~10 files

Planning docs with historical value:
- `appalachian_workflow_plan.md`
- `worker_build_plan.md`
- `plan-metadata-synthesis.md`
- `reference-analysis.md`

**Action**: Move to `docs/archived/historical/`

### 5. MOVE TO RUNBOOKS - ~5 files

Operational content:
- `drift-resolution-checklist.md` → `design/runbook-drift.md`
- `test-environment.md` → `design/runbook-test-env.md`

**Action**: Migrate to design/runbooks

### 6. REVIEW NEEDED - remaining

Files requiring manual review to determine fate.

## Cleanup Commands

```bash
# Phase 1: Delete OBSOLETE files
cd docs/archived
rm -f *.OBSOLETE

# Phase 2: Create historical subfolder
mkdir -p historical
mv appalachian_workflow_plan.md historical/
mv worker_build_plan.md historical/
mv plan-metadata-synthesis.md historical/

# Phase 3: Delete superseded files
rm -f installation.md pulldb-cli.md pulldb-admin-cli.md
rm -f milestone-2-plan.md phase-3-plan.md phase-4-*.md PHASE1-PLANNING.md
```

## Preservation Principle

Before deleting any file:
1. Check git history - content is preserved
2. Verify no unique valuable content
3. Confirm superseding doc exists in HCA structure
