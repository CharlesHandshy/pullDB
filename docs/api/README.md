# pullDB API Documentation

[← Back to Documentation Index](../START-HERE.md)

> **Version**: 1.1.0  
> **Last Updated**: 2026-01-21

---

## Overview

pullDB provides two API surfaces:

| API | Port | Purpose | Authentication |
|-----|------|---------|----------------|
| **REST API** | 8080 | CLI, programmatic access | HMAC signature |
| **Web UI API** | 8000 | Browser interface | Session cookie |

Both APIs share the same underlying application state and database.

---

## Quick Reference

### REST API Highlights

```bash
# Health check
GET /api/health

# Submit restore job
POST /api/jobs
{"user": "jdoe", "customer": "acme", "dbhost": "dev"}

# Get job status
GET /api/jobs/{job_id}

# Stream job events
GET /api/jobs/{job_id}/events?since_id=0

# Cancel job
POST /api/jobs/{job_id}/cancel

# Search jobs
GET /api/jobs/search?q=acme
```

### Web UI Pages

| Path | Description |
|------|-------------|
| `/web/login` | Login page |
| `/web/dashboard/` | Role-specific dashboard |
| `/web/jobs/` | My jobs list |
| `/web/restore/` | Submit new restore |
| `/web/admin/` | Admin panel (admin only) |

---

## Documentation Index

| Document | Description |
|----------|-------------|
| **[REST-API.md](REST-API.md)** | Complete REST API reference (53 endpoints) |
| **[WEB-API.md](WEB-API.md)** | Web UI routes and API reference (141 routes) |
| **[API-DOCUMENTATION-STANDARD.md](API-DOCUMENTATION-STANDARD.md)** | Template and guidelines for API documentation |

---

## Authentication

### HMAC Signature (REST API / CLI)

```bash
# Headers required:
X-API-Key: <your-api-key>
X-Timestamp: <ISO-8601-UTC>
X-Signature: <HMAC-SHA256>

# Signature payload: {method}:{path}:{timestamp}
```

**Example:**
```bash
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
PAYLOAD="GET:/api/status:$TIMESTAMP"
SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$API_SECRET" | awk '{print $2}')

curl -H "X-API-Key: $API_KEY" \
     -H "X-Timestamp: $TIMESTAMP" \
     -H "X-Signature: $SIGNATURE" \
     http://localhost:8080/api/status
```

### Session Cookie (Web UI)

Login via `/web/login` sets `session_token` httponly cookie.

---

## Common Patterns

### Pagination (LazyTable)

Many endpoints support server-side pagination:

```
GET /api/jobs/paginated?page=0&pageSize=50&sortColumn=submitted_at&sortDirection=desc
```

Response:
```json
{
  "rows": [...],
  "totalCount": 150,
  "filteredCount": 45,
  "page": 0,
  "pageSize": 50
}
```

### Filtering

Multi-value filters use comma separation with OR logic:

```
GET /api/jobs/paginated?filter_status=queued,running&filter_dbhost=dev
```

Wildcard filters for text columns:

```
GET /api/jobs/paginated?filter_id=8b4c*&filter_submitted_at=01/*/2026
```

### Cascading Filters

Distinct value endpoints support filter order for dependent dropdowns:

```
GET /api/jobs/paginated/distinct?column=user_code&filter_order=status,dbhost
```

---

## Entry Points

| Command/Service | Module | Port |
|-----------------|--------|------|
| `pulldb-api` | `pulldb.api.main:main` | 8080 |
| `pulldb-web` | `pulldb.api.main:main_web` | 8000 |

Both services use the same FastAPI application with different entry points.

---

## Related Documentation

- [CLI Reference](../hca/pages/cli-reference.md) - Command-line interface
- [Architecture](../hca/widgets/architecture.md) - System design
- [KNOWLEDGE-POOL.md](../KNOWLEDGE-POOL.md) - AWS/infra reference

---

*Source code: [pulldb/api/](../../pulldb/api/) | [pulldb/web/](../../pulldb/web/)*
