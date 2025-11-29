# pullDB Documentation

> **Version**: 0.0.8 | **Start here to navigate all pullDB documentation**

---

## Documentation Map

```
START-HERE.md (you are here)
│
├─► User Documentation
│   ├── getting-started.md ──► Installation & quick start
│   └── cli-reference.md ────► Command reference
│
├─► Operations
│   ├── admin-guide.md ──────► Migrations, cleanup, monitoring
│   ├── deployment.md ───────► Service configuration
│   └── runbooks/ ───────────► Operational checklists
│       ├── runbook-restore.md
│       ├── runbook-failure.md
│       └── runbook-throttle.md
│
├─► Technical Reference
│   ├── architecture.md ─────► System design & data flow
│   ├── mysql-schema.md ─────► Database schema
│   └── development.md ──────► Contributing & dev setup
│
├─► Infrastructure
│   ├── policies/ ───────────► IAM policy templates
│   ├── terraform/ ──────────► IaC examples
│   └── KNOWLEDGE-POOL.md ───► AWS accounts, ARNs, secrets
│
└─► Design & Planning
    ├── roadmap.md ──────────► Future features
    └── diagrams/ ───────────► Architecture diagrams
```

---

## By Role

### 👨‍💻 Developer (CLI User)

**Goal**: Restore databases for local development

1. **[Getting Started](getting-started.md)** - Install CLI, configure endpoint
2. **[CLI Reference](cli-reference.md)** - All commands and options

```bash
# Quick start
pulldb restore customer=acme
pulldb status
pulldb history
```

---

### 🔧 System Administrator

**Goal**: Deploy, configure, and maintain pullDB services

1. **[Deployment](deployment.md)** - Install and configure services
2. **[Admin Guide](admin-guide.md)** - Migrations, cleanup, monitoring
3. **[Runbooks](../design/)** - Operational procedures

| Runbook | When to Use |
|---------|-------------|
| [runbook-restore.md](../design/runbook-restore.md) | Pre-restore checklist |
| [runbook-failure.md](../design/runbook-failure.md) | Troubleshooting failures |
| [runbook-throttle.md](../design/runbook-throttle.md) | Managing load |

---

### 🏗️ Infrastructure Engineer

**Goal**: Set up AWS resources and cross-account access

1. **[KNOWLEDGE-POOL.md](KNOWLEDGE-POOL.md)** - Account IDs, ARNs, secrets
2. **[policies/](policies/)** - IAM policy templates
3. **[terraform/](terraform/)** - Infrastructure as Code examples

| Resource | File |
|----------|------|
| Staging S3 read | `policies/pulldb-staging-s3-read.json` |
| Secrets Manager access | `policies/pulldb-secrets-manager-access.json` |
| Production cross-account | `policies/pulldb-prod-policy.json` |
| Cross-account Terraform | `terraform/pulldb_cross_account.tf` |

---

### 🧑‍💻 Contributor / Developer

**Goal**: Contribute to pullDB codebase

1. **[Development](development.md)** - Dev environment setup
2. **[Architecture](architecture.md)** - System design
3. **[MySQL Schema](mysql-schema.md)** - Database structure

**Key source directories:**
```
pulldb/
├── api/      # FastAPI service
├── cli/      # Click CLI
├── worker/   # Job processing
├── domain/   # Models, config
└── infra/    # MySQL, S3, secrets
```

---

## Document Index

### Core Documentation

| Document | Description | Audience |
|----------|-------------|----------|
| [getting-started.md](getting-started.md) | Installation and quick start | All |
| [cli-reference.md](cli-reference.md) | Complete CLI command reference | Users |
| [architecture.md](architecture.md) | System design, components, data flow | Developers |
| [deployment.md](deployment.md) | Service installation and configuration | Admins |
| [admin-guide.md](admin-guide.md) | Migrations, cleanup, monitoring | Admins |
| [development.md](development.md) | Contributing, testing, coding standards | Contributors |
| [mysql-schema.md](mysql-schema.md) | Database schema and invariants | Developers |

### Reference

| Document | Description |
|----------|-------------|
| [KNOWLEDGE-POOL.md](KNOWLEDGE-POOL.md) | AWS accounts, ARNs, secrets, operational facts |
| [FAIL-HARD.md](FAIL-HARD.md) | Template for documenting failures |
| [WORKSPACE-INDEX.md](WORKSPACE-INDEX.md) | Codebase structure index |

### Infrastructure

| Path | Description |
|------|-------------|
| [policies/](policies/) | IAM policy JSON templates |
| [terraform/](terraform/) | Terraform examples for cross-account setup |

### Operational

| Document | Description |
|----------|-------------|
| [runbook-restore.md](../design/runbook-restore.md) | Restore operation checklist |
| [runbook-failure.md](../design/runbook-failure.md) | Failure troubleshooting |
| [runbook-throttle.md](../design/runbook-throttle.md) | Load management |
| [roadmap.md](../design/roadmap.md) | Future features and phases |

---

## Quick Links

| Task | Go To |
|------|-------|
| Install CLI | [getting-started.md#quick-start](getting-started.md#quick-start-5-minutes) |
| Submit a restore | [cli-reference.md#restore](cli-reference.md#restore) |
| Check job status | [cli-reference.md#status](cli-reference.md#status) |
| Deploy services | [deployment.md](deployment.md) |
| Run migrations | [admin-guide.md#schema-migrations](admin-guide.md#schema-migrations) |
| Clean orphaned DBs | [admin-guide.md#staging-cleanup](admin-guide.md#staging-cleanup) |
| Set concurrency limits | [admin-guide.md#settings-management](admin-guide.md#settings-management) |
| Troubleshoot failure | [runbook-failure.md](../design/runbook-failure.md) |

---

## Version History

| Version | Phase | Key Changes |
|---------|-------|-------------|
| 0.0.8 | 4 | Web auth, sessions, role-based access |
| 0.0.7 | 3 | Multi-S3 locations, search command |
| 0.0.6 | 2 | Concurrency controls, cleanup |
| 0.0.5 | 1 | Cancellation, staging cleanup |
| 0.0.1 | 0 | Initial release |

---

[Getting Started →](getting-started.md) · [CLI Reference](cli-reference.md) · [Architecture](architecture.md)

*Last updated: November 2025*
