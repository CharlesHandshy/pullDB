# Worker Isolation & Build-Out Plan (Nov 2025)

## 1. Purpose
Create a focused roadmap for the worker service so it can be built, validated, and operated independently of CLI/API concerns while honoring Release Freeze guardrails (bug/security fixes only) and the restore-only execution model captured in `docs/appalachian_workflow_plan.md`. The isolation described here applies only during active development and testing; once the worker proves stable, its components are reintegrated into the broader deployment topology per the two-service architecture.

## 2. Scope & Constraints
- **In-scope**: MySQL queue polling, S3 backup acquisition, disk guardrails, dual myloader restores (0.19 + 0.9), post-restore SQL execution, atomic rename, log normalization, metrics/heartbeat, artifact archival.
- **Out-of-scope**: CLI argument parsing, API request validation, job enqueueing, dump generation, future multi-format support (deferred per roadmap).
- **Constraints**: FAIL HARD diagnostics, release freeze (only security/bug fixes), deterministic staging lifecycle, AWS profile rules (Secrets Manager via `pr-dev`, S3 via `pr-staging/pr-prod` when necessary).
- **Integration Plan**: After isolation milestones complete (Phase D), merge the worker-specific modules back into the shared deployment flow (CLI/API + worker releasing together) ensuring config schemas and logging formats stay aligned.

## 3. Isolation Strategy
1. **Process Boundary**: Maintain worker as a dedicated service (`pulldb.worker.service`) with its own dependency graph (infra + worker packages). No CLI imports allowed beyond domain models.
2. **Config Surface**: Worker reads only the subset of configuration needed for queue polling + restore execution; ensure `pulldb.domain.config` exposes a worker-specific view to avoid CLI flags bleeding in.
3. **Interface Contracts**:
   - Repositories: `JobRepository`, `JobEventRepository`, `HostRepository` already shared—stabilize signatures and document expectations.
   - Infra: `CredentialResolver`, `S3BackupClient`, `DiskGuard`, `MyLoaderRunner`, `PostSqlExecutor`, `AtomicRenameInvoker`—treat as plugin-style modules wired via dependency injection for easier testing/mocking.
4. **Log/Telemetry Channel**: Standardize on structured JSON logging + metrics (see `docs/appalachian_workflow_plan.md` §3 & §4) so downstream consumers see identical payloads regardless of worker mode.

## 4. Build-Out Phases
### Phase A: Foundations (Prereq hardening)
- [ ] Confirm repositories + credential resolution have full test coverage (already at 100% per Release Freeze; re-verify).
- [ ] Extract worker-specific config loader (two-phase env + MySQL settings) from `pulldb.domain.config` into `pulldb.worker.config` for isolation.
- [ ] Introduce log normalization module shared between worker + CLI status command (per `appalachian_workflow_plan` §3).

### Phase B: Workflow Orchestration Core
- [ ] Implement staged pipeline object aligning with §5 (Job Intake → S3 Selection → Download → Extraction → Restore 0.19 → Restore 0.9 → Post-SQL → Atomic Cutover → Artifact + Metrics → Completion).
- [ ] Embed heartbeat publisher (every 60s) emitting `{job_id, stage, last_table, percent}`.
- [ ] Wire stop-logic hooks for checksum mismatch, sql_mode retry, dependency failures, and hangs (lack of progress >5m).

### Phase C: Observability & Artifacts
- [ ] Integrate structured event bus for UI progress (Normalized events stored in `job_events.detail` JSON and emitted to logs).
- [ ] Archive stage logs per job into `.tar.gz` and upload to artifact store / attach to job record per §5.1 step 9.
- [ ] Extend metrics emitter (queue depth, stage durations, warnings count).

### Phase D: Testing & Validation
- [ ] Unit tests for each stage (inject fakes for S3, disk guard, loaders).
- [ ] Integration tests re-running restore workflow with staged backups (happy path + failure modes enumerated in plan §4).
- [ ] Load tests verifying queue throughput + disk guard concurrency.
- [ ] Operational drills: simulate missing backup, tar corruption, sql_mode violation, atomic rename failure.

## 5. Deliverables
- Source: `pulldb/worker/` modules refactored per phases above.
- Docs: Updated `design/runbook-restore.md`, `docs/appalachian_workflow_plan.md`, and new release notes capturing changes.
- Tests: Pytest coverage for new components, ensuring no drop in overall test counts.
- Ops: Systemd overrides / deployment notes reflecting new config surface + log outputs.

## 6. Milestone Checklist
| Item | Evidence | Owner |
| --- | --- | --- |
| Config isolation complete | `pulldb.worker.config` module + tests | Worker team |
| Log normalization module live | Shared util referenced by worker + CLI | Worker + CLI |
| Orchestration pipeline delivered | Stage class graph + end-to-end tests | Worker team |
| Observability hooks verified | Heartbeat logs + metrics dashboards | SRE |
| Runbook updated | `design/runbook-restore.md` references new flow | Docs |
| Release freeze compliance | Tests + lint pass, no feature creep | All |

## 7. References
- `docs/appalachian_workflow_plan.md` – lessons, log templates, stage checklist + diagram.
- `design/runbook-restore.md` – operator playbook (now referencing §7 summary/diagram).
- `design/two-service-architecture.md` – overarching split between API and worker services.
- `constitution.md` & `engineering-dna/standards/ai-agent-code-generation.md` – coding + FAIL HARD standards.

## 8. Current Iteration (Nov 19 2025)
- **Goal**: Deliver the log normalization module shared by worker + CLI, matching the patterns documented in `docs/appalachian_workflow_plan.md` §3.
- **Doc**: Update this plan + runbook references so operators know normalization is underway and how it feeds progress UIs.
- **Test**: Create targeted unit tests that feed representative myloader 0.19/0.9 log lines through the normalizer and assert structured output (phase, thread, table, severity, warnings bucket).
- **Build**: Implement `pulldb.worker.log_normalizer` (name TBD) with dataclasses, regex helpers, and severity classification; expose a streaming API the worker can call while tailing subprocess output.
- **Review**: Run the worker test subset (`pytest pulldb/tests/test_worker_log_normalizer.py`) plus existing suites; capture findings + follow-ups before moving to the next iteration (likely heartbeat publisher wiring).
