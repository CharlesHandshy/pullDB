# VS Code Diagnostic Integration

This document explains how to use VS Code's diagnostic information to proactively check and fix code issues.

## The `get_errors` Tool

AI coding agents can use the `get_errors` tool to access real-time diagnostic information from VS Code extensions like Ruff, mypy, and other linters.

### What Information is Available?

The `get_errors` tool provides:
- **Ruff diagnostics**: Style violations, missing docstrings, unused imports, etc.
- **Mypy diagnostics**: Type checking errors, incompatible types, missing type hints
- **Other linters**: SQLFluff, markdownlint, yamllint, shellcheck (if configured)

### Example Usage

```python
# Check a specific file
get_errors(filePaths=["/path/to/file.py"])

# Check multiple files
get_errors(filePaths=["/path/to/file1.py", "/path/to/file2.py"])

# Check all files (omit filePaths parameter)
get_errors()
```

### Example Output

```
config.py:16 - Missing docstring in public class Ruff(D101)
main.py:25 - Line too long (102 > 88) Ruff(E501)
main.py:6 - Import block is un-sorted or un-formatted Ruff(I001)
```

## Proactive Error Checking Workflow

### 1. Before Editing

Always check for existing errors before making changes:

```python
get_errors(filePaths=["pulldb/domain/config.py"])
```

This helps you understand:
- What issues already exist
- What needs to be fixed
- Context for the changes you're about to make

### 2. Make Changes

Address the issues found, following the coding standards:
- Add missing docstrings (D101-D107)
- Fix line length issues (E501)
- Sort imports (I001)
- Fix naming conventions (N802, N806)

### 3. After Editing

Verify the fixes worked:

```python
get_errors(filePaths=["pulldb/domain/config.py"])
```

Expected result: `No errors found`

### 4. Iterate if Needed

If new errors appear, repeat the process until all issues are resolved.

## Common Ruff Error Codes

### Docstring Issues (D-series)
- **D101**: Missing docstring in public class
- **D102**: Missing docstring in public method
- **D103**: Missing docstring in public function
- **D400**: First line should end with a period
- **D401**: First line of docstring should be in imperative mood

### Style Issues (E-series)
- **E501**: Line too long (> 88 characters)
- **E701**: Multiple statements on one line (colon)
- **E702**: Multiple statements on one line (semicolon)
- **E711**: Comparison to None should be `cond is None`

### Import Issues (F-series)
- **F401**: Module imported but unused
- **F811**: Redefinition of unused name
- **F841**: Local variable assigned but never used
- **I001**: Import block is un-sorted or un-formatted

### Naming Issues (N-series)
- **N802**: Function name should be lowercase
- **N806**: Variable in function should be lowercase
- **N815**: Variable in class scope should not be mixedCase

### Best Practice Issues (B-series)
- **B904**: Within an except clause, raise exceptions with `raise ... from err`
- **B006**: Do not use mutable data structures for argument defaults

## Ruff Rule Documentation

To get detailed information about any Ruff rule:

```bash
ruff rule D101
```

This shows:
- Rule description
- Why it matters
- Examples of violations
- How to fix it

## VS Code Extension Setup

### Required Extensions

1. **Ruff** (`charliermarsh.ruff`) - Python linting and formatting
2. **Pylance** (`ms-python.vscode-pylance`) - Python language server
3. **mypy** (`matangover.mypy`) - Python type checking

### Recommended Extensions

4. **markdownlint** (`DavidAnson.vscode-markdownlint`) - Markdown linting
5. **SQLFluff** (`dorzey.vscode-sqlfluff`) - SQL linting
6. **YAML** (`redhat.vscode-yaml`) - YAML validation
7. **ShellCheck** (`timonwong.shellcheck`) - Shell script linting

### Extension Settings

See `.vscode/settings.json` for complete configuration. Key settings:

```json
{
  "ruff.enable": true,
  "ruff.format.enable": true,
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  }
}
```

## Integration with Pre-commit Hooks

The same checks that VS Code runs are also enforced via pre-commit hooks:

```bash
# Install hooks
pre-commit install

# Run all checks manually
pre-commit run --all-files
```

This ensures code quality is maintained even if someone doesn't use VS Code.

## Benefits of This Workflow

1. **Catch Issues Early**: See problems as you type, not after committing
2. **Learn Standards**: Ruff provides explanations for each rule
3. **Consistent Quality**: Same checks in editor and CI/CD
4. **Fast Feedback**: Ruff is 10-100x faster than traditional linters
5. **Automated Fixes**: Many issues can be auto-fixed with `--fix`

## Example: Fixing Missing Docstring

### Before

```python
class Config:
    mysql_host: str
    mysql_user: str
```

**Error**: `config.py:16 - Missing docstring in public class Ruff(D101)`

### After

```python
class Config:
    """Configuration for pullDB with AWS Parameter Store support.

    Stores configuration values for database connections, S3 paths, AWS profiles,
    and working directories.

    Attributes:
        mysql_host: MySQL server hostname for pullDB coordination database.
        mysql_user: MySQL username for authentication.
    """
    mysql_host: str
    mysql_user: str
```

**Verification**: `get_errors` returns `No errors found`

## Tips for AI Agents

1. **Always check before editing**: Run `get_errors` first
2. **Be specific**: Check individual files rather than all files
3. **Verify fixes**: Run `get_errors` after each change
4. **Read the suggestions**: VS Code often provides fix examples
5. **Use rule docs**: Run `ruff rule <code>` for detailed explanations
6. **Follow conventions**: Use Google-style docstrings (see coding-standards.md)

## See Also

- `docs/coding-standards.md` - Comprehensive coding standards for all file types
- `constitution.md` - Development workflow and tooling philosophy
- `.pre-commit-config.yaml` - Automated quality checks
- `pyproject.toml` - Ruff configuration
