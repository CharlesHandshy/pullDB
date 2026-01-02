# Phase 4 Testing Plan

**Date**: November 29, 2025  
**Branch**: phase-4  
**Status**: ✅ Complete - 439 tests passing

---

## Overview

This document outlines the comprehensive testing strategy for Phase 4 (RBAC, Auth, Web UI) using a layered approach from unit tests to integration tests.

## Test Layers

### Layer 1: Pure Unit Tests (No Dependencies)
Tests that run without database, AWS, or external services.

| Test File | Tests | Description |
|-----------|-------|-------------|
| `test_password.py` | 17 | bcrypt hash, verify, needs_rehash |
| `test_permissions.py` | 25 | RBAC permission functions |
| `test_models_role.py` | 13 | UserRole enum, User model role field |
| `test_web_routes.py` | 13 | Template structure, route definitions |

**Total Layer 1**: 68 tests

### Layer 2: Mock-Based Tests
Tests using mocked dependencies.

| Test File | Tests | Description |
|-----------|-------|-------------|
| (Existing tests) | ~50 | Various mock-based tests |

### Layer 3: Database Integration Tests
Tests requiring MySQL connection.

| Test File | Tests | Description |
|-----------|-------|-------------|
| `test_auth_repository.py` | 15 | Password hash storage, session management |
| `test_schema_phase4.py` | 11 | Schema migration validation (070/071/072) |
| `test_user_repository_role.py` | 6 | UserRepository role CRUD operations |

**Total Layer 3**: 32 tests

### Layer 5: Web UI Tests
Tests for web routes and templates.

| Test File | Tests | Description |
|-----------|-------|-------------|
| `test_web_routes.py` | 13 | Route definitions, template content |

---

## Test Execution

### Prerequisites

```bash
# Activate virtual environment
source .venv/bin/activate

# Set MySQL credentials for database tests
export PULLDB_TEST_MYSQL_HOST=localhost
export PULLDB_TEST_MYSQL_USER=pulldb_app
export PULLDB_TEST_MYSQL_PASSWORD='<password-from-secret>'
```

### Run All Tests

```bash
# Full suite (427 + 12 = 439 tests)
python -m pytest pulldb/tests/ tests/ -v

# Quick run (no verbose)
python -m pytest pulldb/tests/ tests/ -q
```

### Run Layer-Specific Tests

```bash
# Layer 1: Pure unit tests (no DB needed)
python -m pytest pulldb/tests/test_password.py \
    pulldb/tests/test_permissions.py \
    pulldb/tests/test_models_role.py \
    pulldb/tests/test_web_routes.py -v

# Layer 3: Database integration tests
python -m pytest pulldb/tests/test_auth_repository.py \
    pulldb/tests/test_schema_phase4.py \
    pulldb/tests/test_user_repository_role.py -v
```

---

## AWS Profile Configuration

### pr-dev (Secrets Manager)
- **Account**: 345321506926 (Development)
- **Purpose**: MySQL coordination DB credentials
- **Secret**: `/pulldb/mysql/coordination-db`

### pr-staging (S3)
- **Account**: 333204494849 (Staging)
- **Bucket**: `pestroutesrdsdbs/daily/stg/`

### pr-prod (S3)
- **Account**: 448509410610 (Production)
- **Bucket**: `pestroutes-rds-backup-prod-vpc-us-east-1-s3`

---

## Database User Access

| User | Purpose | Permissions |
|------|---------|-------------|
| `pulldb_app` | General test operations | Full pulldb database access |
| `pulldb_api` | API service | SELECT, INSERT, UPDATE on jobs, users |
| `pulldb_worker` | Worker service | Full job lifecycle access |
| `pulldb_migrate` | Schema migrations | DDL operations |

---

## Schema Migrations (Phase 4)

| Migration | Description |
|-----------|-------------|
| `00700_auth_users_role.sql` | Add UserRole enum to auth_users |
| `00710_auth_credentials.sql` | Password hash storage table |
| `00720_sessions.sql` | Session management table |

---

## Test Results Summary

```
Total Tests: 439
  - pulldb/tests/: 427 passed, 1 xfailed
  - tests/: 12 passed
  
Execution Time: ~2 minutes
```

---

## New Test Files (Phase 4)

1. `pulldb/tests/test_password.py` - Password hashing utilities
2. `pulldb/tests/test_permissions.py` - RBAC permission functions
3. `pulldb/tests/test_models_role.py` - UserRole enum and model
4. `pulldb/tests/test_auth_repository.py` - Auth repository operations
5. `pulldb/tests/test_schema_phase4.py` - Schema migration validation
6. `pulldb/tests/test_user_repository_role.py` - UserRepository role handling
7. `pulldb/tests/test_web_routes.py` - Web UI routes and templates
