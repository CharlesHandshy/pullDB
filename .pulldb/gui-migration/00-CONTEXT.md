# 00 — Context Loading

> **For AI Agents**: Load these documents IN ORDER before starting ANY work.

---

## Required Reading (In Order)

```
1. .pulldb/CONTEXT.md                    # Project-specific context
2. engineering-dna/AGENT-CONTEXT.md      # Universal AI patterns  
3. .pulldb/standards/hca.md              # HCA layer model (CRITICAL)
4. docs/KNOWLEDGE-POOL.md                # AWS/infra facts
5. docs/STYLE-GUIDE.md                   # Current design docs
6. THIS DIRECTORY                        # GUI migration plan
```

---

## Key Principles

### FAIL HARD
Never silently degrade. If something breaks:
1. Stop immediately
2. Report what was attempted
3. Report why it failed
4. Suggest solutions

### HCA Compliance
All templates MUST follow Hierarchical Containment Architecture:
- Templates go under `features/{feature}/`
- Icons organized by HCA layer in `partials/icons/`
- Imports only from same or lower layers

### Session Logging
Log significant work to `.pulldb/SESSION-LOG.md`:
- After completing a PR
- After finding issues
- Before ending session

---

## Git Workflow

### Branch Naming
```
gui/{pr-number}-{short-description}

Examples:
- gui/pr0-tooling-baseline
- gui/pr1-foundation-icons
- gui/pr5-restore-qatemplate
```

### Standard Commands
```bash
# Start new PR branch
git checkout main && git pull origin main
git checkout -b gui/prX-description

# Commit frequently
git add -A && git commit -m "gui(prX): description"

# Before merge - rebase
git checkout main && git pull origin main
git checkout gui/prX-description && git rebase main

# Merge to main
git checkout main && git merge gui/prX-description
git push origin main && git branch -d gui/prX-description
```

---

## Audit Scripts Available

Run these to validate work:

```bash
# Find all inline SVGs (101 unique icons)
python3 scripts/audit_inline_svgs.py

# Find all inline CSS (10,193 lines!)
python3 scripts/audit_inline_css.py

# Validate HCA template paths
python3 scripts/validate_template_paths.py
```
