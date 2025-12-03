# HCA Documentation Root

> Documentation organized by Hierarchical Containment Architecture layers.

## Layer Index

```
┌─────────────────────────────────────────────────────────┐
│ plugins/     External integrations (myloader, terraform)│
├─────────────────────────────────────────────────────────┤
│ pages/       User-facing guides (CLI, Web, Admin)       │
├─────────────────────────────────────────────────────────┤
│ widgets/     Integration guides (Worker setup, Deploy)  │
├─────────────────────────────────────────────────────────┤
│ features/    Feature docs (Restore, Download, Staging)  │
├─────────────────────────────────────────────────────────┤
│ entities/    Data models (Schema, Config, Models)       │
├─────────────────────────────────────────────────────────┤
│ shared/      Infrastructure (Logging, Errors, S3, MySQL)│
└─────────────────────────────────────────────────────────┘
```

## Quick Navigation

| Layer | Purpose | Key Docs |
|-------|---------|----------|
| [shared/](shared/) | Infrastructure patterns | FAIL-HARD, Logging, MySQL, S3 |
| [entities/](entities/) | Data models & schema | mysql-schema, config, models |
| [features/](features/) | Business operations | restore, download, staging |
| [widgets/](widgets/) | Service integration | deployment, worker setup |
| [pages/](pages/) | User guides | CLI reference, admin guide |
| [plugins/](plugins/) | External tools | myloader, terraform |

## Cross-Layer References

- **Operational Facts**: [../KNOWLEDGE-POOL.md](../KNOWLEDGE-POOL.md)
- **Code Index**: [../WORKSPACE-INDEX.md](../WORKSPACE-INDEX.md)
- **HCA Standard**: [../../.pulldb/standards/hca.md](../../.pulldb/standards/hca.md)

## Layer Import Rules

Documentation follows same containment as code:
- **shared/** ← Referenced by ALL layers
- **entities/** ← Referenced by features, widgets, pages
- **features/** ← Referenced by widgets, pages
- **widgets/** ← Referenced by pages only
- **pages/** ← End-user documentation
- **plugins/** ← External tool documentation
