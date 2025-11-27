# Copilot Instructions for pullDB

> **SLIM VERSION** - Optimized for context window efficiency. Use `list_dir` and `read_file` for details.

## Context Loading Architecture

pullDB uses a **tiered context system** separating universal guidance from project-specific extensions:

```
TIER 0: Self (Claude Opus 4.5)
    └── engineering-dna/standards/claude-opus-4-5.md

TIER 1: Guidance (Universal - READ-ONLY)
    └── engineering-dna/AGENT-CONTEXT.md          ← Entry point
    └── engineering-dna/standards/                ← Python, AWS, Database
    └── engineering-dna/protocols/                ← FAIL HARD, Pre-commit

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
2. **Read `.pulldb/CONTEXT.md`** - pullDB-specific extensions  
3. **Query `docs/KNOWLEDGE-POOL.json`** - Operational facts for your task
4. **Load task-specific overlay** - See table below

## Critical Directives

1. **TIERED LOADING**: Follow the hierarchy above, don't load everything
2. **KNOWLEDGE-POOL FIRST**: Query before solving—don't rediscover
3. **CONTINUOUS LEARNING**: Add discoveries to KNOWLEDGE-POOL.md immediately
4. **FAIL HARD**: Never silently degrade. Fail with: (1) what attempted, (2) why failed, (3) solutions

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
