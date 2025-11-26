# Project Status & Drift Ledger

## Project Overview

pullDB is a database restoration tool that pulls production MySQL backups from S3 and restores them to development environments. The system follows a **documentation-first, prototype-first** approach with extensive planning before implementation.

**Current Status (Nov 5 2025)**: All Phase 0 milestones complete: credentials/config/repositories, logging abstraction, domain error classes, worker poll loop, S3 backup discovery, downloader, disk capacity guard, myloader subprocess wrapper, post‑SQL executor, staging orphan cleanup, metadata table injection, atomic rename invocation module, restore orchestration (end‑to‑end logical chaining), CLI validation & enqueue & status command, daemon service runner (graceful shutdown + lifecycle metrics), metrics emission scaffolding, installer + packaging (interactive/non‑interactive + Debian maintainer scripts + systemd unit), and comprehensive integration tests (happy path + failure modes). Phase 0: 100% complete. Project in RELEASE FREEZE (bug/security fixes only) as of Nov 3 2025 (see `RELEASE-FREEZE.md`). **Security scan: 0 CVEs** (verified Nov 5 2025).

**Completed Work** (verified Nov 5 2025):
- ✅ MySQL 8.0.43 schema deployed (6 tables, 1 view, 1 trigger)
- ✅ Credential resolution (`pulldb/infra/secrets.py` ~399 lines) with Secrets Manager + SSM support
- ✅ Atomic rename stored procedure SQL file (`docs/atomic_rename_procedure.sql`) added
- ✅ Deployment script validation (dry-run, host conflict, missing SQL file, connection failure, drop failure, create failure, success) via unit tests
- ✅ Test suite (184 tests passed, 1 skipped, 1 xpassed: secrets, config, repos, logging, errors, exec, restore, post-SQL, staging, discovery, downloader, disk capacity integration, atomic rename invocation, CLI parsing + status command, procedure deployment, procedure versioning, preview procedure stripping logic, benchmark script validation, installer flags/validation/root enforcement, worker service lifecycle) – latest run 75.49s
- ✅ Versioned atomic rename stored procedure (header comment `Version: 1.0.0`)
- ✅ Preview stored procedure (`pulldb_atomic_rename_preview`) for safe inspection of atomic RENAME TABLE statement
- ✅ Deployment script enhancements: version validation, preview deployment flag, skip-version-check override, conditional preview stripping
- ✅ Benchmark script for atomic rename SQL build performance (`scripts/benchmark_atomic_rename.py`) with FAIL HARD input validation
- ✅ Expanded deployment + benchmark test coverage (version presence/missing/skip, preview include/exclude, benchmark JSON + error paths)
- ✅ CLI status command with --json, --wide, --limit options (5 tests)
- ✅ AI Agent Code Generation Standards (engineering-dna submodule) with modern Python patterns and FAIL HARD protocols

**Not Yet Implemented (Drift vs Initial Plan)**:
- ✅ Staging DB orphan cleanup (pattern matching + DROP operations) – atomic rename procedure still pending

Implemented Since Original Plan (previously marked missing):
- ✅ Structured JSON logging abstraction (baseline)
- ✅ Worker polling loop + event emission
- ✅ S3 backup discovery & selection logic
- ✅ Downloader (stream + disk space preflight + streaming extraction input)
- ✅ Atomic rename stored procedure deployment validation (script + tests)

**Immediate Milestone Goals (Restore Workflow Bootstrap)**:
1. Introduce logging & domain error classes (FAIL HARD runtime scaffolding)
2. Implement worker poll loop + event emission for `queued`→`running` transitions
3. Add S3 discovery + downloader with disk capacity guard
4. Integrate myloader execution (subprocess wrapper capturing stdout/stderr)
5. Execute post‑SQL scripts + record structured results JSON
6. Implement staging lifecycle (name generation, orphan cleanup, placeholder atomic rename)
7. Wire events + status updates in repositories (failed/complete)
8. Replace CLI placeholders with validation + enqueue + status listing
9. Add integration tests for happy path & failure modes (missing backup, disk insufficient, myloader error, post‑SQL failure)
10. Introduce metrics emission after baseline stability

**Quality Guardrail**: Each milestone increment MUST preserve 100% passing tests and extend coverage for new failure paths (FAIL HARD diagnostics required).

**Environment Context**:
- **Development environment** (`345321506926`) runs pullDB and needs cross-account S3 access to:
  - **Staging backups** (`333204494849`): `s3://pestroutesrdsdbs/daily/stg/` - **Primary for development** - Contains both newer and older mydumper format backups for testing
  - **Production backups** (`448509429610`): `s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/` - Older mydumper format (will migrate to newer format post-implementation)
- **Prototype development**: Use staging backups as primary source (has both formats available)
- Multi-format mydumper support required (deferred feature - see roadmap.md)

### Implementation Drift Tracking (Nov 2 2025)

Maintain a living drift ledger until restore workflow is complete:
- Repositories & credential/config layers: ✅ Implemented
- Logging abstraction & domain error classes: ✅ Implemented (item 1 complete)
- Worker poll loop & event emission: ✅ Implemented (item 2 complete)
- S3 discovery & downloader (disk capacity guard + streaming): ✅ Implemented (item 3 complete)
- CLI validation & enqueue & status: ✅ Implemented (argument parsing, validation, enqueue, status command with --json/--wide/--limit/--history/--filter/--rt)
- myloader execution subprocess wrapper: ✅ Implemented (command building, timeout + non‑zero translation)
- Post‑SQL executor: ✅ Implemented (sequential script execution, FAIL HARD on first error, timing + rowcount capture)
- Engineering-dna freshness CI gate: ✅ Implemented (workflow enforces submodule up-to-date)
- Engineering-dna baseline commit gate: ✅ Implemented (pre-commit + CI enforce tag-based baseline)
- Restore orchestration (staging lifecycle integration + post‑SQL chaining): ✅ Implemented (atomic rename module + stored procedure deployment validated with tests)
- Metadata table injection: ✅ Implemented (staging metadata table creation + JSON script report)
- Staging lifecycle: ✅ Orphan cleanup implemented (drop‑all); ✅ Atomic rename invocation module added (procedure existence validated at runtime); ✅ Stored procedure deployment script and tests implemented
- Integration tests (end‑to‑end restore workflow incl. failure modes: missing backup, disk insufficient, myloader error, post‑SQL failure): ✅ Implemented (happy path, optional real S3 listing, myloader failure, post‑SQL failure, disk insufficient, missing backup). Stored procedure deployment covered via unit tests (non-network fakes) ensuring FAIL HARD diagnostics.
- Metrics emission (queue depth, restore durations, disk failures): ✅ Implemented (logging-based counters/gauges/timers/events)

Test Suite Expansion: Current suite has grown from initial 9 tests to 181 passing tests (adds exec + myloader wrapper + post-SQL executor tests for success, non-zero exit, timeout, large output truncation, script failure; downloader disk capacity unit + integration tests; restore orchestration happy path & failure modes; atomic rename invocation module; CLI parsing + status command tests; stored procedure deployment script tests; daemon stop callback test; installer flag parsing, validation, systemd skip, root requirement enforcement). Future hardening deferred until post-freeze (Phase 1) focusing on staging cutover edge cases and performance profiling.

Testing Note (myloader wrapper): We deliberately monkeypatch `run_command` in restore tests to keep them deterministic and OS/binary agnostic—no dependency on a real `myloader` binary while still exercising error translation paths.

Testing Note (atomic rename deployment): Deployment script tests isolate behaviors without real MySQL by faking `mysql.connector.connect` and cursor execution paths, asserting FAIL HARD diagnostics for each failure mode before success.

Agents MUST update this section when a missing component lands (replace ❌/🚧 with ✅ and retain remaining incomplete rows). Do not remove incomplete rows prematurely; always preserve chronological progress for audit.
