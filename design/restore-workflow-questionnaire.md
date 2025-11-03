# Restore Workflow Implementation Questionnaire (TEMP)

> Fill in answers inline below each question. Keep existing numbering. Use `Answer:` prefix. When a proposed default is acceptable, you can just write `Answer: default`. Add any clarifications beneath. Remove this TEMP file after incorporation into code/design docs.

## 1. Staging Lifecycle
1. Staging name convention: Confirm `<target>_<jobid_first12>` (lowercase hex) or specify variation.
   - Answer: Confirmed
2. Orphan cleanup scope: Drop only DBs matching `^<target>_[0-9a-f]{12}$`, or broader? Any age filter?
    - Answer: Unconditional drop-all of every database matching `^<target>_[0-9a-f]{12}$` prior to each new restore job (no age filter, no retention). This enforces FAIL HARD isolation and guarantees a clean slate. Rationale: User re-running a restore to the same target implicitly signals prior staging DBs are no longer needed; retaining any introduces ambiguity and possible stale data usage.
3. Collision behavior after cleanup: Fail HARD or attempt alternative suffix generation?
   - Answer: Fail HARD

## 2. Myloader Orchestration
4. Myloader wrapper path & API: Provide module path and function signature + return fields.
   - Answer: Documentation can be found in reference look for myloader-0.19.3-3.txt & myloader-0.9.5.txt
5. Required myloader flags (threads, user/password, overwrite, etc.) for prototype baseline.
   - Answer: This will be configurable and needs to have a template made for it. examples can be found in reference myloader-0.19.3-3.example & myloader-0.9.5.example
6. Restore timeout (seconds) default & whether configurable via settings table key name.
   - Answer: Adjustable by restore, to to add 30 minutes to last known restore if known, default 2 days

## 3. Repository & DB Access
7. JobRepository methods available (exact names) for: mark running, append event, mark complete, mark failed.
   - Answer: Unknown - need to research
8. How to obtain MySQL connection for staging DB ops (pool API / context manager usage example).
   - Answer: What ever is the most stable and easy to monitor and use for the service.
9. MySQL driver confirmation (mysql-connector-python vs PyMySQL) and any constraints.
   - Answer: Research which is the standard and most stable.

## 4. Post-SQL Execution
10. Source of script directories (hardcoded paths vs settings table keys).
    - Answer: setting table keys - future need to be able to view, upload, edit via web interface
11. Rowcount capture approach (use cursor.rowcount vs custom SELECT logic).
    - Answer: Which is faster?
12. Failure handling: stop on first script error? Keep staging DB intact? (Confirm).
    - Answer: Fail-HARD - first script errors, Keep staging intact for review
13. JSON report schema (list keys; proposed: scripts array with name, status, duration_ms, rowcount, error_message, plus started_at/completed_at/overall_status).
    - Answer: Good for now, evaluate as we go on.
14. Capture script stdout/stderr beyond errors? (If yes, retention format and truncation policy.)
    - Answer: Per job - have clean up purge it default 7 days - settings table

## 5. Metadata Table
15. Exact `pullDB` table schema (columns + types + nullability).
    - Answer: Unknown - need to research
16. Indexes or primary key requirements (PK on job_id? none?).
    - Answer: Yes - what makes logical sense to be created
17. Insert timing: after successful post-SQL but before atomic rename (confirm or adjust).
    - Answer: Insert before update after final status

## 6. Atomic Rename
18. Implement full table rename now or placeholder event (choose). If full: approach (procedure, transactional steps). If placeholder: target status.
    - Answer: Recommend rename procedure per target server, validate exists and most current version before using - provide procedure and deploy as needed.
19. Status semantics if placeholder (use `complete` or introduce `restored_staging`).
    - Answer: complete

## 7. Disk & Working Directory
20. Settings table key for working directory path (name + example value).
    - Answer: working_path - /data/working/<job>
21. Cleanup scope: remove extraction dir only, also delete downloaded tar, or retain both (confirm policy).
    - Answer: Setting table key - working_cleanup - <dir,tar,both,neither> - both

## 8. S3 Backup Selection
22. Data structure returned by backup selection (field names & types: e.g., key, size_bytes, backup_name, timestamp?).
    - Answer: Need to research
23. Default bucket/path in current prototype (staging vs production). Provide actual prefix string used.
    - Answer: staging - need to research format/prefix

## 9. Logging
24. Logger acquisition pattern (function to call or `logging.getLogger` usage) + required structured fields.
    - Answer: Unknown - need to research
25. Mandatory event log fields per phase (list minimal required: job_id, target, phase, status, duration_ms, error?).
    - Answer: start/stop - minimal is fine - add user_id/job owner

## 10. Domain Errors
26. Names of domain error classes for: staging collision, myloader non-zero exit, post-SQL failure, disk insufficient (existing), metadata injection failure.
    - Answer: All classes
27. Should orchestration wrap each step and rethrow as domain-specific error with appended job event? (Confirm.)
    - Answer: Confirmed

## 11. Testing Strategy
28. Integration test environment: use real local MySQL + moto S3 + mocked myloader, or alternative? (Specify.)
    - Answer: use real local MySQL + moto S3 + mocked myloader
29. Priority initial tests (confirm list or adjust): happy path, post-SQL failure, staging collision, myloader timeout, disk insufficient.
    - Answer: Confirmed

## 12. Metrics (Deferred)
30. Emission mechanism preference (logging-based counters, stub collector, or immediate Datadog client?).
    - Answer: logging-based counters that I will later setup for Datadog to ingest

## 13. Baseline Policy Documentation
31. Location for baseline policy doc (new `docs/engineering-dna-baseline.md` vs augment README section).
    - Answer: Confirmed

## 14. Baseline Bump Automation
32. Baseline bump script format (bash vs python) + desired behaviors (validate tag exists, update file, commit template, optional push).
    - Answer: python

---
### Optional Global Defaults
If you intend to accept all proposed defaults where not otherwise specified, you can add:
```
Answer: default for all unspecified
```
at the bottom, then only override divergent items above.

### Notes / Additional Constraints
Add any cross-cutting requirements (transaction boundaries, isolation levels, concurrency plans) here:
   - Notes: job isolation

### Clarifications / Resolved Divergences
- Staging orphan cleanup policy finalized as unconditional drop-all (previous draft suggested retaining latest unless older than 2 days). Implementation (`pulldb/worker/staging.py::cleanup_orphaned_staging`) already performs drop-all; questionnaire updated to match.
- Metadata insertion timing: Initial answer suggested "Insert before update after final status". Current workflow inserts metadata after post-SQL and before atomic rename to ensure staging DB carries audit info if rename fails. Future adjustment may relocate insertion post-rename if target-level metadata preferred.
- Atomic rename strategy: Proceeding with stored procedure `pulldb_atomic_rename` per host; procedure existence validated before invocation.

