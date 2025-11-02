# Engineering DNA Developer Instructions

## Overview

This guide explains how to use the vendored Engineering DNA snapshot located in
`dna_repo/` to enforce quality gates locally and in CI.

## Pre-Commit Hook Setup (Planned)

Add the following to `.pre-commit-config.yaml`:

```yaml
- repo: local
  hooks:
    - id: engineering-dna-verify
      name: Engineering DNA Hygiene
      entry: python3 dna_repo/tools/precommit-verify.py
      language: system
      pass_filenames: false
```

Then install hooks:

```bash
pre-commit install
```

## Manual Gate Execution

```bash
python3 dna_repo/tools/precommit-verify.py        # Format + lint + types + tests
python3 dna_repo/tools/ensure_fail_hard.py        # Control doc FAIL HARD presence
python3 dna_repo/tools/drift_auditor.py           # Drift ledger completeness check
```

All scripts emit FAIL HARD diagnostics on failure (Goal / Problem / Root Cause / Solutions).

## Adding dna-config.json (Future)

Create `dna-config.json` in repo root to parameterize gates:

```json
{
  "gates": {"format": true, "lint": true, "types": true, "tests": true, "drift": true},
  "protocols": {"fail_hard": true, "timeout_monitoring": true, "hygiene": true}
}
```

Script extension will allow selective disabling (e.g., temporary `"types": false` during migration).

## CI Integration (Planned)

Example workflow excerpt:

```yaml
jobs:
  dna-hygiene:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements-dev.txt
      - run: python3 dna_repo/tools/precommit-verify.py
      - run: python3 dna_repo/tools/drift_auditor.py
      - run: python3 dna_repo/tools/ensure_fail_hard.py
```

## Syncing with Upstream (Once Externalized)

1. Pull latest upstream repository changes.
2. Replace protocol markdown files verbatim.
3. Merge tool script changes; mark local customizations with `# LOCAL MOD`.
4. Run gates to confirm no regression.
5. Update `dna_repo/README.md` `Last Synced` timestamp.
6. Commit with hygiene block referencing upstream commit hash.

## Troubleshooting

| Symptom | Root Cause | Solution |
|---------|------------|----------|
| Script exits non-zero, vague stderr | Missing dependencies | Install dev requirements (ruff, mypy, pytest, plugin) |
| Drift auditor fails after README edit | Ledger lines renamed | Restore expected wording or adjust auditor list |
| ensure_fail_hard reports missing | Section removed unintentionally | Re-add canonical FAIL HARD block |

## Next Enhancements

- Extend `precommit-verify.py` to parse `dna-config.json` gates.
- Add performance baseline tracking (test duration trend alerting).
- Integrate Slack notification on FAIL HARD CI failures.
