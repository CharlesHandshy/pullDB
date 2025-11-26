# AI Agent Behavior & Hygiene Standards

## AI Agent FAIL HARD Mandate

**CRITICAL**: When debugging issues or implementing features, AI agents must follow the FAIL HARD philosophy (see `constitution.md` for complete requirements).

### Diagnostic Protocol

When encountering failures, AI agents must:

1. **Detect the Failure**
   - Use `get_errors` tool to check VS Code diagnostics
   - Run commands and verify exit codes
   - Read logs and error messages completely
   - Don't assume - verify actual state

2. **Research Root Cause**
   - Gather context: read relevant files, check configuration, verify permissions
   - Use appropriate tools: `grep_search`, `read_file`, `run_in_terminal`
   - Trace the failure path back to the originating condition
   - Validate hypothesis with concrete evidence (don't speculate)

3. **Present Structured Findings**

   **Goal**: What was the intended outcome?
   - Example: "Configure test suite to use AWS Secrets Manager for MySQL credentials"

   **Problem**: What actually happened? (Be specific)
   - Example: "All 50 tests skipped with message 'Cannot verify secret residency: Secrets Manager can't find the specified secret'"

   **Root Cause**: Why did it fail? (Validated diagnosis)
   - Example: "Tests running without AWS credentials (AWS_PROFILE not set). The `verify_secret_residency` fixture calls boto3.client() which defaults to looking for credentials in standard locations. When no credentials found, boto3 raises NoCredentialsError, caught by fixture's broad exception handler, triggering skip."

   **Solutions** (ranked by effectiveness):
   1. **Best Solution**: "Set AWS_PROFILE environment variable to 'default' before running tests. This uses EC2 instance profile credentials."
      - Pros: Matches production authentication, validates full AWS integration
      - Cons: Requires AWS access
   2. **Alternative**: "Use local override variables (PULLDB_TEST_MYSQL_*) to bypass AWS entirely"
      - Pros: Works offline, faster test execution
      - Cons: Doesn't validate AWS integration path, skips residency check
   3. **Workaround**: "Mock boto3 client in tests to simulate secret retrieval"
      - Pros: No AWS dependency
      - Cons: Doesn't validate real AWS behavior, test complexity increases

4. **Implement and Verify**
   - Apply the chosen solution
   - Run verification commands to confirm fix
   - Check for regressions using `get_errors`
   - Document the resolution if it reveals architectural decisions

### Prohibited Behaviors

**NEVER**:
- ❌ Silently catch exceptions without logging or user notification
- ❌ Add `try/except: pass` blocks that hide failures
- ❌ Return empty results or None when operation fails
- ❌ Implement workarounds without explaining why direct fix isn't used
- ❌ Skip diagnostic steps and jump to solutions
- ❌ Present speculation as fact ("this might be because...")

**ALWAYS**:
- ✅ Use specific exception types in error handling
- ✅ Preserve stack traces with `raise ... from e`
- ✅ Log failures with context (job_id, operation, inputs)
- ✅ Return errors to caller, don't swallow them
- ✅ Verify root cause before proposing solutions
- ✅ Present evidence-based diagnosis

### Warning Eradication Principle (NEW Nov 3 2025)

Treat every warning (lint, type-check, schema, formatting) as an **incubating error** that will become
harder and more expensive to fix later. Agents must prefer **eliminating** the underlying cause over
silencing it. This principle extends FAIL HARD: silent deferral of minor issues violates forward
stability. Acceptable responses to warnings:

1. Remove the root cause (refactor, annotate, tighten types, adjust schema).
2. Strengthen validation (add explicit guards, TypeGuards, assertions) so tools gain certainty.
3. Document the limitation AND open a tracked work item when immediate removal is impossible.

Unacceptable responses:
- Adding broad `type: ignore` or blanket suppression without justification.
- Leaving a warning unaddressed in production code because it is "low priority".
- Converting warnings into ignores in bulk commits.

Narrow (scoped) ignores are permitted only when:
- Tooling exhibits a verified false positive AND
- A precise, single‑line ignore is annotated with a rationale AND
- A follow‑up improvement path is documented (e.g., pending library stub update).

Metric: Warning count in critical paths (infra/, domain/, worker/, cli/) SHOULD trend to **zero**.
Test files may carry temporary structured ignores only when they exercise intentionally invalid
inputs. Each ignore must include a justification string.

Commit Message Tag: When removing warnings, include `WarnFix:` line summarizing count reduced.

### Error Message Standards

Code must produce actionable error messages:

```python
# ❌ BAD: Vague, no context, no solution
raise Exception("Operation failed")

# ❌ BAD: Swallows original error
try:
    operation()
except Exception:
    raise ValueError("Something went wrong")

# ✅ GOOD: Specific, contextualized, actionable
try:
    client.describe_secret(SecretId=secret_id)
except ClientError as e:
    if e.response["Error"]["Code"] == "ResourceNotFoundException":
        raise SecretNotFoundError(
            f"Secret '{secret_id}' does not exist in AWS Secrets Manager. "
            f"Create it with: aws secretsmanager create-secret "
            f"--name {secret_id} --secret-string '{{...}}' "
            f"See docs/aws-secrets-manager-setup.md for complete setup."
        ) from e
    elif e.response["Error"]["Code"] == "AccessDenied":
        raise PermissionError(
            f"Access denied reading secret '{secret_id}'. "
            f"Ensure IAM role has 'secretsmanager:GetSecretValue' permission. "
            f"Verify policy attachment: aws iam list-attached-role-policies "
            f"--role-name pulldb-ec2-service-role"
        ) from e
    else:
        raise  # Unexpected error - preserve original
```

### Test Fixture Behavior

Test fixtures must fail with clear messages, not silently skip:

```python
# ❌ BAD: Silent degradation
def mysql_credentials():
    try:
        return resolver.resolve(secret_id)
    except:
        return MySQLCredentials("localhost", "root", "")  # Hides failure

# ✅ GOOD: Explicit skip with diagnostic message
def mysql_credentials():
    try:
        return resolver.resolve(secret_id)
    except NoCredentialsError as e:
        pytest.skip(
            f"AWS credentials not configured. "
            f"Set AWS_PROFILE environment variable or configure "
            f"~/.aws/credentials. See docs/testing.md for setup. "
            f"Original error: {e}"
        )
```

## Pre-Commit Hygiene Protocol

**Purpose**: Guarantee every commit preserves code quality, test integrity, documentation accuracy (drift ledger + README status), and excludes transient artifacts. Integrates with FAIL HARD—any failed step aborts with actionable diagnostics.

### Ordered Checklist (Abort on First Failure)
1. Working tree sanity: `git status` shows only intended changes; no stray large archives or dumps.
2. Formatting: `ruff format .` (must produce no diffs on second run).
3. Lint: `ruff check .` (zero errors/warnings required for commit).
4. Types: `mypy .` (no errors; introduce stubs or refactors instead of ignoring).
5. Tests: `pytest -q --timeout=60 --timeout-method=thread` (all pass; invoke Timeout Monitoring Protocol if timeouts).
6. Drift ledger sync: Update in `.github/copilot-instructions-status.md`—Completed Work + Not Yet Implemented + Implementation Drift Tracking—reflect new components or status changes (add ✅/❌ transitions only with evidence).
7. Test count & duration: Capture latest line (e.g., `112 passed in 55.3s`) and ensure commit message includes it.
8. .gitignore audit: Confirm newly introduced transient patterns are ignored (extraction dirs, profiling output) and no essential assets are accidentally excluded.
9. README status block: Update only if milestone progress (feature implemented or promoted from pending).
10. Commit message uses standard template (see below).

### Commit Message Template
```
pullDB: <component>: <short summary>

Component: <files/modules>
Change-Type: feature|fix|refactor|docs|hygiene
Tests: <N> tests passing in <S.SS>s (timeout=60s)
Drift: Updated <sections touched>
Hygiene: ruff+mypy+pytest clean; gitignore audited; docs synced
```

### Artifact Classification
| Category | Tracked | Ignored |
|----------|---------|---------|
| Source & Domain | `pulldb/`, design docs, SQL scripts in `customers_after_sql/`, `qa_template_after_sql/` | Generated caches (`__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`) |
| Backups / Dumps | (Never) | `*.sql*`, `*.tar*`, `*.dump`, extracted working dirs (`pulldb_work_*`) |
| Environment | Required examples in docs | `.env`, local overrides, virtual env dirs (`venv/`, `.venv/`) |
| Diagnostics | FAIL HARD logs embedded in exceptions | `*.log`, profiling (`profile/`, `profiling/`), benchmarking (`.benchmarks/`) |
| Processes | N/A | PID/trace artifacts (`*.pid`, `*.out`, `*.trace`, `*.stackdump`) |

### Failure Protocol (Example)
```
Goal: Run mypy type checks pre-commit
Problem: mypy reported 2 incompatible type errors in staging.py
Root Cause: Row access uses generic Any without explicit tuple type; missing cast/ignore
Solutions:
 1. Add typed protocol or cast for cursor.fetchall rows (preferred)
 2. Introduce TypedDict/NamedTuple for database rows
 3. As last resort, narrow ignore with type: ignore[index] and explain in code comment
```

### Safeguards
- Never ignore business SQL sanitization scripts.
- Do not auto-commit if test count decreased without explicit rationale.
- Avoid broad patterns (e.g., `*work*`)—use specific prefixes (`pulldb_work_`).
- Re-run ruff and mypy after doc edits (docs can introduce trailing whitespace issues).

### Future Extensions
- Add `scripts/precommit-verify.py` to automate checklist (planned).
- Integrate performance baseline alerts (average test duration trending upward >10%).
- Security scan injection (dependency vulnerability checks) after core workflow completes.

### Success Criteria
- All steps green.
- Commit message contains hygiene block.
- Drift ledger and test count correct.
- No transient artifacts added.
