# Release Freeze Policy (Initiated Nov 3 2025)

The pullDB project has entered a release freeze following Phase 0 completion.
Only critical fixes are allowed until stability criteria are met. This document
defines allowed change types, required validation, and exit conditions.

## Scope

Applies to all files under repository root excluding transient artifacts.

## Allowed Changes

| Category | Examples | Review Requirements |
|----------|----------|---------------------|
| Bug Fix | Logic error in restore workflow; incorrect disk calculation; broken CLI flag | 2 reviewer approvals + test update |
| Security Fix | Dependency CVE patch; secret exposure remediation; IAM policy hardening | Security review + changelog entry |
| Critical Ops | Deployment script reliability; systemd unit hardening; installer failure correction | Ops sign-off + regression tests |
| Doc Correction | Factual mismatch (test counts, versions), typo in procedures | Single reviewer approval |

## Disallowed Changes

| Category | Examples |
|----------|----------|
| New Feature | New CLI command, new API endpoint, retry logic, cancellation |
| Non-essential Refactor | Code style-only edits, abstraction rewrites without defect |
| Performance Optimization | Caching, parallelism, batching enhancements |
| Cosmetic Documentation | Formatting-only README changes, new diagrams without functional change |

## Mandatory Gates for Allowed Changes

1. `ruff check` and `ruff format` clean
2. `mypy` strict passing
3. Full test suite passing (`pytest -q --timeout=60 --timeout-method=thread`)
4. Commit message follows hygiene template with updated test counts
5. README and copilot instructions updated only if factual change
6. No reduction in test coverage (add tests for new bug/security paths)
7. Security fixes include dependency version pin rationale

## Stability Exit Criteria

| Criterion | Target |
|-----------|--------|
| Successful Production Restores | ≥ 10 |
| Unhandled Exceptions | 0 over 14 consecutive days |
| Average Restore Duration | < 30 minutes |
| Post-SQL Script Success Rate | 100% across customer & QA template runs |
| Orphaned Staging Cleanup | 100% success (no leftovers after subsequent restores) |
| Metrics Accuracy | Queue depth & disk failure metrics validated |
| Security Scan | No critical/high CVEs outstanding |

## Change Request Workflow

1. Open issue labeled `freeze-fix` with Goal/Problem/Root Cause/Solutions.
2. Attach reproduction steps and failing test (if bug) or CVE advisory (if security).
3. Implement minimal change; add/adjust tests.
4. Provide FAIL HARD diagnostic example in PR description.
5. Obtain required approvals; merge after CI green.

## Emergency Changes

For production-impacting outages (restore failure across all jobs):
- Bypass standard review only with incident commander approval
- Post-merge retrospective required within 24h
- Retrospective adds section to this file documenting incident and resolution

## Versioning & Tagging

- Tag each approved change: `v0.0.1-freeze.<n>` incrementing `<n>`
- Final stable release after exit criteria: promote to `v0.1.0`

## Monitoring Checklist

- Datadog dashboard: queue depth, active restores, restore durations, disk failures
- Log sampling: verify structured fields present (job_id, phase)
- AWS Secrets rotation check weekly
- Disk space audit before large restore tests

## Retrospective Template

```
Incident: <summary>
Date: <UTC timestamp>
Impact: <scope>
Root Cause: <analysis>
Resolution: <fix>
Follow-up Actions: <list>
Lessons Learned: <list>
```

## Ownership

- Technical Lead: Ensures adherence to freeze rules
- Release Manager: Tracks exit criteria progress
- Security Officer: Validates CVE patches
- Operations Lead: Monitors production metrics

## Exit Process

Upon meeting all criteria:
1. Prepare release notes summarizing Phase 0 stability metrics
2. Tag `v0.1.0`
3. Lift freeze: archive this file as `RELEASE-FREEZE-PHASE0.md`
4. Begin Phase 1 planning (features backlog grooming)

---
Document version: 1.0.0
Updated: Nov 3 2025
