# Phase 0 Test Plan Execution (Nov 14 2025)

## Task List

### Environment & Preconditions
- [x] Refresh test environment (`test-env`) and verify credentials/ownership
- [x] Ensure API service (`pulldb-api`) running with current secrets
- [x] Ensure worker service (or equivalent manual runner) available for tests

### Automated Tests
- [ ] Run queue manager repository suite (`pulldb/tests/test_repositories.py`)
- [ ] Run CLI parsing/formatter tests (`pulldb/tests/test_cli_*.py`)
- [ ] Run worker helper/orchestration tests (`pulldb/tests/test_worker_*.py`)
- [ ] Run targeted API integration tests (`pulldb/tests/test_api_*.py`)
- [x] Run full `pytest` suite with timeouts
- [x] Run dev smoke test (`tests/dev/test_smoke.py`) via CI-equivalent invocation

### Manual / Exploratory Exercises
- [x] CLI restore command happy path (manual invocation)
- [x] CLI error handling scenarios (invalid args, conflicts)
- [x] Queue inspection via MySQL (status transitions + events)
- [x] Worker daemon lifecycle (start/stop, graceful shutdown)
- [ ] End-to-end restore with real backup (staging bucket)
- [x] Metrics/log validation (JSON logs, Datadog stub)
- [ ] Failure drills (interrupt restore, revoke S3, rotate secret)

### Exit Tracking & Reporting
- [ ] Capture restore success metrics vs exit criteria
- [ ] Document unresolved issues & remediation items
- [ ] Summarize findings for Phase 0 readiness review

## Execution Log

> Entries will be appended here as tasks are executed. Each entry should capture:
> 1. Task reference
> 2. Command(s) or actions performed
> 3. Outcome (pass/fail/blocked)
> 4. Follow-up items

- **Task**: Refresh test environment (`test-env`) and verify credentials/ownership  
	**Actions**: `ls -ld test-env*`; `sudo chown -R charleshandshy:charleshandshy test-env/config test-env/work`  
	**Outcome**: Pass — ownership normalized to `charleshandshy` for config/logs/work; `.env` accessible.  
	**Follow-up**: None
- **Task**: Ensure API service (`pulldb-api`) running with current secrets  
	**Actions**: `ps -eo pid,cmd | grep pulldb-api`; review `/proc/<pid>/environ`; `curl` `/api/health` and `/api/jobs/active`  
	**Outcome**: Pass — API process PID 1743265 uses refreshed secret (`pulldb_test_9f3ff6e42fc262c3`); health + active endpoints return 200.  
	**Follow-up**: Add automation to restart API after secret rotation (future task)
- **Task**: Ensure worker service available  
	**Actions**: `timeout 5 pulldb-worker` under `test-env`; observed structured logs/metrics; ensured graceful shutdown on SIGTERM  
	**Outcome**: Pass — worker start/stop functional; metrics emitted (`worker_active`, `queue_empty`) before timed shutdown.  
	**Follow-up**: Consider background runner wrapper for longer manual testing
- **Task**: Run queue manager repository tests  
	**Actions**: `pytest pulldb/tests/test_job_repository.py ... test_settings_repository.py`; repeated with local credential overrides; re-ran with `-rs` for skip reasons  
	**Outcome**: Blocked — all repository tests skipped by `verify_secret_residency` fixture because AWS Secrets Manager credentials unavailable; local overrides trigger suite-wide skip.  
	**Follow-up**: Acquire AWS access for `/pulldb/mysql/coordination-db` (dev account) or introduce non-skip path for vetted local overrides
- **Task**: Run CLI parsing/status tests  
	**Actions**: `pytest pulldb/tests/test_cli_parse.py pulldb/tests/test_cli_status.py`; reran with `-rs` to capture skip diagnostics  
	**Outcome**: Blocked — fixtures require Secrets Manager `DescribeSecret` permission; current AWS session assumes staging read-only role lacking access; tests skipped with AccessDenied.  
	**Follow-up**: Obtain dev account IAM role or adapt tests to allow approved local credential overrides without skipping assertions
- **Task**: Run worker helper/orchestration tests  
	**Actions**: `pytest pulldb/tests/test_restore.py ... test_downloader.py`; reran with `-rs` on representative modules  
	**Outcome**: Blocked — same Secrets Manager residency check fails with AccessDenied (staging cross-account role).  
	**Follow-up**: Same as above; worker suite requires successful secret resolution to MySQL dev credentials
- **Task**: Run API integration tests  
	**Actions**: `pytest pulldb/tests/test_api_jobs.py -rs`  
	**Outcome**: Blocked — AccessDenied on `DescribeSecret` for `/pulldb/mysql/coordination-db`; tests skip before exercising API routes.  
	**Follow-up**: Required AWS dev account credentials or local override strategy that allows tests to proceed
- **Task**: Run full pytest suite  
	**Actions**: `pytest -q --timeout=60 --timeout-method=thread`  
	**Outcome**: Partial — run completed with `11 passed, 180 skipped`; majority skipped tests depend on Secrets Manager access.  
	**Follow-up**: Same AWS credential remediation to reduce skip count and gain real coverage
- **Task**: Run dev smoke test  
	**Actions**: `pytest tests/dev/test_smoke.py -q --timeout=60 --timeout-method=thread`  
	**Outcome**: Pass — smoke test succeeded in 0.76s targeting in-process API/CLI flow.  
	**Follow-up**: Integrate into CI as guardrail
- **Task**: CLI restore happy path  
	**Actions**: `pulldb restore user=John.Doe customer=AcmeTest`; inspected job via `pulldb status`; cleaned rows with MySQL `DELETE`  
	**Outcome**: Pass — CLI enqueued job successfully, status listing showed queued job, cleanup restored empty queue.  
	**Follow-up**: None
- **Task**: CLI error handling scenarios  
	**Actions**: `pulldb restore customer=Bad`; `pulldb restore user=Jane.Doe customer=Acme qatemplate`; duplicate submission for `AcmeConflict`; manual DELETE cleanup  
	**Outcome**: Pass — CLI surfaces `UsageError` for malformed args and `ClickException` with 409 conflict message for duplicate target; queue cleaned after tests.  
	**Follow-up**: Consider automated regression capturing conflict path
- **Task**: Queue inspection via MySQL  
	**Actions**: `mysql -e "USE pulldb_test_coordination; SELECT status, COUNT(*) FROM jobs GROUP BY status; SELECT COUNT(*) FROM job_events;"`  
	**Outcome**: Pass — no rows in `jobs`; `job_events` count 0 after cleanup, confirming manual tests left database clean.  
	**Follow-up**: None
- **Task**: Worker daemon lifecycle  
	**Actions**: `timeout 5 pulldb-worker` (captures startup + SIGTERM flow)  
	**Outcome**: Pass — worker logged startup, queue polling, and graceful shutdown with metrics before timeout terminated process.  
	**Follow-up**: For extended manual runs, create script to tail logs and enforce cleanup
- **Task**: Metrics/log validation  
	**Actions**: `tail -n 5 test-env/logs/pulldb-api.log`; observed worker stdout metrics from lifecycle test  
	**Outcome**: Pass — structured JSON logs contain counter/event entries with job_id/target fields; confirm metrics instrumentation active.  
	**Follow-up**: Hook into Datadog sink to confirm external ingestion (future)
