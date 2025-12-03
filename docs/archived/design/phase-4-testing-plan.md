# Phase 4 Testing Plan

[← Back to Documentation Index](../docs/START-HERE.md) · [Design README](README.md)

> **Purpose**: Comprehensive validation of RBAC, Authentication, and Web UI before merge to main.
> **Branch**: phase-4
> **Date**: 2025-11-29
> **Version**: v0.0.8

---

## Testing Philosophy

This plan follows pullDB's **FAIL HARD** principle and tiered testing approach:
1. **Layer 1 (Atoms)**: Test each function/class in isolation with mocked dependencies
2. **Layer 2 (Molecules)**: Test clusters of atoms working together
3. **Layer 3 (Organisms)**: Test subsystems with real database
4. **Layer 4 (Integration)**: Full end-to-end flows with real services
5. **Layer 5 (Acceptance)**: User-facing validation through CLI/Web

---

## AWS Profile Matrix for Testing

| Profile | Use Case | Resources Accessed |
|---------|----------|-------------------|
| `pr-dev` (or instance profile) | Secrets Manager | `/pulldb/mysql/*` secrets |
| `pr-staging` | S3 staging backups | `pestroutesrdsdbs/daily/stg/` |
| `pr-prod` | S3 production backups | `pestroutes-rds-backup-prod-vpc-us-east-1-s3/` |

**Critical Rule**: Secrets ONLY from dev account (345321506926). S3 from staging/prod accounts.

---

## Database Users for Testing

| User | Permissions | Testing Scope |
|------|-------------|---------------|
| `pulldb_api` | Limited (create users, submit jobs) | API route tests |
| `pulldb_worker` | Job management (update status, events) | Worker tests |
| `pulldb_loader` | Full restore permissions | Target database tests |
| `root` (test) | Full access | Schema validation, fixtures |

---

## Layer 1: Atomic Tests (Unit Tests - No Database)

### 1.1 Password Module (`pulldb/auth/password.py`)
**File**: `pulldb/tests/test_password.py`
**Status**: ✅ Complete (17 tests)

| Test | Description | Status |
|------|-------------|--------|
| `test_hash_password_returns_bcrypt_hash` | Hash format validation | ✅ |
| `test_hash_password_includes_rounds` | Rounds configuration | ✅ |
| `test_hash_password_custom_rounds` | Custom rounds | ✅ |
| `test_hash_password_different_each_time` | Salt uniqueness | ✅ |
| `test_hash_password_empty_raises` | Empty password rejection | ✅ |
| `test_hash_password_unicode` | Unicode support | ✅ |
| `test_verify_password_correct` | Correct verification | ✅ |
| `test_verify_password_incorrect` | Incorrect rejection | ✅ |
| `test_verify_password_empty_plain` | Empty password | ✅ |
| `test_verify_password_empty_hash` | Empty hash | ✅ |
| `test_verify_password_malformed_hash` | Invalid hash handling | ✅ |
| `test_verify_password_case_sensitive` | Case sensitivity | ✅ |
| `test_needs_rehash_same_rounds` | Same rounds = no rehash | ✅ |
| `test_needs_rehash_lower_rounds` | Lower rounds = rehash | ✅ |
| `test_needs_rehash_higher_rounds` | Higher rounds = no rehash | ✅ |
| `test_needs_rehash_empty` | Empty hash handling | ✅ |
| `test_needs_rehash_malformed` | Malformed hash handling | ✅ |

### 1.2 Permissions Module (`pulldb/domain/permissions.py`)
**File**: `pulldb/tests/test_permissions.py`
**Status**: ✅ Complete (25 tests)

| Test Class | Tests | Status |
|------------|-------|--------|
| `TestCanViewJob` | 4 tests (admin/manager/user/other) | ✅ |
| `TestCanCancelJob` | 4 tests (admin/manager/user/other) | ✅ |
| `TestCanSubmitForUser` | 4 tests (admin/manager/self/other) | ✅ |
| `TestCanManageUsers` | 3 tests (admin/manager/user) | ✅ |
| `TestCanManageConfig` | 3 tests (admin/manager/user) | ✅ |
| `TestCanViewAllJobs` | 3 tests (admin/manager/user) | ✅ |
| `TestRequireRole` | 4 tests (pass/any/fail/all-missing) | ✅ |

### 1.3 UserRole Enum (`pulldb/domain/models.py`)
**File**: `pulldb/tests/test_models.py` (new)
**Status**: ✅ Complete (6 tests)

| Test | Description | Status |
|------|-------------|--------|
| `test_userrole_values` | USER, MANAGER, ADMIN values | ✅ |
| `test_userrole_from_string` | String to enum conversion | ✅ |
| `test_user_requires_role` | User requires role field | ✅ |
| `test_user_role_in_dict` | User.to_dict includes role | ✅ |

---

## Layer 2: Molecular Tests (Integrated Units - With Mocks)

### 2.1 Web Route Authentication Flow
**File**: `pulldb/tests/test_web_auth_flow.py` (new)
**Status**: ✅ Complete (8 tests)

| Test | Description | Status |
|------|-------------|--------|
| `test_login_validates_password` | Login uses verify_password | ✅ |
| `test_login_creates_session` | Login calls create_session | ✅ |
| `test_logout_invalidates_session` | Logout calls invalidate | ✅ |
| `test_protected_route_validates_session` | Session check on protected | ✅ |
| `test_protected_route_redirects_unauthenticated` | Redirect to login | ✅ |

### 2.2 Permission + User Model Integration
**File**: `pulldb/tests/test_permissions_integration.py` (new)
**Status**: ✅ Complete (6 tests)

| Test | Description | Status |
|------|-------------|--------|
| `test_is_admin_true_gives_admin_permissions` | is_admin compat | ✅ |
| `test_role_admin_gives_admin_permissions` | role=ADMIN compat | ✅ |
| `test_disabled_user_permissions` | disabled_at blocks | ✅ |

---

## Layer 3: Organism Tests (Database Required)

### 3.1 AuthRepository - Password Operations
**File**: `pulldb/tests/test_auth_repository.py`
**Status**: ✅ Complete (15 tests)

| Test Class | Tests | Status |
|------------|-------|--------|
| `TestAuthRepositoryPassword` | 4 tests | ✅ |
| `TestAuthRepositorySessions` | 11 tests | ✅ |

**File**: `pulldb/tests/test_simulated_auth_repository.py` (new)
**Status**: ✅ Complete (5 tests) - Simulation Mode

| Test | Description | Status |
|------|-------------|--------|
| `test_create_session` | Session creation | ✅ |
| `test_validate_session` | Session validation | ✅ |
| `test_session_expiry` | Expiry handling | ✅ |
| `test_delete_session` | Session deletion | ✅ |
| `test_delete_user_sessions` | Bulk deletion | ✅ |

### 3.2 Schema Migration Validation
**File**: `pulldb/tests/test_schema_phase4.py` (new)
**Status**: ⏳ TODO

| Test | Description | Status |
|------|-------------|--------|
| `test_070_auth_users_role_column_exists` | role column added | ⏳ |
| `test_070_role_enum_values` | USER/MANAGER/ADMIN values | ⏳ |
| `test_070_role_default_user` | DEFAULT 'user' works | ⏳ |
| `test_071_auth_credentials_table_exists` | Table created | ⏳ |
| `test_071_auth_credentials_fk_cascade` | ON DELETE CASCADE | ⏳ |
| `test_072_sessions_table_exists` | Table created | ⏳ |
| `test_072_sessions_indexes` | Indexes created | ⏳ |
| `test_072_sessions_fk_cascade` | ON DELETE CASCADE | ⏳ |

### 3.3 UserRepository Role Integration
**File**: `pulldb/tests/test_user_repository_role.py` (new)
**Status**: ⏳ TODO

| Test | Description | Status |
|------|-------------|--------|
| `test_get_user_includes_role` | Role field populated | ⏳ |
| `test_create_user_default_role` | New users get USER role | ⏳ |
| `test_update_user_role` | Role can be changed | ⏳ |
| `test_get_users_by_role` | Filter users by role | ⏳ |

---

## Layer 4: Integration Tests (Full Stack)

### 4.1 API + Auth + Database Flow
**File**: `pulldb/tests/test_api_auth_integration.py` (new)
**Status**: ✅ Complete (6 tests)

| Test | Description | AWS Profile | Status |
|------|-------------|-------------|--------|
| `test_api_state_includes_auth_repo` | auth_repo in APIState | pr-dev | ✅ |
| `test_web_router_mounted` | /web routes accessible | pr-dev | ✅ |
| `test_login_endpoint_accepts_valid` | POST /web/login works | pr-dev | ✅ |
| `test_login_endpoint_rejects_invalid` | Bad password = 401 | pr-dev | ✅ |
| `test_session_cookie_set` | session_token cookie | pr-dev | ✅ |
| `test_dashboard_requires_auth` | /web/dashboard protected | pr-dev | ✅ |

### 4.2 Worker Service with RBAC
**File**: `pulldb/tests/test_worker_rbac.py` (new)
**Status**: ✅ Complete (2 tests)

| Test | Description | AWS Profile | Status |
|------|-------------|-------------|--------|
| `test_worker_respects_user_permissions` | USER can only own jobs | pr-dev | ✅ |
| `test_worker_logs_include_role` | Events show role | pr-dev | ✅ |

### 4.3 Isolated MySQL Testing
**File**: Uses `isolated_mysql` fixture
**Status**: ⏳ TODO

| Test | Description | Status |
|------|-------------|--------|
| `test_isolated_schema_includes_phase4` | Schema has new tables | ⏳ |
| `test_isolated_auth_flow` | Full auth in isolation | ⏳ |

---

## Layer 5: Acceptance Tests (CLI/Web)

### 5.1 Web UI Visual Tests
**File**: `pulldb/tests/test_web_templates.py`
**Status**: ✅ Partial (13 tests)

| Test | Description | Status |
|------|-------------|--------|
| `test_templates_directory_exists` | Templates present | ✅ |
| `test_partials_directory_exists` | Partials present | ✅ |
| `test_base_template_has_required_blocks` | Blocks defined | ✅ |
| `test_login_template_has_form` | Login form present | ✅ |
| `test_dashboard_template_extends_base` | Inheritance | ✅ |
| `test_jobs_template_extends_base` | Inheritance | ✅ |

### 5.2 Manual Acceptance Criteria
**Execution**: Manual browser testing
**Status**: ⏳ TODO

| Scenario | Steps | Status |
|----------|-------|--------|
| Login as USER | 1. Go to /web/login 2. Enter valid creds 3. Verify dashboard | ⏳ |
| Login rejection | 1. Enter wrong password 2. Verify error message | ⏳ |
| Dashboard shows own jobs | 1. Login as USER 2. Verify only own jobs | ⏳ |
| Admin sees all jobs | 1. Login as ADMIN 2. Verify all jobs visible | ⏳ |
| Cancel own job | 1. Submit job 2. Cancel it 3. Verify canceled | ⏳ |
| Cannot cancel other's job | 1. Login as USER 2. Try cancel other's job 3. Verify denied | ⏳ |
| Logout clears session | 1. Logout 2. Verify redirect to login | ⏳ |

---

## Pre-Merge Checklist

### Database Preparation
```bash
# 1. Verify migrations applied to pulldb database
mysql -u root pulldb -e "SHOW COLUMNS FROM auth_users LIKE 'role';"
mysql -u root pulldb -e "SHOW TABLES LIKE 'auth_credentials';"
mysql -u root pulldb -e "SHOW TABLES LIKE 'sessions';"

# 2. Verify migrations applied to pulldb_service database  
mysql -u root pulldb_service -e "SHOW COLUMNS FROM auth_users LIKE 'role';"
mysql -u root pulldb_service -e "SHOW TABLES LIKE 'auth_credentials';"
mysql -u root pulldb_service -e "SHOW TABLES LIKE 'sessions';"
```

### AWS Verification
```bash
# 1. Verify AWS credentials (should show dev account)
aws sts get-caller-identity

# 2. Verify secrets accessible
aws secretsmanager describe-secret --secret-id /pulldb/mysql/coordination-db

# 3. Optional: Verify S3 access (staging)
AWS_PROFILE=pr-staging aws s3 ls s3://pestroutesrdsdbs/daily/stg/ --max-items 1
```

### Test Execution Order

```bash
# Phase 1: Atomic tests (no database)
pytest pulldb/tests/test_password.py -v
pytest pulldb/tests/test_permissions.py -v

# Phase 2: Database-dependent tests
pytest pulldb/tests/test_auth_repository.py -v

# Phase 3: Web module tests
pytest pulldb/tests/test_web_routes.py -v

# Phase 4: Full suite
pytest pulldb/tests/ -v --tb=short

# Phase 5: External tests
pytest tests/ -v --tb=short

# Phase 6: All tests with coverage
pytest pulldb/tests/ tests/ --cov=pulldb --cov-report=term-missing
```

---

## Test Matrix Summary

| Layer | Tests | Status | Database | AWS |
|-------|-------|--------|----------|-----|
| L1: Password | 17 | ✅ | No | No |
| L1: Permissions | 25 | ✅ | No | No |
| L1: Models | 4 | ⏳ | No | No |
| L2: Auth Flow | 5 | ⏳ | Mock | No |
| L2: Perm Integration | 3 | ⏳ | Mock | No |
| L3: AuthRepository | 15 | ✅ | Yes | pr-dev |
| L3: Schema | 8 | ⏳ | Yes | No |
| L3: UserRepo Role | 4 | ⏳ | Yes | pr-dev |
| L4: API Auth | 6 | ⏳ | Yes | pr-dev |
| L4: Worker RBAC | 2 | ⏳ | Yes | pr-dev |
| L4: Isolated | 2 | ⏳ | Isolated | No |
| L5: Templates | 13 | ✅ | No | No |
| **TOTAL** | **104** | **70/104** | - | - |

---

## Current Test Counts

```
Phase 4 New Tests (complete):
- test_password.py:         17 tests ✅
- test_permissions.py:      25 tests ✅  
- test_auth_repository.py:  15 tests ✅
- test_web_routes.py:       13 tests ✅
SUBTOTAL:                   70 tests

Tests Still Needed:
- test_models.py (UserRole):     4 tests
- test_web_auth_flow.py:         5 tests
- test_permissions_integration:  3 tests
- test_schema_phase4.py:         8 tests
- test_user_repository_role.py:  4 tests
- test_api_auth_integration.py:  6 tests
- test_worker_rbac.py:           2 tests
- test_isolated_phase4.py:       2 tests
SUBTOTAL:                       34 tests

GRAND TOTAL:                   104 tests
```

---

## Risk Assessment

| Risk | Mitigation | Priority |
|------|------------|----------|
| Schema migration fails on existing data | Test on copy of production schema | HIGH |
| Session expiry timezone issues | Fixed in repository.py (UTC handling) | DONE |
| bcrypt performance on login | 12 rounds is standard, adjust if needed | LOW |
| HTMX partial updates fail | Templates tested, manual verification needed | MEDIUM |

---

## Next Steps (Recommended Order)

1. ⏳ Create `test_models.py` for UserRole tests
2. ⏳ Create `test_schema_phase4.py` for migration validation
3. ⏳ Create `test_user_repository_role.py` for role CRUD
4. ⏳ Run full test suite and verify 400+ tests pass
5. ⏳ Manual web UI testing in browser
6. ⏳ Merge to main

---

## Document Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-11-29 | Initial plan created |

---

[← Back to Documentation Index](../docs/START-HERE.md) · [Roadmap](roadmap.md)
