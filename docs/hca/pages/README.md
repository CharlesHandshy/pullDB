# Pages Layer Documentation

> User-facing entry points (CLI, Web, Admin).
> Code locations: `pulldb/cli/`, `pulldb/web/`, `pulldb/api/`

## Documents

| Document | Purpose | Status |
|----------|---------|--------|
| [cli-reference.md](cli-reference.md) | CLI command reference | ✅ Active |
| [admin-guide.md](admin-guide.md) | Administration guide | ✅ Active |
| [getting-started.md](getting-started.md) | User quickstart | ✅ Active |
| [web-ui.md](web-ui.md) | Web interface guide | 📝 Planned |

## Entry Points

### CLI (`pulldb/cli/`)

```bash
# User commands
pulldb restore <backup> <target>
pulldb status <job-id>
pulldb list-backups

# Admin commands  
pulldb-admin queue-status
pulldb-admin cancel-job <job-id>
```

### API (`pulldb/api/`)

```
POST /api/v1/jobs          # Submit restore job
GET  /api/v1/jobs/{id}     # Get job status
GET  /api/v1/backups       # List available backups
```

### Web (`pulldb/web/`)

- Dashboard with job queue
- Backup browser
- Job progress monitoring

## Page Responsibilities

Pages handle ONLY:
- Request parsing
- Authentication/authorization
- Response formatting
- Invoking widgets/services

Pages do NOT contain business logic:
```python
# ✅ GOOD - page delegates to widget
@app.route('/api/v1/jobs', methods=['POST'])
def create_job():
    job = worker_service.submit_job(request.json)
    return jsonify(job.to_dict())

# ❌ BAD - business logic in page
@app.route('/api/v1/jobs', methods=['POST'])
def create_job():
    # Don't do database operations here!
    db.execute("INSERT INTO jobs...")
```

## Related

- [../widgets/](../widgets/) - Services invoked by pages
- [../plugins/](../plugins/) - External tools used by system
