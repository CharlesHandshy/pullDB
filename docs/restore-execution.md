# Restore Execution Primitives

This short stub documents the two foundational execution layers now implemented for the restore workflow. It will be expanded once staging lifecycle, post‑SQL execution, and atomic rename orchestration land.

## Layers

1. `pulldb.infra.exec` (`run_command`)
   - Thin, generic subprocess wrapper (timeout, stdout/stderr capture + truncation, duration metrics).
   - Raises:
     - `CommandExecutionError` (process could not start: ENOENT, permission, etc.)
     - `CommandTimeoutError` (deadline exceeded, includes partial output)
   - Returns `CommandResult` (command list, exit_code, timestamps, duration, captured IO).
   - No logging side‑effects; caller injects context (job_id, phase) at a higher layer.

2. `pulldb.worker.restore` (`run_myloader`)
   - Builds `myloader` command from `MyLoaderSpec`.
   - Invokes `run_command` and translates failure modes into `MyLoaderError` (FAIL HARD diagnostics).
   - Truncates stdout/stderr to 5KB tails for inclusion in error detail and result model.
   - Isolation: Only handles command construction + failure mapping. Orchestration (staging DB provisioning, post‑SQL scripts, atomic rename) deliberately deferred to future modules (`staging.py`, `post_sql.py`).

3. `pulldb.worker.post_sql` (`execute_post_sql`)
   - Discovers `*.sql` scripts in designated directory (lexicographic order).
   - Executes scripts sequentially against staging database via `mysql.connector`.
   - Captures per-script timing, optional `rowcount`, and halts on first failure.
   - Raises `PostSQLError` with list of completed scripts for diagnostics.
   - Returns `PostSQLExecutionResult` with timing + row metrics (empty list if no scripts).

## Testing Strategy

- Unit tests monkeypatch `run_command` for the myloader wrapper to keep tests deterministic and OS/binary agnostic.
- Direct `run_command` tests cover:
  - Success
  - Non‑zero exit (returned not raised)
  - Timeout (exception)
  - Spawn failure (simulated via patched `Popen`)
  - Large output truncation behavior
- Wrapper tests cover:
  - Success path (translated into `MyLoaderResult`)
  - Non‑zero exit → `MyLoaderError`
  - Timeout → `MyLoaderError` with partial IO
- Post-SQL tests cover:
  - No scripts → empty result
  - Success (ordered execution, rowcount capture)
  - Failure (first error halts execution, completed list preserved)

## Next Expansion (Planned)

| Component | Purpose | Status |
|-----------|---------|--------|
| `staging.py` | Staging DB name generation, orphan cleanup, safety checks | Planned |
| `post_sql.py` | Post‑restore script discovery & sequential execution with JSON report | **Implemented** |
| Atomic rename | Table-level or schema-level atomic cutover procedure | Planned |
| Metadata table | Insert restore metadata + post‑SQL results | Planned |

## Rationale

Keeping the execution primitives small and test-focused reduces coupling and enables fast iteration on the more complex orchestration flows without destabilizing low-level process handling.

## To Do (Doc Expansion)
- Add sequence diagrams linking `service.py` poll loop → `restore.py` → future `staging.py`/`post_sql.py`.
- Document environment variable escape/quoting guidance for future myloader advanced options.
- Expand error taxonomy once post‑SQL and atomic rename errors are implemented.
