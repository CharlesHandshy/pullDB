# pullDB QA Test Suite

Comprehensive QA testing framework for pullDB's CLI, API, and Web UI.

## Quick Start

```bash
# Activate virtual environment
source venv/bin/activate

# Install test dependencies
pip install httpx playwright

# Run all QA tests
pytest tests/qa/ -v

# Run only smoke tests (fast)
pytest tests/qa/ -v -m smoke

# Run API tests only
pytest tests/qa/ -v -m api

# Run CLI tests only
pytest tests/qa/ -v -m cli

# Run with HTML report
pytest tests/qa/ -v --html=qa-report.html
```

## Test Categories

| Marker | Description | Duration |
|--------|-------------|----------|
| `smoke` | Quick health checks | < 5s |
| `api` | API endpoint tests | < 10s |
| `cli` | CLI command tests | < 60s |
| `web` | Playwright browser tests | < 30s |
| `db` | Database tests | < 10s |

## Prerequisites

1. **API Server Running**
   ```bash
   set -a && source .env && set +a
   uvicorn pulldb.api.main:app --port 8000
   ```

2. **Environment Variables**
   - See `.env.example` for required variables
   - MySQL database must be accessible

3. **For Web Tests (Optional)**
   ```bash
   pip install playwright
   playwright install chromium
   ```

## Test Files

| File | Tests | Description |
|------|-------|-------------|
| `conftest.py` | - | Fixtures and configuration |
| `test_smoke.py` | 11 | Quick health checks |
| `test_api.py` | 10 | API endpoint tests |
| `test_cli.py` | 8 | CLI command tests |
| `test_web.py` | 8 | Browser tests |

## Fixtures

### API Fixtures
- `api_client` - HTTP client for API requests
- `api_base_url` - Base URL (default: localhost:8000)
- `api_health` - Pre-fetched health status

### CLI Fixtures
- `cli_runner` - Execute pulldb commands
- `cli_env` - Environment with venv activated

### Web Fixtures
- `browser` - Playwright browser instance
- `page` - Browser page
- `web_login_page` - Pre-navigated login page
- `swagger_page` - Pre-navigated Swagger UI

### Test Data Fixtures
- `sample_job_id` - Known completed job ID
- `sample_user_code` - Known user code
- `sample_search_term` - Search term with results

## Adding New Tests

```python
import pytest

@pytest.mark.api
class TestNewFeature:
    """Tests for new feature."""
    
    def test_feature_works(self, api_client):
        """Feature returns expected response."""
        response = api_client.get("/api/new-feature")
        assert response.status_code == 200
        data = response.json()
        assert "expected_field" in data
```

## CI/CD Integration

```yaml
# .github/workflows/qa.yml
name: QA Tests
on: [push, pull_request]

jobs:
  qa-tests:
    runs-on: ubuntu-latest
    services:
      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: test
          MYSQL_DATABASE: pulldb_service
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: pip install -e ".[test]" httpx
      - name: Run QA tests
        run: pytest tests/qa/ -v -m "smoke or api"
```

## Test Execution Log

See `TEST_EXECUTION_LOG.md` for detailed test results and documentation.
