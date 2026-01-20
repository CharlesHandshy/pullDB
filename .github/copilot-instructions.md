# Copilot Instructions for pullDB

> **SLIM VERSION** - Optimized for context window efficiency. Use `list_dir` and `read_file` for details.

## HCA Activation

**All development MUST follow Hierarchical Containment Architecture (HCA).**

Before creating or modifying files:
1. **Determine HCA layer**: shared → entities → features → widgets → pages → plugins
2. **Place file correctly**: See layer mapping below
3. **Validate imports**: Only import from same or lower layers
4. **Name explicitly**: File names include layer context

```
┌─────────────────────────────────────────────────────┐
│ plugins/  → pulldb/binaries/        External tools │
├─────────────────────────────────────────────────────┤
│ pages/    → pulldb/cli/, web/, api/ Entry points   │
├─────────────────────────────────────────────────────┤
│ widgets/  → pulldb/worker/service   Orchestration  │
├─────────────────────────────────────────────────────┤
│ features/ → pulldb/worker/*.py      Business logic │
├─────────────────────────────────────────────────────┤
│ entities/ → pulldb/domain/          Data models    │
├─────────────────────────────────────────────────────┤
│ shared/   → pulldb/infra/           Infrastructure │
└─────────────────────────────────────────────────────┘
```

> **Reference**: `.pulldb/standards/hca.md` for detailed guidance

## Context Loading Architecture

**Engineering-DNA Version**: v0.1.2-alpha (January 2026)

pullDB uses a **tiered context system** with **automated triage** for intelligent document loading:

```
TIER 0: Self (Claude Opus 4.5)
    └── engineering-dna/standards/claude-opus-4-5.md

TIER 1: Guidance (Universal - READ-ONLY)
    └── engineering-dna/AGENT-CONTEXT.md          ← Entry point
    └── engineering-dna/docs/triage-system.md     ← Intelligent loading
    └── engineering-dna/metadata/documentation-index.json  ← Document catalog
    └── engineering-dna/standards/                ← Python, AWS, Database (auto-selected)
    └── engineering-dna/protocols/                ← FAIL HARD, Pre-commit (auto-selected)

TIER 2: Augmentation (pullDB-specific)
    └── .pulldb/CONTEXT.md                        ← Project entry point
    └── .pulldb/standards/                        ← myloader, staging, restore
    └── .pulldb/extensions/                       ← MySQL user separation

TIER 3: Operational (Runtime facts)
    └── docs/KNOWLEDGE-POOL.md + .json            ← Account IDs, secrets, ARNs
    └── docs/mysql-schema.md                      ← Schema definition

TIER 4: Session (Task-specific)
    └── .github/copilot-instructions-*.md         ← Behavior, Python, Testing
```

### Loading Priority

1. **Read `engineering-dna/AGENT-CONTEXT.md`** - Universal AI patterns
   - **NEW**: Triage system automatically loads relevant standards/protocols
   - Reduces token consumption by 40-60% while maintaining quality
   - See `engineering-dna/docs/triage-system.md` for details
2. **Read `.pulldb/CONTEXT.md`** - pullDB-specific extensions  
3. **Query `docs/KNOWLEDGE-POOL.json`** - Operational facts for your task
4. **Load task-specific overlay** - See table below

## Critical Directives

1. **INTELLIGENT LOADING**: Triage system (engineering-dna v0.1.2-alpha) automatically selects relevant docs
   - Don't manually load all standards—let the triage system optimize
   - See `engineering-dna/docs/triage-system.md` for how it works
2. **KNOWLEDGE-POOL FIRST**: Query before solving—don't rediscover
3. **CONTINUOUS LEARNING**: Add discoveries to KNOWLEDGE-POOL.md immediately
4. **FAIL HARD**: Never silently degrade. Fail with: (1) what attempted, (2) why failed, (3) solutions
5. **ROOT CAUSE FIXING**: FIX IT - NOT BANDAID IT. See `engineering-dna/protocols/root-cause-fixing.md`
   - Search for source of problem
   - Reflect on problem to plan complete fix
   - Test the fix and verify it solves the root cause
   - Check edge cases and related code
   - Never suppress errors via configuration—fix the actual code
6. **SESSION LOGGING**: Automatically log work to `.pulldb/SESSION-LOG.md` (see below)

## Session Logging (AUTOMATIC)

**Like HCA, this is mandatory and ongoing without user prompting.**

### When to Log
- **Session start**: Note the topic/goal when context becomes clear
- **After significant work**: Major fixes, audits, refactors, new features
- **Before session end**: Summarize if substantial work was done

### Log Format (append to `.pulldb/SESSION-LOG.md`)
```markdown
## YYYY-MM-DD | Brief Topic

### Context
What prompted this work (user request, bug found, etc.)

### What Was Done
- Concrete action 1
- Concrete action 2

### Rationale
WHY these decisions were made (reference principles, laws, standards)

### Files Modified
- `path/to/file.py` (what changed)
```

### Guidelines
- **Be concise** but capture the WHY
- **Reference principles** (FAIL HARD, HCA, Laws of UX, etc.)
- **Include findings** from audits
- **Newest entries first** (reverse chronological)
- **Don't duplicate** - one entry per topic per day

## Architecture (Mental Model)

```
CLI → API Service → MySQL Queue ← Worker Service → S3/myloader
```

- **MySQL** = all coordination, state, locks
- **Per-target exclusivity** via MySQL constraints
- **Download-per-job** (no archive reuse)
- Services communicate **only** via MySQL queue

## Load-On-Demand Categories

Read the relevant file **before** performing that type of task:

| Task Type | engineering-dna | .pulldb/ | .github/ |
|-----------|-----------------|----------|----------|
| **Any task** | `AGENT-CONTEXT.md` | `CONTEXT.md` | `copilot-instructions-behavior.md` |
| **New code/files** | | **`standards/hca.md`** | |
| Python code | `standards/python.md`, `ai-agent-*.md` | | `copilot-instructions-python.md` |
| myloader/restore | | `standards/myloader.md` | |
| Staging databases | `standards/database.md` | `standards/staging-lifecycle.md` | |
| MySQL credentials | `standards/database.md` | `extensions/mysql-user-separation.md` | |
| AWS/S3 | `standards/aws.md` | | |
| Testing | `protocols/test-timeout-monitoring.md` | | `copilot-instructions-testing.md` |
| Status/progress | | | `copilot-instructions-status.md` |

## Key Reference Docs

| Doc | Purpose | Tier |
|-----|---------|------|
| `engineering-dna/AGENT-CONTEXT.md` | Universal AI entry point | 1 |
| `.pulldb/CONTEXT.md` | **pullDB extensions entry point** | 2 |
| **`.pulldb/standards/hca.md`** | **HCA layer model & enforcement** | 2 |
| `docs/KNOWLEDGE-POOL.md` | AWS/infra quick facts | 3 |
| `docs/WORKSPACE-INDEX.md` | Atomic-level code index | 3 |
| `constitution.md` | Project governance | 3 |
| `docs/mysql-schema.md` | Database schema + invariants | 3 |

## Directory Quick Reference

Use `list_dir` for full structure. Key paths:

- `engineering-dna/` - Universal guidance (submodule, read-only)
- `.pulldb/` - **Project-specific extensions** (owned by pullDB)
- `pulldb/infra/` - secrets, mysql, logging, s3, exec
- `pulldb/worker/` - service, downloader, restore, staging, post_sql
- `pulldb/domain/` - config, models, errors
- `docs/` - Operational facts, schema, setup guides
- `tests/` - comprehensive test suite
