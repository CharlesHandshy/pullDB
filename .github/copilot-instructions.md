# Copilot Instructions for pullDB

## Overview

This document is the **primary reference for AI coding agents** working on pullDB. It distills the essential architecture, patterns, and constraints from the comprehensive documentation. Always read this file first, then consult other documents as needed.

**Related Documents**:
- **`engineering-dna/standards/ai-agent-code-generation.md`** - **MANDATORY for AI agents**: Modern Python patterns, file generation protocols, FAIL HARD standards, anti-patterns to avoid (created Nov 2025)
- **`constitution.md`** - Coding standards, tooling philosophy, and development workflow
- **`docs/coding-standards.md`** - Comprehensive style guidelines for all file types (Python, Markdown, SQL, Shell, YAML, Mermaid)
- **`docs/security-controls.md`** - Security controls for S3 and Secrets Manager (Implementation Verification)

**Knowledge Base Protocol**: Before answering any question or solving any problem, **ALWAYS check `docs/KNOWLEDGE-POOL.md` first**.
**CONTINUOUS LEARNING DIRECTIVE**: You must **continuously add anything you learn** to `docs/KNOWLEDGE-POOL.md` as you find it. Do not wait for final resolution. If you discover a quirk, a fix, a path, or a dependency issue, document it immediately in the Knowledge Pool. This directive is **ALWAYS ACTIVE**.

These documents form the foundation—all other documentation flows from these principles. **AI agents MUST follow the standards in `engineering-dna/standards/ai-agent-code-generation.md` when generating any code.**

## Architecture Principles

- **FAIL HARD Philosophy**: When operations cannot complete as designed, **fail immediately** with comprehensive diagnostics. Never silently degrade or work around issues. Always provide: (1) what was attempted, (2) what failed and why, (3) ranked solutions. See `constitution.md` for complete FAIL HARD requirements.
- **Three-Service Architecture**: CLI (thin client) → API Service (job management) → Worker Service (job execution)
- **API Service**: Accepts HTTP requests, validates input, inserts jobs to MySQL, provides status/discovery endpoints (read-only S3 access for backup listing)
- **Worker Service**: Polls MySQL queue, executes restores via S3 + myloader (full S3 read access for downloads, no HTTP exposure)
- **MySQL as Coordination Layer**: All state, locks, and job tracking via MySQL (accessed by API and Worker services)
- **Download-Per-Job**: No archive reuse in prototype - download fresh each time
- **Per-Target Exclusivity**: MySQL constraints prevent concurrent restores to same target database
- **Independent Services**: API and Worker never communicate directly - only via MySQL queue
- **CLI Capabilities Preserved**: All original functionality available through API service HTTP endpoints

## Key Files & Directory Structure

```
.github/copilot-instructions.md  # THIS FILE - Primary AI agent reference
.github/copilot-instructions-behavior.md # MANDATORY: FAIL HARD, Hygiene, Diagnostics
.github/copilot-instructions-python.md   # Python Standards, Code Style, File Ownership
.github/copilot-instructions-business-logic.md # Domain Logic, Constraints, Pitfalls
.github/copilot-instructions-testing.md  # Testing Strategy, Timeouts
.github/copilot-instructions-status.md   # Project Status, Drift Ledger
constitution.md                   # Coding standards and development workflow (co-primary)
design/
  └── two-service-architecture.md # API Service + Worker Service split (CRITICAL)
docs/
  ├── coding-standards.md         # Comprehensive style guide for all file types
  ├── mysql-schema.md             # Complete database schema with invariants
  ├── testing.md                  # Testing guide with AWS integration (NEW Nov 2025)
 ├── AWS-SETUP.md                # Complete AWS setup and configuration guide
  ├── aws-authentication-setup.md # AWS cross-account setup for EC2 (RECOMMENDED)
  ├── aws-secrets-manager-setup.md # AWS Secrets Manager credential resolution (IMPLEMENTED)
  ├── vscode-diagnostics.md       # VS Code diagnostic integration
  └── parameter-store-setup.md    # Secure credential storage in AWS
pulldb/
  ├── infra/
  │   ├── secrets.py              # IMPLEMENTED - Credential resolution (Secrets Manager + SSM)
  │   ├── mysql.py                # IMPLEMENTED - Repositories (Job/User/Host/Settings) + thin pool wrapper
  │   ├── logging.py              # IMPLEMENTED - Structured JSON logging
  │   ├── s3.py                   # IMPLEMENTED - Backup discovery & selection
  │   └── exec.py                 # IMPLEMENTED - subprocess wrapper (myloader)
  ├── worker/
  │   ├── service.py             # IMPLEMENTED - Poll loop + event emission
  │   ├── downloader.py          # IMPLEMENTED - Stream download + disk capacity guard
  │   ├── restore.py             # IMPLEMENTED - Restore workflow orchestration
  │   ├── staging.py             # IMPLEMENTED - Staging DB lifecycle
  │   └── post_sql.py            # IMPLEMENTED - Post-restore SQL execution
  ├── domain/
  │   ├── config.py               # IMPLEMENTED - Two-phase environment + MySQL settings enrichment
  │   ├── models.py               # IMPLEMENTED - Dataclasses (Job, JobEvent, etc.)
  │   ├── errors.py               # IMPLEMENTED - Structured FAIL HARD runtime errors
  │   └── restore_models.py       # IMPLEMENTED - myloader + post-SQL DTOs
  └── tests/
      ├── ...                     # Comprehensive suite (unit + integration: discovery, downloader, repos, errors, loop, logging, exec, restore, post_sql, disk capacity)

> Current suite: 181 passing tests (+1 skipped, +1 xpassed) covering discovery, downloader (including disk capacity integration tests), logging, errors, myloader wrapper, post-SQL executor, restore orchestration, metadata injection, atomic rename invocation, CLI parsing, procedure deployment, versioned + preview procedures, benchmark script scenarios, and installer behaviors (flags, systemd skip, validation warnings, root enforcement).
customers_after_sql/              # Post-restore SQL for customer databases (PII removal)
  ├── 010.remove_customer_pii.sql
  ├── 020.remove_billto_info.sql
  └── ... (120.reset_business_registration.sql)
qa_template_after_sql/            # Post-restore SQL for QA templates (currently empty)
  └── README.md                   # Explains no scripts needed for QA templates
reference/                        # Legacy PHP implementations (read-only)
  ├── pullDB-auth                 # Customer restore with obfuscation
  └── pullQA-auth                 # QA template restore
scripts/
  ├── verify-secrets-perms.sh     # Secrets Manager permission verification (Nov 2025)
  └── README.md                   # Script usage documentation
```

**Documentation Hierarchy**: This file + constitution.md are top-level guides. All other docs elaborate on specific aspects defined here.

## Instruction Categories (Load As Needed)

To minimize context window usage, detailed instructions have been categorized. **You MUST read the relevant category file before performing specific tasks.**

### 1. Behavior & Hygiene (MANDATORY)
**File**: `.github/copilot-instructions-behavior.md`
**When to read**: ALWAYS before starting any task.
**Contents**:
- **FAIL HARD Mandate**: Diagnostic protocols, prohibited behaviors.
- **Warning Eradication**: How to handle linter warnings.
- **Pre-Commit Hygiene**: Checklist for committing code.
- **Error Message Standards**: How to write actionable exceptions.

### 2. Python Standards
**File**: `.github/copilot-instructions-python.md`
**When to read**: Before writing or modifying Python code.
**Contents**:
- **Code Style**: PEP 8, type hints, docstrings.
- **File Ownership**: Rules for file permissions in dev environment.
- **Dependency Patterns**: Libraries to use (boto3, mysql-connector, etc.).
- **Repository Pattern**: How to structure data access.
- **Test Database Credentials**: Mandatory use of Secrets Manager in tests.

### 3. Business Logic & Domain
**File**: `.github/copilot-instructions-business-logic.md`
**When to read**: Before implementing features or fixing bugs in core logic.
**Contents**:
- **Critical Constraints**: CLI usage, Schema patterns, Config philosophy.
- **Domain Logic**: User code gen, Target naming, S3 discovery, Disk capacity.
- **Restore Workflow**: Read-only restore, Post-SQL scripts, Staging-to-Production rename.
- **Common Pitfalls**: What to avoid.

### 4. Testing Strategy
**File**: `.github/copilot-instructions-testing.md`
**When to read**: Before writing tests or debugging test failures.
**Contents**:
- **Testing Strategy**: Unit vs Integration.
- **Timeout Monitoring**: Protocol for detecting hangs (CRITICAL).

### 5. Project Status & Drift
**File**: `.github/copilot-instructions-status.md`
**When to read**: To understand current progress or update the drift ledger.
**Contents**:
- **Project Status**: Completed work, missing features.
- **Drift Ledger**: **Agents MUST update this section** when components land.
