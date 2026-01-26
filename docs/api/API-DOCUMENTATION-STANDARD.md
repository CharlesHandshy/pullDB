# API Documentation Standard

[← Back to API Index](README.md)

> **Version**: 1.0.0  
> **Last Updated**: 2026-01-21  
> **Purpose**: Standard template and guidelines for documenting pullDB API endpoints

---

## Table of Contents

1. [Overview](#overview)
2. [Endpoint Documentation Template](#endpoint-documentation-template)
3. [Field Descriptions](#field-descriptions)
4. [Multi-Language Examples](#multi-language-examples)
5. [Response Model Guidelines](#response-model-guidelines)
6. [Error Documentation](#error-documentation)
7. [Complete Example](#complete-example)

---

## Overview

All pullDB API endpoints must be documented following this standard to ensure:
- Consistency across documentation
- Complete information for integrators
- Multi-language code examples for common use cases
- Clear error handling guidance

---

## Endpoint Documentation Template

```markdown
### `{METHOD} {PATH}`

{Brief one-line description.}

**Authentication:** Required | None  
**Authorization:** {Role required, if any}

**Purpose:** {Detailed explanation of what the endpoint does, when to use it, and any important behavior notes.}

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `param` | type | Description |

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `param` | type | default | Description |

**Request Body:** `{ModelName}`
```json
{
  "field": "value"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `field` | type | yes/no | default | Description |

**Response Model:** `{ModelName}`
```json
{
  "field": "value"
}
```

**Errors:**
| Code | Description |
|------|-------------|
| 400 | When/why this error occurs |
| 404 | When/why this error occurs |

---
```

---

## Field Descriptions

### Required Sections

| Section | When to Include |
|---------|-----------------|
| Method & Path | Always |
| Brief description | Always |
| Authentication | Always |
| Authorization | When role-restricted |
| Purpose | For complex or non-obvious endpoints |
| Path Parameters | When path has `{param}` |
| Query Parameters | When accepts query params |
| Request Body | When accepts JSON body |
| Response Model | Always (except 204) |
| Errors | For endpoints with specific error cases |

### Authentication Values

| Value | Meaning |
|-------|---------|
| `Required` | HMAC signature or session cookie |
| `None` | Public endpoint |

### Authorization Values

| Value | Meaning |
|-------|---------|
| `Admin role` | Requires `role=admin` |
| `Manager role` | Requires `role=manager` or above |
| `Request author or admin` | Ownership or admin |
| *(omit)* | Any authenticated user |

---

## Multi-Language Examples

For commonly-used endpoints, include examples in Python, PHP, and Bash.

### Python Example Template

```python
"""
{Endpoint purpose in one line}

Usage:
    python example_endpoint.py
    
Requirements:
    pip install requests
"""

import hashlib
import hmac
import os
from datetime import datetime, timezone

import requests

# Configuration
API_BASE = os.getenv("PULLDB_API_URL", "http://localhost:8080")
API_KEY = os.environ["PULLDB_API_KEY"]
API_SECRET = os.environ["PULLDB_API_SECRET"]


def generate_signature(method: str, path: str, timestamp: str) -> str:
    """Generate HMAC-SHA256 signature for API authentication."""
    payload = f"{method}:{path}:{timestamp}"
    return hmac.new(
        API_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()


def api_request(method: str, path: str, json_data: dict | None = None) -> dict:
    """Make authenticated API request."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signature = generate_signature(method, path, timestamp)
    
    headers = {
        "X-API-Key": API_KEY,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }
    
    url = f"{API_BASE}{path}"
    response = requests.request(method, url, headers=headers, json=json_data)
    response.raise_for_status()
    return response.json()


def main():
    # Example: {describe the operation}
    result = api_request("{METHOD}", "{PATH}", {
        # Request body fields
    })
    
    print(f"Result: {result}")


if __name__ == "__main__":
    main()
```

### PHP Example Template

```php
<?php
/**
 * {Endpoint purpose in one line}
 * 
 * Usage:
 *     php example_endpoint.php
 *     
 * Requirements:
 *     PHP 8.0+ with curl extension
 */

// Configuration
$apiBase = getenv('PULLDB_API_URL') ?: 'http://localhost:8080';
$apiKey = getenv('PULLDB_API_KEY');
$apiSecret = getenv('PULLDB_API_SECRET');

if (!$apiKey || !$apiSecret) {
    die("Error: PULLDB_API_KEY and PULLDB_API_SECRET must be set\n");
}

/**
 * Generate HMAC-SHA256 signature for API authentication.
 */
function generateSignature(string $method, string $path, string $timestamp, string $secret): string {
    $payload = "{$method}:{$path}:{$timestamp}";
    return hash_hmac('sha256', $payload, $secret);
}

/**
 * Make authenticated API request.
 */
function apiRequest(string $method, string $path, ?array $jsonData = null): array {
    global $apiBase, $apiKey, $apiSecret;
    
    $timestamp = gmdate('Y-m-d\TH:i:s\Z');
    $signature = generateSignature($method, $path, $timestamp, $apiSecret);
    
    $headers = [
        "X-API-Key: {$apiKey}",
        "X-Timestamp: {$timestamp}",
        "X-Signature: {$signature}",
        "Content-Type: application/json",
    ];
    
    $url = $apiBase . $path;
    
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
    curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    
    if ($jsonData !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($jsonData));
    }
    
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    if ($httpCode >= 400) {
        throw new Exception("API error (HTTP {$httpCode}): {$response}");
    }
    
    return json_decode($response, true);
}

// Main execution
try {
    // Example: {describe the operation}
    $result = apiRequest('{METHOD}', '{PATH}', [
        // Request body fields
    ]);
    
    echo "Result: " . json_encode($result, JSON_PRETTY_PRINT) . "\n";
    
} catch (Exception $e) {
    die("Error: " . $e->getMessage() . "\n");
}
```

### Bash Example Template

```bash
#!/bin/bash
# {Endpoint purpose in one line}
#
# Usage:
#     ./example_endpoint.sh
#
# Requirements:
#     - curl, openssl, jq
#     - Environment variables: PULLDB_API_KEY, PULLDB_API_SECRET

set -euo pipefail

# Configuration
API_BASE="${PULLDB_API_URL:-http://localhost:8080}"
API_KEY="${PULLDB_API_KEY:?Error: PULLDB_API_KEY not set}"
API_SECRET="${PULLDB_API_SECRET:?Error: PULLDB_API_SECRET not set}"

# Generate HMAC-SHA256 signature
generate_signature() {
    local method="$1"
    local path="$2"
    local timestamp="$3"
    echo -n "${method}:${path}:${timestamp}" | \
        openssl dgst -sha256 -hmac "$API_SECRET" | \
        awk '{print $2}'
}

# Make authenticated API request
api_request() {
    local method="$1"
    local path="$2"
    local data="${3:-}"
    
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    local signature
    signature=$(generate_signature "$method" "$path" "$timestamp")
    
    local curl_args=(
        -s
        -X "$method"
        -H "X-API-Key: $API_KEY"
        -H "X-Timestamp: $timestamp"
        -H "X-Signature: $signature"
        -H "Content-Type: application/json"
    )
    
    if [[ -n "$data" ]]; then
        curl_args+=(-d "$data")
    fi
    
    curl "${curl_args[@]}" "${API_BASE}${path}"
}

# Main execution
main() {
    # Example: {describe the operation}
    local result
    result=$(api_request "{METHOD}" "{PATH}" '{"field": "value"}')
    
    echo "Result:"
    echo "$result" | jq .
}

main "$@"
```

---

## Response Model Guidelines

### JSON Format Standards

- Use `snake_case` for field names
- Dates: ISO 8601 format (`2026-01-21T10:30:00Z`)
- Nullable fields: Include `| None` in type
- Lists: Use `list[ItemType]` notation
- Pagination: Follow LazyTable convention

### Pagination Response Standard

```json
{
  "rows": [...],
  "totalCount": 150,
  "filteredCount": 45,
  "page": 0,
  "pageSize": 50
}
```

### Boolean Response Standard

For simple success/failure:
```json
{
  "success": true,
  "message": "Operation completed successfully"
}
```

### List Response Standard

```json
{
  "items": [...],
  "total": 25
}
```

---

## Error Documentation

### Standard Error Format

All errors return:
```json
{
  "detail": "Human-readable error message"
}
```

### Common Error Codes

| Code | Name | When Used |
|------|------|-----------|
| 400 | Bad Request | Invalid parameters, validation failure |
| 401 | Unauthorized | Missing or invalid authentication |
| 403 | Forbidden | Authenticated but insufficient permissions |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | State conflict (e.g., job already canceled) |
| 422 | Unprocessable Entity | Semantic validation failure |
| 500 | Internal Server Error | Unexpected server error |
| 503 | Service Unavailable | Backend dependency unavailable |

### Documenting Specific Errors

For endpoints with specific error cases:

```markdown
**Errors:**
| Code | Description |
|------|-------------|
| 400 | `days` must be between 1 and 365 |
| 404 | User not found |
| 409 | Job is already in terminal state |
```

---

## Complete Example

Here's a fully documented endpoint following all standards:

---

### `POST /api/jobs`

Submit a new database restore job.

**Authentication:** Required  

**Purpose:** Creates a new restore job that will download a backup from S3 and restore it to a staging database. The job enters the queue and is processed by the worker service. Returns immediately with job ID for status tracking.

**Request Body:** `JobSubmitRequest`
```json
{
  "user": "jdoe",
  "customer": "acme",
  "dbhost": "dev",
  "target": "acme_jdoe",
  "backup_date": "2026-01-20"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `user` | string | yes | - | Username (must match authenticated user) |
| `customer` | string | yes | - | Customer ID for backup selection |
| `dbhost` | string | yes | - | Target database host alias |
| `target` | string | no | `{customer}_{user}` | Custom target database name |
| `backup_date` | string | no | latest | Specific backup date (YYYY-MM-DD) |

**Response Model:** `JobSubmitResponse`
```json
{
  "id": "8b4c4a3a-85a1-4da2-9f3c-abc123def456",
  "status": "queued",
  "staging_name": "staging_acme_8b4c4a3a",
  "target": "acme_jdoe",
  "message": "Job submitted successfully"
}
```

**Errors:**
| Code | Description |
|------|-------------|
| 400 | Invalid customer or host |
| 403 | User not authorized for this customer |
| 409 | Active job already exists for this target |

#### Python Example

```python
"""Submit a new restore job."""

import os
from pulldb_client import PullDBClient

client = PullDBClient(
    api_url=os.getenv("PULLDB_API_URL", "http://localhost:8080"),
    api_key=os.environ["PULLDB_API_KEY"],
    api_secret=os.environ["PULLDB_API_SECRET"],
)

# Submit restore job
result = client.submit_job(
    customer="acme",
    dbhost="dev",
    target="acme_jdoe",
)

print(f"Job ID: {result['id']}")
print(f"Status: {result['status']}")
print(f"Staging DB: {result['staging_name']}")
```

#### PHP Example

```php
<?php
// Submit a new restore job

$result = apiRequest('POST', '/api/jobs', [
    'user' => 'jdoe',
    'customer' => 'acme',
    'dbhost' => 'dev',
]);

echo "Job ID: {$result['id']}\n";
echo "Status: {$result['status']}\n";
echo "Staging DB: {$result['staging_name']}\n";
```

#### Bash Example

```bash
#!/bin/bash
# Submit a new restore job

result=$(api_request "POST" "/api/jobs" '{
  "user": "jdoe",
  "customer": "acme",
  "dbhost": "dev"
}')

echo "Job ID: $(echo "$result" | jq -r .id)"
echo "Status: $(echo "$result" | jq -r .status)"
echo "Staging DB: $(echo "$result" | jq -r .staging_name)"
```

---

## Checklist

When documenting a new endpoint, verify:

- [ ] Method and path are correct
- [ ] Brief description is clear and concise
- [ ] Authentication requirement is stated
- [ ] Authorization is specified if role-restricted
- [ ] Purpose explains the "why" for complex endpoints
- [ ] All path parameters are documented
- [ ] All query parameters with types and defaults
- [ ] Request body model with all fields
- [ ] Response model with example JSON
- [ ] Specific error cases are documented
- [ ] Multi-language examples for high-use endpoints

---

*This standard ensures pullDB API documentation is complete, consistent, and developer-friendly.*
