# 06 — Troubleshooting

---

## Template Not Found

**Error**:
```
jinja2.exceptions.TemplateNotFound: features/jobs/detail.html
```

**Solution**:
1. Check route uses correct path
2. Run `python3 scripts/validate_template_paths.py`
3. Verify file exists at expected location

---

## Icon Not Rendering

**Output**:
```html
<!-- Icon not found: unknown-icon -->
```

**Solution**:
1. Check icon name exists in `partials/icons/` files
2. Run `python3 scripts/audit_inline_svgs.py` to see available icons
3. Add missing icon to appropriate layer file

---

## CSS Not Applying

**Solution**:
1. Hard refresh browser (Ctrl+Shift+R)
2. Check CSS file linked in base.html
3. Check class names match exactly
4. Check browser dev tools for 404s

---

## QA Template Not Working (PR 5)

**Solution**:
1. Check hidden input exists:
   ```html
   <input name="qatemplate" value="false" id="qatemplate-input">
   ```
2. Check JavaScript tab switching code is present
3. Test backup API directly:
   ```
   GET /api/backups?customer=qatemplate
   ```
4. Check browser console for JS errors

---

## Dark Mode Colors Wrong

**Solution**:
1. Check `[data-theme="dark"]` selector in CSS
2. Verify all color variables have dark mode overrides
3. Test with browser dev tools:
   - Elements tab → html element
   - Add `data-theme="dark"` attribute
4. Check contrast ratios meet WCAG AA

---

## Route Returns 404

**Solution**:
1. Check route is registered in `routes/__init__.py`
2. Check template path in route handler
3. Restart dev server: `./start_dev.sh`

---

## Merge Conflicts on Rebase

**Solution**:
```bash
# See conflicting files
git status

# For each file, resolve conflicts, then:
git add <file>

# Continue rebase
git rebase --continue

# If hopeless, abort and try fresh:
git rebase --abort
```

---

## Rollback Procedure

If a PR breaks something critical:

```bash
# 1. Find breaking commit
git log --oneline -10

# 2. Revert merge
git revert -m 1 <merge-commit-hash>

# 3. Push revert
git push origin main

# 4. Create fix branch
git checkout <commit-before-break>
git checkout -b gui/prX-fix

# 5. Fix, then re-merge
```
