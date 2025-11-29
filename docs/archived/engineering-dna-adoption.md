# Engineering DNA Adoption Guide

## Purpose

Document how the vendored `dna_repo/` snapshot integrates into `pullDB`, the
planned evolution toward an external dependency (submodule, subtree, or package),
and operational procedures for keeping protocols and tooling in sync.

## Scope

Applies to:
- Protocol documents (FAIL HARD, Pre-Commit Hygiene, Test Timeout Monitoring)
- Tooling scripts (precommit-verify, ensure_fail_hard, drift_auditor)
- Optional JSON Schema (`dna-config.schema.json`)

Excludes runtime business logic for restore workflow (handled elsewhere in design docs).

## Rationale for Vendoring (Initial Phase)

| Criterion        | Vendored Snapshot | Submodule | Subtree | Package |
|------------------|-------------------|-----------|---------|---------|
| Setup Complexity | Low               | Medium    | Medium  | Low     |
| Sync Visibility  | High (explicit)   | Medium    | Medium  | Low     |
| External Depend. | None              | Remote    | Remote  | Index   |
| Partial Updates  | Simple manual     | Upstream commit needed | Merge complexity | Version bump |
| Multi-Language   | Yes               | Yes       | Yes     | Python only |

Early development favors immediate accessibility and zero external friction; later
stages can adopt automation once restore workflow stabilizes.

## Planned Evolution Path

1. Prototype (Current): Vendored snapshot under `dna_repo/`.
2. Stabilization: Introduce `dna-config.json` gating and CI enforcement.
3. Externalization: Publish `engineering-dna` repository; convert to git submodule
   or subtree for clearer upstream lineage.
4. Packaging (Optional): Distribute Python-specific tooling via PyPI for reuse in
   other internal projects.

## Sync Procedure

Steps when upstream repository updates (post externalization):
1. Fetch upstream changes (`git fetch origin`).
2. Compare local `dna_repo/` files with upstream HEAD.
3. Replace protocol markdown verbatim.
4. Merge tool script changes; retain local project-specific adjustments with comments.
5. Run hygiene gates:
   - `python3 dna_repo/tools/precommit-verify.py`
   - `python3 dna_repo/tools/ensure_fail_hard.py`
   - `python3 dna_repo/tools/drift_auditor.py`
6. Update `dna_repo/README.md` `Last Synced` timestamp.
7. Commit with FAIL HARD hygiene block and reference to upstream commit hash.

## dna-config.json (Future)

Example (planned):
```json
{
  "gates": {"format": true, "lint": true, "types": true, "tests": true, "drift": true},
  "protocols": {"fail_hard": true, "timeout_monitoring": true, "hygiene": true},
  "notifications": {"slack_webhook": "https://hooks.slack.com/services/..."}
}
```

Usage:
- Pre-commit script reads file to determine which gates to run.
- CI passes `--config dna-config.json` parameter to verify script (extension planned).
- Drift auditor may later ensure enabled gates appear in README and `.github/copilot-instructions.md`.

## Developer Workflow Integration

Add to `.pre-commit-config.yaml` (planned):
```yaml
- repo: local
  hooks:
    - id: engineering-dna-verify
      name: Engineering DNA Hygiene
      entry: python3 dna_repo/tools/precommit-verify.py
      language: system
      pass_filenames: false
```

CI Workflow (planned snippet):
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

## Risk & Mitigation

| Risk | Mitigation |
|------|------------|
| Stale protocols | Scheduled monthly sync review & README timestamp update |
| Divergent tooling | Keep local modifications commented with `# LOCAL MOD` marker |
| Over-enforcement friction | Start with advisory gating; escalate to blocking after stability |
| Hidden drift | Routine drift auditor runs in CI |

## Success Criteria

1. All commits pass Engineering DNA hygiene gates.
2. FAIL HARD references present in control documents.
3. Sync timestamps updated at least monthly or after upstream changes.
4. No untracked protocol divergences between local and upstream repositories.

## Open Questions

1. Should notification integration (Slack/email) reside in generic script or project-specific layer?
2. Will future metrics (test duration trends) be aggregated centrally or per-repo?
3. Should `dna-config.json` support per-language extensions (e.g., `python`, `nodejs` blocks)?

## Next Actions

- Wire pre-commit hook.
- Add CI job referencing vendored scripts.
- Draft initial `dna-config.json` (disabled gates default to true without file initially).
