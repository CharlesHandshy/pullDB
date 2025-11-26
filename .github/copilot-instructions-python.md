# Python Implementation Guidelines

## Test Database Credential Mandate (Effective Nov 2025)

**MANDATORY**: All integration and repository tests must use AWS Secrets Manager for database login. Direct test user logins (e.g., 'pulldb_test'@'localhost') are deprecated and must not be used for DB authentication in tests. Application test users (for business logic) remain valid for app-level testing.

**Implementation Status** (as of November 1, 2025):
- ✅ Test fixtures updated to use AWS Secrets Manager (`pulldb/tests/conftest.py`)
- ✅ Secret residency verification added (`verify_secret_residency` fixture)
- ✅ Graceful degradation for offline development (local override support)
- ✅ Comprehensive test documentation (`docs/testing.md`)
- ✅ All 87 tests passing with AWS integration

**Secret Residency Enforcement**:
- New `verify_secret_residency` fixture validates secrets exist only in development account (345321506926)
- Automatically asserts secret ARN contains correct account ID
- Gracefully skips when AWS unavailable (offline development)
- Fails with clear error message if secret found in wrong account (staging/prod)

**Migration Steps** (COMPLETED):
- ✅ Update all test fixtures to resolve DB credentials via AWS Secrets Manager (use CredentialResolver).
- ✅ Store test DB credentials in `/pulldb/mysql/coordination-db` secret.
- ✅ Remove any direct use of test user credentials in test connection pools.
- ✅ Document this pattern in all setup and test documentation.

**Rationale:**
- Ensures test and production credential resolution paths are identical.
- Prevents drift between test and production authentication logic.
- Simplifies credential rotation and audit.
- Validates secrets exist in correct AWS account (dev-only constraint).

**Reference:** See `docs/testing.md` for complete testing guide and `docs/aws-secrets-manager-setup.md` for credential setup.

#### Development Override (Temporary)

For local development only (never CI or production), a temporary override path
is available when the coordination DB secret hostname is unreachable or AWS
read permissions are pending. The test fixture logic will prefer the following
environment variables when all are set:

- `PULLDB_TEST_MYSQL_HOST`
- `PULLDB_TEST_MYSQL_USER`
- `PULLDB_TEST_MYSQL_PASSWORD`
- `PULLDB_TEST_MYSQL_DATABASE`

This bypass exists solely to keep momentum during secret propagation delays.
It must not be used in committed code examples, CI pipelines, or documentation
outside this section. Remove the override once the canonical secret
(`/pulldb/mysql/coordination-db`) resolves successfully in the development
account. All tests must still exercise the CredentialResolver path by default.

## Proactive Error Checking

**CRITICAL**: Always use the `get_errors` tool to check for VS Code diagnostics before and after editing files. This tool provides access to:
- **Ruff diagnostics**: Missing docstrings (D101-D107), style violations (E, W), unused imports (F401), etc.
- **Mypy diagnostics**: Type checking errors, incompatible types, missing type hints
- **Other linters**: Any configured VS Code extensions

**Workflow**:
1. Before editing: `get_errors` on target files to understand existing issues
2. Make changes addressing the issues
3. After editing: `get_errors` to verify fixes and check for new issues
4. Iterate until all errors are resolved

**Example Error**: `config.py:16 - Missing docstring in public class Ruff(D101)`
- **Action**: Add comprehensive Google-style docstring to class
- **Verification**: Run `get_errors` again to confirm fix

## Project Structure (from `design/implementation-notes.md`)
```python
pulldb/
  cli/           # Command validation, option parsing, API calls
  api/           # API Service - HTTP endpoints, job creation, status queries
  worker/        # Worker Service - Job polling, S3 download, MySQL restore orchestration
  infra/         # MySQL, S3, logging abstractions (shared by API + Worker)
  domain/        # Job, JobEvent, configuration dataclasses (shared)
  tests/         # Unit tests with test MySQL instances, integration smoke tests
```

## Code Style (PEP 8 Required)
**Primary Reference**: See `docs/coding-standards.md` for complete standards covering Python, Markdown, SQL, Shell, YAML, and Mermaid.

**Python Quick Reference**:
- **Primary linter**: Ruff (replaces Flake8, isort, pydocstyle, etc.) - 10-100x faster
- **Maximum line length**: 88 characters (Ruff/Black default)
- **Type hints required**: All function signatures must include type hints (checked by mypy)
- **Docstrings required**: Google-style docstrings for all public functions/classes (Ruff D101-D107)
- **Import order**: stdlib, third-party, local (alphabetized within groups, enforced by Ruff I001)
- **Naming**: snake_case for functions/variables, PascalCase for classes, UPPER_CASE for constants (Ruff N802, N806)
- **Error handling**: Use specific exceptions, always `raise ... from e` to preserve traceback (Ruff B904)
- **No print statements**: Use Python `logging` module exclusively (Ruff T201)
- **Quality tools**: Code must pass `ruff check`, `ruff format`, `mypy`, and tests before commit
- **VS Code integration**: Use `get_errors` tool to access real-time Ruff/mypy diagnostics

## Development File Ownership Principle (Effective Nov 2025)

All files created or modified during development inside a user-controlled directory (e.g., `/home/<user>/Projects/.../pullDB`) **must remain owned by that user** (not `root`) unless a specific production packaging or system integration step explicitly requires root ownership (e.g., system-wide install, systemd unit deployment). Root ownership in a development working copy creates friction (sudo required for edits) and increases the risk of accidental permission escalation or silent failures.

Ownership & Permissions Baseline (Current Standard):
- Ownership: `charleshandshy:charleshandshy` (replace with active dev user)
- Directories: `750` (restrict world access; group expansion possible later)
- Executable scripts & entrypoints: `750` (user rwx, group rx)
- Regular source/config files: `640` (user rw, group r)
- Credentials/secrets artifacts: `600` or `640` depending on group read need
- Virtual environment bin contents: `750` (preserve executability)

Rationale:
1. Eliminates sudo dependency for iterative edits (accelerates feedback loop).
2. Preserves FAIL HARD transparency—permission errors now indicate intentional boundaries.
3. Reduces chance of accidentally committing root-owned artifacts that fail CI or block cleanup.
4. Simplifies automation scripts (no conditional sudo logic for normal file writes).

Agent Enforcement Rules:
1. When introducing new files via patches, ensure they inherit non-root ownership (implicitly by creating under the user’s directory).
2. Do NOT chown files to root during development tasks unless explicitly part of packaging or system install instructions.
3. If a script requires elevated operations, prefer targeted `sudo` calls (e.g., `sudo mysql ...`) rather than changing script ownership.
4. Normalize permissions after bulk operations touching venv or extracted artifacts (apply the baseline pattern above).
5. Treat unexpected root ownership as a **diagnostic event**: investigate origin (installation step, manual sudo edit), correct, and record resolution.

FAIL HARD Diagnostic Template (Ownership Drift):
```
Goal: Maintain user-level ownership for development workspace
Problem: Found 12 files owned by root under test-env/ after venv rebuild
Root Cause: Setup script executed under sudo without post-install chown normalization
Solutions:
 1. (Preferred) Add post-setup chown -R <user>:<user> test-env/ (documented in script)
 2. Restrict sudo usage to individual commands instead of whole script execution
 3. Add automated permission audit to pre-commit (future enhancement)
```

Future Enhancements:
- Add a `--normalize-perms` flag to `setup-test-environment.sh` to enforce baseline automatically.
- Integrate a lightweight permission audit command (`scripts/audit-permissions.sh`) with CI warning if drift detected.
- Add `permissions-audit` GitHub Action workflow to enforce zero root-owned artifacts and drift-free `test-env` when present.
- Add local pre-commit hook (`permission-audit`) invoking `scripts/audit-permissions.sh test-env`.

Commit Tag Convention:
- When correcting ownership/permission drift include `PermFix:` line summarizing scope (e.g., `PermFix: normalized test-env (23 files)`).
- When adding automation around ownership/permissions include `PermGuard:` tag for traceability.

Agents MUST apply this principle whenever creating or modifying development artifacts. Root-owned development files are considered **hygiene debt** and should be corrected immediately.

**Other File Types**:
- **Markdown**: Follow CommonMark + GitHub Flavored Markdown (enforced by markdownlint)
- **SQL**: SQL Style Guide with MySQL dialect (enforced by sqlfluff)
- **Shell**: Google Shell Style Guide (enforced by shellcheck + shfmt)
- **YAML**: YAML 1.2 spec (enforced by yamllint)
- **Mermaid**: Clear node IDs, descriptive labels, consistent styling

All standards automatically enforced via pre-commit hooks. See `constitution.md` and `docs/coding-standards.md` for complete details.

## Dependency Patterns
- **MySQL**: `mysql-connector-python` or `PyMySQL` for coordination database and restored databases
- **S3**: `boto3.client('s3')` with paginated listing for latest backup discovery
- **MySQL Restore**: Shell out to `myloader` via `subprocess.run`, capture stdout/stderr
- **Testing**: `pytest` with fixtures, moto for S3 mocking, test MySQL instances
- **Logging**: Structured JSON via Python `logging`, include job_id/target/phase

## Repository Pattern
```python
class JobRepository:
    def enqueue_job(self, job: Job) -> None: ...
    def mark_running(self, job_id: str) -> None: ...
    def append_event(self, job_id: str, event_type: str, detail: str) -> None: ...
```
