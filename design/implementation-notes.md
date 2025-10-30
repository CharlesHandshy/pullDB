# Implementation Notes

> **Prerequisites**: Ensure you've read `../.github/copilot-instructions.md` (architectural overview) and `../constitution.md` (coding standards) before implementation.

These notes outline the anticipated Python structure and integrations for the prototype implementation. Follow them alongside `../constitution.md` when writing code.

## Project Skeleton

```
pulldb/
  cli/
    __init__.py
    app.py
    commands.py
  daemon/
    __init__.py
    service.py
    workers.py
  infra/
    mysql.py
    s3.py
    logging.py
  domain/
    models.py
    events.py
  tests/
    ...
```

- Keep modules short and single-purpose. Avoid deep inheritance; prefer composition.
- Define dataclasses in `domain/models.py` for `Job`, `JobEvent`, and configuration objects.

## Database Access

- Use `mysql-connector-python` or `PyMySQL` for MySQL connectivity.
- Wrap SQL statements in repository classes (e.g., `JobRepository`, `EventRepository`). Each class should expose explicit methods like `enqueue_job`, `mark_running`, `append_event`.
- Enforce uniqueness via SQL constraints; handle `IntegrityError` by surfacing user-friendly CLI messages.

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
