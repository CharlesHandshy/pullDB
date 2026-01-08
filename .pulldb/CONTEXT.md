# pullDB Local Augmentation Store

> **PURPOSE**: Project-specific extensions to engineering-dna standards.
> This is NOT a replacement for engineering-dna—it EXTENDS and AUGMENTS the shared guidance.

**Version**: 1.0.0 | **Updated**: November 2025

---

## Relationship to engineering-dna

```
engineering-dna/           ← Shared template (READ-ONLY from pullDB)
  ├── AGENT-CONTEXT.md    ← Universal AI agent entry point
  ├── docs/triage-system.md  ← Intelligent context loading
  ├── metadata/documentation-index.json  ← Document catalog
  ├── standards/          ← Universal coding standards
  └── protocols/          ← Universal operational protocols

.pulldb/                   ← Project augmentation (OWNED by pullDB)
  ├── CONTEXT.md          ← This file (project entry point)
  ├── standards/          ← pullDB-specific patterns
  └── extensions/         ← Domain-specific implementations
```

### Loading Priority

**Version**: engineering-dna v0.1.2-alpha (January 2026)

1. **engineering-dna** → Base patterns (FAIL HARD, type hints, pre-commit)
   - Uses automated triage system for intelligent document loading
   - See `engineering-dna/docs/triage-system.md` for details
2. **.pulldb/** → Project-specific extensions (myloader, staging, restore flow)
3. **docs/** → Operational facts (account IDs, secrets, lessons learned)

---

## pullDB Architecture Context

```
CLI → API Service → MySQL Queue ← Worker Service → S3/myloader
```

**Core Architecture**: Hierarchical Containment Architecture (HCA) is the strict standard for all new development.

### HCA Layer Model

```
plugins/  → pulldb/binaries/          External integrations
pages/    → pulldb/cli/, web/, api/   User-facing entry points  
widgets/  → pulldb/worker/service.py  Job orchestration
features/ → pulldb/worker/*.py        Business logic
entities/ → pulldb/domain/            Data models
shared/   → pulldb/infra/             Infrastructure
```

> **CRITICAL**: All new code MUST follow `.pulldb/standards/hca.md`

| Component | DNA Standard | pullDB Extension |
|-----------|--------------|------------------|
| Error handling | `protocols/fail-hard.md` | `.pulldb/standards/restore-errors.md` |
| Database | `standards/database.md` | `.pulldb/extensions/mysql-user-separation.md` |
| AWS | `standards/aws.md` | `.pulldb/extensions/cross-account-s3.md` |
| Testing | `protocols/test-timeout-monitoring.md` | `.pulldb/standards/integration-tests.md` |

---

## Directory Index

### standards/ (Project Patterns)

| Document | Purpose | Extends |
|----------|---------|---------|
| **`hca.md`** | **Hierarchical Containment Architecture standard** | HCA methodology |
| `myloader.md` | myloader subprocess wrapper patterns | `ai-agent-code-generation.md` |
| `restore-flow.md` | Restore workflow orchestration | `fail-hard.md` |
| `staging-rename.md` | Staging database lifecycle | `database.md` |
| `post-sql.md` | Post-restore SQL execution | `database.md` |

### extensions/ (Domain Implementations)

| Document | Purpose | Extends |
|----------|---------|---------|
| `mysql-user-separation.md` | Service-specific MySQL users | `database.md` |
| `cross-account-s3.md` | Multi-account S3 access | `aws.md` |
| `mydumper-formats.md` | Backup format detection/handling | N/A (domain-specific) |

---

## Quick Reference: What Goes Where

### engineering-dna/ (Universal)
- ✅ FAIL HARD protocol
- ✅ Modern Python type hints
- ✅ Pre-commit hygiene
- ✅ Test timeout monitoring
- ✅ AWS credential patterns (general)
- ✅ Database security patterns (general)

### .pulldb/ (Project Extensions)
- ✅ myloader subprocess invocation patterns
- ✅ Staging database naming convention
- ✅ Restore workflow state machine
- ✅ Post-SQL script execution order
- ✅ pulldb_api/worker/loader user separation
- ✅ S3 backup discovery algorithm

### docs/ (Operational Facts)
- ✅ Account IDs (345321506926, etc.)
- ✅ Secret paths (/pulldb/mysql/*)
- ✅ IAM role ARNs
- ✅ S3 bucket names and paths
- ✅ Lessons learned from production

### .github/copilot-instructions*.md (Session)
- ✅ Entry point for AI agents
- ✅ Task-specific overlays
- ✅ Cross-references to all tiers

---

## AI Agent Integration

### Before Starting Work

```
1. Read engineering-dna/AGENT-CONTEXT.md (base patterns)
   - Uses triage system to load relevant standards/protocols automatically
   - See engineering-dna/docs/triage-system.md for intelligent loading
2. Read .pulldb/CONTEXT.md (this file - project extensions)
3. Query docs/KNOWLEDGE-POOL.json for relevant facts
4. Check .github/copilot-instructions.md for task-specific guidance
```

**Note**: The triage system (engineering-dna v0.1.2-alpha) automatically selects relevant documentation based on task analysis, reducing token consumption by 40-60% while maintaining quality.

### Ongoing Behaviors (AUTOMATIC)

These happen continuously without user prompting:

| Behavior | Trigger | Action |
|----------|---------|--------|
| **HCA Enforcement** | Creating/modifying files | Place in correct layer, validate imports |
| **Session Logging** | Significant work completed | Append to `.pulldb/SESSION-LOG.md` |
| **Knowledge Pool Updates** | New facts discovered | Add to `docs/KNOWLEDGE-POOL.md` |

### Session Logging

**Mandatory**: Log significant work to `.pulldb/SESSION-LOG.md`

```markdown
## YYYY-MM-DD | Brief Topic

### Context
What prompted this work

### What Was Done
- Concrete actions

### Rationale
WHY decisions were made (reference principles)

### Files Modified
- `path/to/file.py`
```

### When Discovering New Patterns

| Discovery Type | Record In |
|----------------|-----------|
| Universal pattern (applies to any project) | engineering-dna/ (propose upstream) |
| pullDB-specific pattern (restore, staging, etc.) | .pulldb/standards/ or extensions/ |
| Operational fact (account ID, secret path) | docs/KNOWLEDGE-POOL.md |
| Lesson learned (debugging resolution) | docs/KNOWLEDGE-POOL.md |

---

## Related Documents

- [engineering-dna/AGENT-CONTEXT.md](../engineering-dna/AGENT-CONTEXT.md) - Universal AI entry point
- [docs/KNOWLEDGE-POOL.md](../docs/KNOWLEDGE-POOL.md) - Operational facts
- [constitution.md](../constitution.md) - Project governance
