# Phase 1 Planning (Post-Freeze)

**Status**: PLANNING ONLY - No implementation until freeze exits per RELEASE-FREEZE.md

**Created**: Nov 3 2025  
**Freeze Exit Target**: After meeting all stability criteria in RELEASE-FREEZE.md

This document captures Phase 1 feature backlog for evaluation after Phase 0 stabilizes. All items remain deferred until v0.1.0 release and freeze lift.

## Planning Principles

1. **Freeze Respect**: No implementation work during freeze; planning artifacts only
2. **FAIL HARD Documentation**: Each feature documents failure boundaries before coding
3. **Metric-Driven**: Phase 0 production metrics inform priority ranking
4. **Incremental**: Ship smallest valuable slice, validate in production, iterate
5. **Testing First**: Each feature requires test plan before implementation begins

## Backlog Overview

### High Priority (Address First After Freeze)

| Feature | Why | Metric Signal | Estimated Complexity |
|---------|-----|---------------|---------------------|
| Performance Profiling | Understand baseline restore times, identify bottlenecks | Average restore >30min observed | 1 week |
| Staging Cutover Edge Cases | Atomic rename failure recovery, long-running queries during cutover | Production incident potential | 2 weeks |
| Retry Logic with Exponential Backoff | Transient AWS failures (S3 throttling, network blips) block restores | Failed jobs requiring manual resubmit | 1 week |
| Enhanced Observability | Restore phase timing, S3 download rates, myloader progress | Debugging time per incident | 1 week |

### Medium Priority (Phase 1 Later)

| Feature | Why | Metric Signal | Estimated Complexity |
|---------|-----|---------------|---------------------|
| Job Cancellation | User-initiated stop for large restores consuming resources | Support requests for stuck jobs | 2 weeks |
| Archive Reuse Optimization | Reduce S3 egress/time for repeated restores | Backup download time % of total | 3 weeks |
| Multi-Format mydumper Support | Support older backup format from production | Production migration timeline | 2 weeks |
| Restore History & Audit | Track who restored what when for compliance | Audit/compliance requirements | 1 week |

### Low Priority (Phase 2+ Candidates)

| Feature | Why | Metric Signal | Estimated Complexity |
|---------|-----|---------------|---------------------|
| Partial Database Restore | Restore specific tables/schemas only | Storage cost for full restores | 4 weeks |
| Backup Validation Service | Pre-validate backups before restore attempts | Failed restores due to corrupt archives | 3 weeks |
| API Rate Limiting | Prevent queue flooding from automated tools | Job queue saturation events | 1 week |
| Web UI Dashboard | Visual status tracking instead of CLI-only | User preference feedback | 6 weeks |

## Detailed Feature Plans

### 1. Performance Profiling

**Goal**: Establish baseline restore performance metrics and identify optimization opportunities.

**Scope**:
- Instrument restore phases: S3 download, extraction, myloader, post-SQL
- Capture per-phase timing and data volume metrics
- Generate percentile distributions (p50, p90, p99) from production runs
- Profile myloader CPU/memory consumption
- Measure disk I/O patterns during restore

**FAIL HARD Boundaries**:
- Profiling overhead must not degrade restore performance >5%
- Profile data collection failures must not fail restores
- Missing profile data triggers warning log but continues restore

**Observability Additions**:
- New metrics: `restore_phase_duration_seconds{phase=download|extract|myloader|postsql}`
- New metrics: `restore_data_volume_bytes{phase=download|extracted}`
- New metrics: `myloader_cpu_percent`, `myloader_memory_mb`
- New events: `profiling_start`, `profiling_complete`, `profiling_error`

**Ranked Remediation**:
1. If profiling overhead >5%: Disable profiling, log warning, continue restore
2. If metric emission fails: Log locally to structured file, async upload to monitoring
3. If profiling library crashes: Catch exception, disable profiling, emit event

**Success Criteria**:
- Profile 20 production restores end-to-end
- Identify top 3 time-consuming phases with data
- Document optimization targets for Phase 1 iteration

**Tests Required**:
- Profile enablement/disablement toggle
- Profile data serialization and emission
- Overhead measurement (restore with/without profiling)
- Profiler exception handling (library failure graceful degradation)

### 2. Staging Cutover Edge Cases

**Goal**: Harden atomic rename procedure against real-world failure modes observed in production.

**Context**: Phase 0 atomic rename stored procedure implements basic RENAME TABLE logic but lacks edge case handling:
- Long-running queries holding metadata locks on target database
- Partial rename failure (some tables renamed, others fail)
- Target database already exists (should never happen but needs explicit handling)
- Session disconnect during rename (transaction boundary ambiguity)

**Scope**:
- Add metadata lock detection before rename attempt
- Implement lock wait timeout with configurable threshold
- Add rollback logic for partial rename failures
- Enhance stored procedure with pre-flight checks
- Document known failure modes and required manual recovery steps

**FAIL HARD Boundaries**:
- Detect metadata locks >30s: Fail restore immediately, log query details
- Partial rename: Fail immediately, leave staging intact, require manual review
- Pre-existing target: Fail before rename, log existing table list
- Lock detection failure: Fail restore, do not attempt blind rename

**Observability Additions**:
- New metric: `rename_lock_wait_seconds`
- New metric: `rename_partial_failure_count`
- New events: `rename_metadata_lock_detected{duration_ms, blocking_query}`
- New events: `rename_partial_failure{renamed_tables, failed_tables}`
- New events: `rename_precheck_failed{reason, tables_existing}`

**Ranked Remediation**:
1. Metadata lock detected: Wait up to 30s, then fail with query details + suggested kill command
2. Partial failure: Preserve staging DB, log renamed/failed table lists, require DBA review
3. Pre-existing target: Fail immediately, suggest manual DROP or rename conflict resolution
4. Lock detection tool unavailable: Fall back to blind rename with extended timeout

**Success Criteria**:
- Detect and handle metadata locks in 100% of test scenarios
- Document rollback procedures for each failure mode
- Test suite covers all 4 edge cases with assertions

**Tests Required**:
- Metadata lock simulation (long SELECT on target during rename)
- Partial failure injection (kill MySQL during multi-table rename)
- Pre-existing target conflict (create target before restore)
- Lock detection tool failure (mock INFORMATION_SCHEMA unavailable)

### 3. Retry Logic with Exponential Backoff

**Goal**: Automatically recover from transient AWS failures without manual job resubmission.

**Context**: Phase 0 immediately fails jobs on any S3/network error. Production metrics show ~5% of failures are transient (S3 throttling, temporary network partition).

**Scope**:
- Add retry decorator for S3 operations (list, head, get)
- Implement exponential backoff: 1s, 2s, 4s, 8s, 16s (max 5 attempts)
- Add jitter to prevent thundering herd
- Distinguish transient (retry) vs. permanent (fail) errors
- Emit retry attempt events for observability

**FAIL HARD Boundaries**:
- Max 5 retry attempts: After exhaustion, fail with full diagnostic history
- Non-retryable errors: Fail immediately (403 Forbidden, 404 Not Found)
- Retry budget exhausted: Fail with all attempt details + final error
- Clock drift detection: If retry delay calculation fails, use conservative fixed delay

**Observability Additions**:
- New metric: `s3_operation_retries_total{operation, outcome=success|failure}`
- New metric: `s3_retry_delay_seconds{attempt_number}`
- New events: `retry_attempt{operation, attempt_num, delay_ms, error}`
- New events: `retry_exhausted{operation, total_attempts, final_error}`

**Ranked Remediation**:
1. Transient error (throttle, timeout): Retry with backoff
2. Permanent error (not found, forbidden): Fail immediately with diagnostic
3. Retry budget exhausted: Fail with timeline of all attempts + suggest manual review
4. Retry logic bug: Log error, fall back to immediate failure (no infinite loops)

**Success Criteria**:
- Reduce transient failure rate from 5% to <1%
- Retry successful on at least 80% of transient errors
- No infinite retry loops (max 5 enforced)
- Test suite validates all retry paths

**Tests Required**:
- Transient error recovery (S3 throttling simulation)
- Retry budget exhaustion (permanent failure after 5 attempts)
- Immediate failure on non-retryable errors (404, 403)
- Exponential backoff timing validation
- Jitter randomness verification

### 4. Enhanced Observability

**Goal**: Surface restore progress and bottlenecks in real-time for debugging and capacity planning.

**Scope**:
- Add restore phase timing breakdown to job events
- Emit S3 download rate and progress percentage
- Capture myloader stdout/stderr in structured log events
- Add disk I/O metrics during restore phases
- Create Datadog dashboard with restore funnel visualization

**FAIL HARD Boundaries**:
- Metric emission failure must not fail restores
- Missing observability data triggers warning but continues
- Metric buffer overflow: Drop oldest, log warning, continue
- Dashboard query failure: Degrade gracefully, show cached data

**Observability Additions**:
- New metric: `s3_download_bytes_per_second`
- New metric: `restore_progress_percent{phase}`
- New metric: `disk_io_bytes_per_second{operation=read|write}`
- New events: `phase_progress{phase, percent, elapsed_ms}`
- New events: `myloader_output{line, stream=stdout|stderr}`

**Ranked Remediation**:
1. Metric emission fails: Queue locally, retry async, warn if buffer full
2. Dashboard unavailable: Serve cached snapshot with staleness warning
3. Excessive metric volume: Sample (every 10th event), log sampling rate
4. Log buffer overflow: Drop oldest events, emit overflow warning event

**Success Criteria**:
- Real-time progress tracking for 100% of restores
- Dashboard refresh <10s latency
- Zero observability-related restore failures
- Ops team can identify bottleneck phase in <5 minutes

**Tests Required**:
- Metric emission during restore phases
- Progress percentage calculation accuracy
- Buffer overflow handling (high event volume)
- Dashboard query caching on backend unavailable

## Phase 1 Roadmap (Tentative Order)

After freeze exit and v0.1.0 release:

1. **Week 1-2**: Performance Profiling
   - Instrument existing restore workflow
   - Collect baseline metrics from production
   - Document findings for optimization targets

2. **Week 3-4**: Enhanced Observability
   - Build on profiling work
   - Add real-time progress tracking
   - Deploy Datadog dashboard

3. **Week 5-6**: Staging Cutover Edge Cases
   - Informed by production incident data
   - Harden atomic rename procedure
   - Document failure recovery playbooks

4. **Week 7**: Retry Logic
   - Reduce manual resubmit burden
   - Based on Phase 0 failure rate data

5. **Week 8+**: Medium priority features (backlog grooming based on production learnings)

## Metrics to Collect During Freeze

To inform Phase 1 priorities, track these metrics during Phase 0 stabilization:

- Restore duration percentiles (p50, p90, p99)
- Failure rate by cause (S3, disk, myloader, post-SQL, atomic rename)
- Manual resubmit frequency (transient failure indicator)
- Support tickets related to restore issues
- Disk space exhaustion events
- Staging database orphan cleanup success rate

## Decision Points

**Defer to Phase 2** if during Phase 1:
- Archive reuse: If S3 download <20% of total restore time
- Multi-format mydumper: If production migration completes before Phase 1
- Partial restore: If storage costs remain within budget
- Web UI: If CLI adoption remains high and no accessibility issues

**Promote to High Priority** if:
- Job cancellation: Support ticket volume >5/week for stuck jobs
- Backup validation: Failed restore rate due to corrupt archives >2%
- API rate limiting: Queue saturation events observed

## Implementation Freeze Exit Checklist

Before starting Phase 1 implementation:

- [ ] v0.1.0 release tagged and published
- [ ] RELEASE-FREEZE.md archived as RELEASE-FREEZE-PHASE0.md
- [ ] All Phase 0 stability exit criteria met (see RELEASE-FREEZE.md)
- [ ] Baseline production metrics documented (restore times, failure rates)
- [ ] Phase 1 priorities ranked by metric data (not speculation)
- [ ] FAIL HARD documentation complete for top 2 features
- [ ] Test plans drafted for top 2 features
- [ ] Team capacity allocated for Phase 1 sprint

## Notes

- This document is a planning artifact only; no code changes allowed during freeze
- Priorities may shift based on production metrics collected during stabilization
- FAIL HARD boundaries must be documented before any implementation begins
- Each feature ships independently with full test coverage; no batch merges
- Regular backlog grooming sessions every 2 weeks during freeze to refine estimates

---
Document version: 1.0.0  
Next review: After freeze exit  
Owner: Technical Lead
