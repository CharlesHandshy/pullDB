# Copilot Instructions for pullDB

> **SLIM VERSION** - Optimized for context window efficiency. Use `list_dir` and `read_file` for details.

## Critical Directives

1. **KNOWLEDGE-POOL FIRST**: Check `docs/KNOWLEDGE-POOL.md` before any task
2. **CONTINUOUS LEARNING**: Add discoveries to KNOWLEDGE-POOL.md immediately
3. **FAIL HARD**: Never silently degrade. Fail with: (1) what attempted, (2) why failed, (3) solutions

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

| Task Type | File |
|-----------|------|
| **Any task** (mandatory) | `.github/copilot-instructions-behavior.md` |
| Python code | `.github/copilot-instructions-python.md` |
| Domain/business logic | `.github/copilot-instructions-business-logic.md` |
| Writing tests | `.github/copilot-instructions-testing.md` |
| Status/progress | `.github/copilot-instructions-status.md` |

## Key Reference Docs

| Doc | Purpose |
|-----|---------|
| `constitution.md` | Coding standards, workflow |
| `engineering-dna/standards/ai-agent-code-generation.md` | **MANDATORY** Python patterns |
| `docs/mysql-schema.md` | Database schema + invariants |
| `design/two-service-architecture.md` | API/Worker split |

## Directory Quick Reference

Use `list_dir` for full structure. Key paths:

- `pulldb/infra/` - secrets, mysql, logging, s3, exec
- `pulldb/worker/` - service, downloader, restore, staging, post_sql
- `pulldb/domain/` - config, models, errors
- `tests/` - comprehensive test suite
- `customers_after_sql/` - PII removal scripts
- `reference/` - legacy PHP (read-only)
