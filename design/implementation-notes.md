# Implementation Notes

> **Prerequisites**: Ensure you've read `../.github/copilot-instructions.md` (architectural overview), `../constitution.md` (coding standards), and `two-service-architecture.md` (service separation) before implementation.

These notes outline the anticipated Python structure and integrations for the prototype implementation. Follow them alongside `../constitution.md` when writing code.

## FAIL HARD Coding Contract

All service and repository code MUST follow the standardized failure pattern:

- Raise specific exception subclasses (define domain errors: CredentialResolutionError, DiskCapacityError, BackupDownloadError).
- Chain exceptions (`raise ... from e`) to preserve full traceback.
- Emit Goal / Problem / Root Cause / Ranked Solutions in user-visible error_detail or structured log when a job fails.
- Tests asserting failure paths MUST inspect message content for remediation guidance.
- Avoid broad, silent catch blocks; translating third-party exceptions requires context preservation.
- Prohibit `except: pass` and returning partially-valid objects on failure.

## Project Skeleton

```
pulldb/
  cli/
    main.py                # Placeholder – to be replaced by validated command set
    (validate.py)          # PLANNED – argument parsing & normalization
    (api_client.py)        # PLANNED – HTTP calls to future API service (deferred until API stands up)
  worker/
    service.py             # Implemented heartbeat + poll loop
    (workflow.py)          # PLANNED – end-to-end restore orchestration (will call downloader, restore, post_sql, staging)
    downloader.py          # IMPLEMENTED – S3 download + disk space checks + streaming
    (staging.py)           # PLANNED – orphan cleanup + name generation + atomic rename placeholder
    (restore.py)           # PLANNED – myloader subprocess wrapper
    (post_sql.py)          # PLANNED – ordered execution of post-restore scripts
  infra/
    secrets.py             # IMPLEMENTED – credential resolution (Secrets Manager + SSM)
    mysql.py               # IMPLEMENTED – repositories & thin pool
    s3.py                  # IMPLEMENTED – backup discovery/listing helpers + typed client
    (logging.py)           # PLANNED – structured JSON logger abstraction
    (exec.py)              # PLANNED – subprocess runner capturing stdout/stderr
  domain/
    models.py              # IMPLEMENTED – core dataclasses
    (errors.py)            # PLANNED – structured FAIL HARD runtime errors
    (restore_models.py)    # PLANNED – BackupSpec (migrated from infra?), PostSQLResult, Metadata payloads
  tests/
    test_*                 # 87 passing modules; will expand with workflow & failure path coverage
```

Parenthesized entries are planned but not yet implemented as of Nov 1 2025. Non-parenthesized entries exist today. Update this skeleton as modules land; convert planned entries to implemented lines without parentheses and adjust commentary.

### Drift Acknowledgment (Nov 1 2025)

Documentation originally referenced an `api/` service layer; current implementation has not yet introduced HTTP endpoints. The initial milestone focuses on a direct CLI → MySQL enqueue path and a worker service performing restores. The HTTP API service remains deferred until after baseline restore workflow stabilizes. Once ready, reintroduce `api/` directory with FastAPI (preferred) and migrate CLI interactions from direct repository usage to HTTP calls.

- Keep modules short and single-purpose. Avoid deep inheritance; prefer composition.
- Define dataclasses in `domain/models.py` for `Job`, `JobEvent`, and configuration objects.
- CLI uses `api_client.py` to communicate with API service via HTTP REST.
- API service has `server.py` (Flask/FastAPI), `handlers.py` (endpoints), `validation.py` (input validation).
- Worker service has `service.py` (poll loop), `restore.py` (restore workflow), `s3.py` (S3 operations).

## Service Separation

**CRITICAL**: Read `two-service-architecture.md` for complete details on the API/Worker split.

- **API Service**: Accepts HTTP requests, validates input, inserts jobs to MySQL, returns status (no S3/myloader access)
- **Worker Service**: Polls MySQL queue, downloads from S3, executes myloader, updates job status (no HTTP exposure)
- **Communication**: Services never communicate directly - only via MySQL coordination database

## REST API Design

- Use Flask or FastAPI for API service HTTP endpoints.
- Key endpoints:
  - `POST /api/jobs` - Create new restore job (accepts user, customer/qatemplate, dbhost, overwrite)
  - `GET /api/jobs` - List jobs (with filtering by user, status, target)
  - `GET /api/jobs/{job_id}` - Get job details and events
  - `GET /api/health` - Health check endpoint
- Return structured JSON responses with proper HTTP status codes.
- Validate all inputs in API layer before database insertion.
- Include request ID in logs for tracing.

## Database Access

- Use `mysql-connector-python` or `PyMySQL` for MySQL connectivity (API and worker services only).
- CLI does NOT access MySQL - it calls API service via HTTP.
- Wrap SQL statements in repository classes (e.g., `JobRepository`, `EventRepository`). Each class should expose explicit methods like `enqueue_job`, `mark_running`, `append_event`.
- Enforce uniqueness via SQL constraints; handle `IntegrityError` by surfacing user-friendly API responses.

## S3 Interaction

- Use `boto3.client('s3')` with paginated listing to find the latest backup.
- Download via `download_file` or streaming `get_object` with chunked writes to disk.
- Mock S3 in tests using moto or a local fake to avoid network access during CI.

## MySQL Restore

- Shell out to `myloader` via `subprocess.run`, capturing stdout/stderr.
- Require explicit command arguments (host, user, password, target database, input directory).
- On failure, attach the relevant output to `error_detail` and add a `failed` event.

## Configuration

- Load environment variables using `os.environ` or a thin wrapper (`infra.settings`).
- Keep secrets outside the repo; support AWS Secrets Manager or SSM retrieval when available.

## Logging & Metrics

- Use Python's `logging` with JSON-structured handlers. Include job ID, target, phase, and duration fields.
- Emit metrics through Datadog API or StatsD-compatible client as defined in the operations playbook.

## Testing Strategy

- Unit tests: use `pytest` with fixtures for test MySQL databases or mocked connections.
- Integration tests: spin up disposable MySQL containers (e.g., Testcontainers) to validate restore flow.
- Mock S3 and subprocess calls where full integration is not required.
- Smoke test script: orchestrate CLI + daemon against a staging configuration before release.

Keep this file updated as implementation details evolve. Changes require documentation review before code merges.

## Next Milestone (Restore Workflow Continuation)

With S3 discovery, downloader, and poll loop implemented, the next feature slice focuses on executing and finalizing restores end-to-end. Deliver components in the order below, preserving green tests after each increment:

1. Domain Error Classes (errors.py)
  - Define: MyLoaderExecutionError, PostSQLScriptError, StagingLifecycleError, AtomicRenameError.
  - Include remediation guidance text blocks; tests assert presence of actionable phrases (e.g., 'grant FILE privilege').

2. Subprocess Wrapper (exec.py + restore.py)
  - Implement `run_myloader(spec: RestoreSpec) -> MyLoaderResult` capturing stdout/stderr, exit code, duration.
  - Fail HARD if exit code != 0; surface first 40 lines of stderr plus truncation notice.
  - Unit tests: success (mocked returncode 0), failure (non‑zero), timeout scenario.

3. Staging Lifecycle (staging.py)
  - Functions: `generate_staging_name(target, job_id)`, `cleanup_orphans(target, conn)`, `verify_absent(name, conn)`.
  - Regex pattern: `{target}_[0-9a-f]{12}`. Drop matches before starting restore.
  - Tests: orphan present removed; existing staging name after cleanup raises.

4. Atomic Rename Placeholder
  - Implement naive rename: create target if not exists, copy tables via `RENAME TABLE staging.tbl TO target.tbl` loop.
  - Defer stored procedure optimization until performance measurement.
  - Test: tables moved, staging dropped only on success.

5. Post‑SQL Executor (post_sql.py)
  - Enumerate directory; lexicographic order; stop on first failure, record partial results JSON.
  - Result model: list of `{script_name, started_at, completed_at, success, error}`.
  - Tests: all succeed, first fails (abort), invalid SQL syntax captured.

6. Metadata Injection
  - Create `pullDB` metadata table in staging before rename; include columns: user, backup_name, restore_started_at, restore_completed_at, post_sql_report_json.
  - Test: table exists with expected JSON keys.

7. Workflow Orchestration (workflow.py)
  - Compose: discover_latest_backup -> ensure_disk_capacity -> download_backup -> generate staging -> myloader restore -> post_sql -> metadata -> rename.
  - Emit job events at each boundary; update status transitions.
  - Integration test (partial): use moto S3 + sqlite or lightweight MySQL fixture for flow sans heavy data.

8. End‑to‑End Integration Tests
  - Add scenarios: missing backup (discover raises), disk insufficient (capacity error), myloader non‑zero exit, post‑SQL script failure, rename collision.
  - Ensure each sets `jobs.error_detail` with structured FAIL HARD block.

9. Metrics Hooks (deferred until baseline stable)
  - Placeholder timers around major phases; counters for failures by type.

Acceptance Criteria: After completion, a single queued job proceeds to `complete` with populated metadata table, post‑SQL summary JSON, and event log coverage for each phase. All failure paths produce deterministic domain errors with remediation guidance.
