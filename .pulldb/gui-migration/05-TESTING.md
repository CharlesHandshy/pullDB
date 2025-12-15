# 05 — Testing Protocol

---

## Before Each PR

Run these commands and verify no errors:

```bash
# 1. Lint check
ruff check pulldb/

# 2. Type check  
mypy pulldb/ --ignore-missing-imports

# 3. Unit tests
pytest tests/ -v --ignore=tests/e2e/

# 4. Template path validation
python3 scripts/validate_template_paths.py

# 5. Dev server + manual test
./start_dev.sh
# Open http://localhost:8000/web/login
```

---

## Manual Testing Checklist

| Flow | URL | What to Check |
|------|-----|---------------|
| Login | `/web/login` | Form works, redirects |
| Dashboard | `/web/dashboard` | Stats display, tables load |
| Restore | `/web/restore` | Customer search, **QA Template tab**, backup selection |
| Jobs | `/web/jobs` | Active/History tabs, cancel |
| Admin | `/web/admin` | All sections accessible |
| Manager | `/web/manager` | Team table loads |
| Profile | `/web/profile` | User info displays |

---

## Visual Regression

After CSS changes:
1. Open page in browser
2. Compare to baseline screenshot
3. Check light mode AND dark mode (after PR 12)
4. Check mobile viewport (375px width)

---

## E2E Tests (After PR 0)

```bash
# Full suite
pytest tests/e2e/ -v

# Specific test
pytest tests/e2e/test_login.py -v
```

---

## Final Validation (After All PRs)

```bash
# 1. No HCA violations
python3 scripts/validate_template_paths.py
# Expected: "✅ All template paths are HCA-compliant!"

# 2. No root templates (except base.html)
ls pulldb/web/templates/*.html
# Expected: Only base.html

# 3. All tests pass
pytest tests/ -v

# 4. No inline CSS > 10 lines
python3 scripts/audit_inline_css.py --min-lines 11
# Expected: "0 blocks"

# 5. No inline SVGs
grep -r "<svg" pulldb/web/templates/ | grep -v "partials/icons" | wc -l
# Expected: 0
```

---

## Manual Final Checklist

- [ ] Login works (light mode)
- [ ] Login works (dark mode)
- [ ] Dashboard displays for all roles
- [ ] Customer restore end-to-end
- [ ] **QA Template restore end-to-end** ⚠️
- [ ] Job cancellation works
- [ ] Admin settings save
- [ ] Theme toggle works
- [ ] Theme persists across sessions
- [ ] All sidebar links work
- [ ] No console errors
- [ ] Mobile viewport OK
