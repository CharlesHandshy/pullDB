# Testing Strategy & Protocols

## Testing Strategy

### Unit Tests
- Test MySQL instances with temporary databases
- Mock S3 calls with moto library
- Mock subprocess calls to avoid external dependencies
- Test user_code generation edge cases and collision handling

### Integration Tests
- Use local installed shared MySQL instance for disposable MySQL instances ensuring consistent environment and cleanup after tests always
- Test complete restore flow against staging S3 bucket
- Verify cleanup and error handling scenarios

## Test Timeout Monitoring Protocol

**CRITICAL**: All test executions must include timeout monitoring to detect hanging tests, resource leaks, and deadlocks early. This protocol ensures test suite reliability and provides diagnostic data for FAIL HARD resolution.

### Standard Test Execution

**Command** (all test runs):
```bash
pytest -q --timeout=60 --timeout-method=thread
```

**Configuration**:
- **Timeout**: 60 seconds per test (default for unit tests)
- **Method**: Thread-based timeout (reliable across platforms, works with subprocess calls)
- **Exit behavior**: Non-zero exit code with "TIMEOUT" in output when test exceeds limit

**Timeout Thresholds by Test Type**:
- Unit tests: 60 seconds (current suite averages 2-3s per test)
- Integration tests: 120 seconds (real AWS/MySQL operations)
- End-to-end restore tests: 300 seconds (S3 download, myloader, post-SQL)

### Timeout Detection and Escalation

**When timeout occurs**, automatically invoke diagnostic protocol:

1. **Identify timed-out test** from pytest output:
   ```
   FAILED test_module.py::test_function - Failed: Timeout >60.0s
   ```

2. **Execute diagnostic re-run** with verbose flags:
   ```bash
   pytest -vv -s --timeout=120 --timeout-method=thread -p no:xdist test_module.py::test_function
   ```

3. **Diagnostic flags explained**:
   - `-vv`: Very verbose (show fixture setup/teardown, test progress)
   - `-s`: Disable output capture (see real-time logging, print statements)
   - `--timeout=120`: Double timeout for observation
   - `-p no:xdist`: Disable parallel execution (run serially for isolation)
   - `--tb=long`: Long traceback format (optional, add if needed)

4. **Collect resource state**:
   ```bash
   # Check for orphaned processes
   ps aux | grep -E "(myloader|pytest|python)" | grep -v grep

   # Check for unclosed MySQL connections
   mysql -e "SHOW PROCESSLIST" | grep pulldb

   # Check for open file handles (if test PID known)
   lsof -p <pytest_pid>

   # Check for temp files not cleaned up
   ls -la /tmp/*pulldb* 2>/dev/null
   ```

5. **Present structured FAIL HARD report**:
   ```
   TIMEOUT DETECTED
   ================
   Test: test_module.py::test_function_name
   Timeout: 60 seconds
   Last Output: [captured output before timeout]

   DIAGNOSTIC RE-RUN
   =================
   Command: pytest -vv -s --timeout=120 -p no:xdist test_module.py::test_function_name
   Result: [timeout again | passed | failed with error]
   Duration: [actual time if completed]

   ROOT CAUSE ANALYSIS
   ===================
   [Evidence-based diagnosis: which operation hung, resource state]

   RECOMMENDED SOLUTIONS
   =====================
   1. [Most effective fix with code example]
   2. [Alternative approach]
   3. [Workaround if needed]
   ```

### Common Timeout Causes and Prevention

**Frequent culprits**:
- **Unclosed database connections**: Connection pool exhaustion
  - Prevention: Always use `with` statements or fixtures with proper teardown
- **Subprocess not terminated**: Orphaned myloader/mysqld processes
  - Prevention: Use `timeout` parameter in `subprocess.run`, ensure SIGTERM handling
- **Infinite retry loops**: Network operations without timeout
  - Prevention: Set explicit `timeout` on boto3 calls, mysql.connector operations
- **File handle leaks**: Open files never closed
  - Prevention: Use `with open(...)` or ensure `finally` blocks close resources
- **Deadlocks**: Threading/async coordination issues
  - Prevention: Avoid shared state, use thread-safe primitives, test with `-p no:xdist`

**Prevention checklist** (pre-commit):
- [ ] All file operations use `with` statements
- [ ] All database connections properly closed (fixtures or context managers)
- [ ] All subprocess calls have `timeout` parameter
- [ ] All network operations have explicit timeout (S3, MySQL)
- [ ] No global mutable state shared across tests
- [ ] Fixtures have proper teardown/cleanup

### Resource Cleanup Verification

**After any test run** (especially after timeout), verify:
```bash
# No orphaned MySQL connections
mysql -e "SHOW PROCESSLIST" | grep pulldb
# Expected: Empty output or only current connection

# No orphaned processes
ps aux | grep -E "(myloader|pytest)" | grep -v grep
# Expected: Empty output (all tests completed)

# No temp directories lingering
ls -la /tmp/*pulldb* 2>/dev/null | wc -l
# Expected: 0 (or small number if tests just ran)
```

### Integration into AI Agent Workflow

**Standard test execution workflow**:
1. Make code changes
2. Run: `pytest -q --timeout=60 --timeout-method=thread`
3. Check result:
   - **Pass** (exit 0, duration < 60s) → Report success with duration
   - **Timeout detected** → Invoke diagnostic protocol (steps 1-5 above)
   - **Other failure** → Report failures normally with traceback
4. Verify cleanup: No orphaned processes/connections/temp files
5. Document duration in commit messages: "98 tests passing in 12.3s"

**When to apply timeout monitoring**:
- ✅ Always: Full test suite after code changes
- ✅ Always: When user requests "run tests" or "proceed with tests"
- ✅ Always: During milestone completion verification
- ✅ Always: After modifying resource management code (database, subprocess, file I/O)
- ❌ Optional: Single test quick validation (unless that test previously timed out)

**Timeout threshold tuning**:
- Use `@pytest.mark.timeout(120)` for known slow integration tests
- Use `@pytest.mark.timeout(300)` for end-to-end restore workflow tests
- Document rationale in test docstring when using non-standard timeout

### Dependencies

**Required**: `pytest-timeout` plugin
```bash
pip install pytest-timeout
```

**Verification**:
```bash
pytest --version  # Should show pytest-timeout in plugins list
```

**Configuration** (optional `pytest.ini` or `pyproject.toml`):
```ini
[tool:pytest]
timeout = 60
timeout_method = thread
```
