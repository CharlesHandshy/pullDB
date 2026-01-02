# pullDB Documentation

> **Version**: 0.2.0 | **Start here to navigate all pullDB documentation**

---

## HCA Documentation Structure

All documentation is organized by **Hierarchical Containment Architecture** layers:

```
docs/hca/                 ← ALL documentation lives here
├── shared/              Infrastructure (FAIL-HARD)
├── entities/            Data models (mysql-schema)
├── features/            Business logic (staging, atomic rename)
├── widgets/             Integration (deployment, architecture)
├── pages/               User guides (CLI, admin, development)
└── plugins/             External tools (myloader, policies, terraform)
```

> **[📂 Browse All Docs →](hca/README.md)**

---

## Quick Links by Role

### 👨‍💻 Developer (CLI User)

| Goal | Document |
|------|----------|
| Install & setup | [hca/pages/getting-started.md](hca/pages/getting-started.md) |
| CLI commands | [hca/pages/cli-reference.md](hca/pages/cli-reference.md) |

### 🔧 System Administrator

| Goal | Document |
|------|----------|
| Deploy services | [hca/widgets/deployment.md](hca/widgets/deployment.md) |
| Admin tasks | [hca/pages/admin-guide.md](hca/pages/admin-guide.md) |
| Architecture | [hca/widgets/architecture.md](hca/widgets/architecture.md) |

### 🏗️ Infrastructure Engineer

| Goal | Document |
|------|----------|
| IAM policies | [hca/plugins/policies/](hca/plugins/policies/) |
| Terraform | [hca/plugins/terraform/](hca/plugins/terraform/) |
| AWS facts | [KNOWLEDGE-POOL.md](KNOWLEDGE-POOL.md) |

### 🧑‍💻 Contributor

| Goal | Document |
|------|----------|
| Development setup | [hca/pages/development.md](hca/pages/development.md) |
| Schema reference | [hca/entities/mysql-schema.md](hca/entities/mysql-schema.md) |
| myloader patterns | [hca/plugins/myloader.md](hca/plugins/myloader.md) |

---

## Reference Files (Non-HCA)

These files are kept at docs/ root for tooling/operational access:

| File | Purpose |
|------|---------|
| `KNOWLEDGE-POOL.md` | AWS account IDs, ARNs, secrets |
| `KNOWLEDGE-POOL.json` | Machine-readable operational facts |
| `WORKSPACE-INDEX.md` | Codebase structure index |
| `WORKSPACE-INDEX.json` | Machine-readable code index |
| `VERIFICATION-REPORT.md` | Project audit results |

---

## Archived Documentation

Historical and superseded documents are in `archived/`:
- `archived/superseded/` - Docs replaced by HCA versions
- `archived/debug-reports/` - Debug session artifacts
- `archived/audit-reports/` - Previous audits
- `archived/historical/` - Planning documents

---

*Last updated: January 2026*

*[HCA Documentation Root →](hca/README.md)*
