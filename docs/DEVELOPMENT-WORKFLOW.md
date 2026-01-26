# pullDB Development Workflow

> **Version**: 1.0.0  
> **Last Updated**: 2026-01-26

This document defines the development workflow for pullDB contributors.

---

## Table of Contents

1. [Git Workflow](#git-workflow)
2. [Branch Strategy](#branch-strategy)
3. [Commit Conventions](#commit-conventions)
4. [Pre-commit Checks](#pre-commit-checks)
5. [Code Review Process](#code-review-process)
6. [Release Process](#release-process)

---

## Git Workflow

### Feature Branch Flow

```
main (protected)
  │
  ├─── feature/add-new-endpoint ─── work ─── PR ─┐
  │                                              │
  ├─── fix/broken-auth ────────── work ─── PR ──┤
  │                                              │
  └─────────────────────── merge ◄───────────────┘
```

### Branch Naming Conventions

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feature/` | New functionality | `feature/add-bulk-restore` |
| `fix/` | Bug fixes | `fix/worker-timeout` |
| `docs/` | Documentation only | `docs/update-api-reference` |
| `refactor/` | Code cleanup | `refactor/simplify-auth` |
| `test/` | Test additions | `test/add-e2e-coverage` |
| `chore/` | Maintenance tasks | `chore/update-deps` |

### Quick Start

```bash
# Start new feature
git checkout main
git pull origin main
git checkout -b feature/my-feature

# Work on feature
# ... make changes ...
git add -p
git commit -m "feat: add new capability"

# Push and create PR
git push -u origin feature/my-feature
# Create PR via GitHub UI or CLI
```

---

## Branch Strategy

### Protected Branches

- **`main`**: Production-ready code. All changes via PR.

### Branch Lifecycle

1. **Create**: Branch from latest `main`
2. **Develop**: Make focused, atomic commits
3. **Test**: Ensure all checks pass locally
4. **PR**: Open pull request with description
5. **Review**: Address feedback
6. **Merge**: Squash merge to main
7. **Delete**: Remove feature branch after merge

### Keeping Branches Fresh

```bash
# Update your branch with latest main
git checkout feature/my-feature
git fetch origin
git rebase origin/main

# Or merge if you prefer
git merge origin/main
```

---

## Commit Conventions

### Format

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation changes |
| `style` | Formatting, no code change |
| `refactor` | Code restructuring |
| `test` | Adding/updating tests |
| `chore` | Maintenance, deps, tooling |
| `perf` | Performance improvement |

### Examples

```bash
# Feature
git commit -m "feat(api): add bulk job cancellation endpoint"

# Bug fix
git commit -m "fix(worker): prevent race condition in job pickup"

# Documentation
git commit -m "docs: update KNOWLEDGE-POOL with new endpoints"

# With body
git commit -m "fix(auth): handle expired tokens gracefully

Previously, expired tokens would cause 500 errors.
Now returns 401 with clear message.

Closes #123"
```

---

## Pre-commit Checks

### Automatic Hooks

These hooks run automatically when installed:

| Hook | Trigger | Purpose |
|------|---------|---------|
| `pre-commit` | `git commit` | Documentation drift check |
| `pre-push` | `git push` | Fast unit tests |

### Install Hooks

```bash
# Install pre-commit hook (documentation drift)
ln -sf ../../scripts/pre-commit-doc-audit.sh .git/hooks/pre-commit

# Install pre-push hook (fast tests)
ln -sf ../../scripts/pre-push-test.sh .git/hooks/pre-push
```

### Manual Checks

```bash
# Full documentation audit
python -m pulldb.audit --full

# Drift detection with AI context
python -m pulldb.audit --drift --copilot

# Run all tests
pytest

# Run fast tests only
pytest tests/unit -q
```

### Bypassing Hooks (Emergency Only)

```bash
git commit --no-verify -m "emergency: fix production issue"
git push --no-verify
```

---

## Code Review Process

### Before Opening PR

- [ ] All local tests pass
- [ ] Pre-commit hook passes
- [ ] KNOWLEDGE-POOL updated if needed
- [ ] SESSION-LOG entry added for significant work

### PR Description Template

```markdown
## Summary
Brief description of changes.

## Changes
- Change 1
- Change 2

## Testing
How was this tested?

## Documentation
- [ ] KNOWLEDGE-POOL updated
- [ ] API docs updated (if applicable)

## Related Issues
Closes #XXX
```

### Review Checklist

- [ ] Code follows HCA layer rules
- [ ] No FAIL HARD violations
- [ ] Tests cover new functionality
- [ ] Documentation is accurate

---

## Release Process

### Version Tagging

```bash
# After merging release-ready code
git checkout main
git pull origin main

# Create annotated tag
git tag -a v1.0.X -m "Release 1.0.X - Brief description"

# Push tag
git push origin v1.0.X
```

### Release Checklist

1. [ ] All tests pass on main
2. [ ] CHANGELOG.md updated
3. [ ] RELEASE-NOTES-vX.X.X.md created
4. [ ] Version bumped in `pyproject.toml`
5. [ ] Version bumped in `pulldb/__init__.py`
6. [ ] Tag created and pushed
7. [ ] GitHub release created

### Semantic Versioning

- **MAJOR** (1.x.x): Breaking changes
- **MINOR** (x.1.x): New features, backward compatible
- **PATCH** (x.x.1): Bug fixes, backward compatible

---

## Quick Reference

### Daily Workflow

```bash
# Morning: sync with main
git checkout main && git pull

# Start work
git checkout -b feature/my-work

# During day: commit often
git add -p && git commit -m "feat: progress on X"

# End of day: push WIP
git push -u origin feature/my-work
```

### Common Commands

```bash
# Check documentation drift
python -m pulldb.audit --drift

# Run tests
pytest tests/unit -q

# Format code
ruff format pulldb/

# Lint code
ruff check pulldb/
```

---

*For questions, see the project maintainers or check `.pulldb/CONTEXT.md`*
