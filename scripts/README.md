# pullDB Scripts

Operational tooling, installers, and diagnostics for pullDB.

## Directory Structure

```
scripts/
├── archived/           # Historical scripts (reference only)
├── lib/                # Shared shell libraries
│   └── validate-common.sh
├── validate/           # Validation pipeline (numbered phases)
│   ├── 00-prerequisites.sh
│   ├── 10-install.sh
│   ├── 20-unit-tests.sh
│   ├── 30-integration.sh
│   ├── 40-e2e-restore.sh
│   └── 99-teardown.sh
└── [scripts]           # Active scripts (see below)
```

## Script Categories

### Packaging (bundled into .deb)

These scripts are copied into `/opt/pulldb.service/scripts/` during package install:

| Script | Purpose |
|--------|---------|
| `install_pulldb.sh` | Main installer |
| `uninstall_pulldb.sh` | Uninstaller |
| `upgrade_pulldb.sh` | Upgrade handler |
| `configure-pulldb.sh` | Interactive configuration |
| `configure_server.sh` | Server AWS setup |
| `merge-config.sh` | Config migration during upgrades |
| `monitor_jobs.py` | Job/process monitoring |
| `service-validate.sh` | Production validation |

### Build

| Script | Purpose |
|--------|---------|
| `build_deb.sh` | Build server .deb package |
| `build_client_deb.sh` | Build client .deb package |

### Infrastructure Setup

| Script | Purpose |
|--------|---------|
| `setup-aws.sh` | Install/configure AWS CLI |
| `setup-aws-credentials.sh` | Validate AWS credentials |
| `setup-mysql.sh` | Install/configure MySQL |
| `setup-test-environment.sh` | Full test environment setup |
| `setup_test_env.sh` | Python venv setup only |
| `teardown-test-environment.sh` | Cleanup test environment |
| `start-test-services.sh` | Start services in test env |

### Validation

| Script | Purpose |
|--------|---------|
| `pulldb-validate.sh` | Main validation orchestrator |
| `verify-secrets-perms.sh` | IAM/Secrets Manager permissions |
| `verify-aws-access.py` | Cross-account S3 access |

### Operations

| Script | Purpose |
|--------|---------|
| `cleanup_dev_env.py` | Drop test databases |
| `cleanup_system.sh` | System cleanup |
| `deploy-iam-templates.sh` | Print IAM CLI commands |

### Development

| Script | Purpose |
|--------|---------|
| `precommit-verify.py` | Pre-commit hygiene gates |
| `validate-knowledge-pool.py` | JSON/MD sync validation |
| `validate-metrics-emission.py` | Metrics infrastructure test |
| `ensure_fail_hard.py` | Doc compliance check |
| `benchmark_atomic_rename.py` | Rename performance benchmark |
| `deploy_atomic_rename.py` | Deploy stored procedure |
| `generate_cloudshell.py` | Generate AWS CLI scripts |
| `update-engineering-dna.sh` | Update submodule |
| `audit-permissions.sh` | File permission audit |
| `ci-permissions-check.sh` | CI permission check |

---

## Key Scripts

### verify-secrets-perms.sh

Verifies `pulldb-ec2-service-role` has correct Secrets Manager permissions.

```bash
./scripts/verify-secrets-perms.sh --profile dev-admin
./scripts/verify-secrets-perms.sh --profile dev-admin --secret /pulldb/mysql/api
```

### monitor_jobs.py

Reconciles active jobs with system processes.

```bash
python3 scripts/monitor_jobs.py          # Check status
python3 scripts/monitor_jobs.py --fix    # Mark dead jobs as failed
```

### pulldb-validate.sh

Comprehensive validation framework.

```bash
./scripts/pulldb-validate.sh --quick     # Prerequisites + unit tests
./scripts/pulldb-validate.sh --full      # + integration tests
./scripts/pulldb-validate.sh --e2e       # + end-to-end restore
```

### merge-config.sh

Smart config merge for upgrades (used by postinst).

```bash
./scripts/merge-config.sh env existing.env template.env output.env
./scripts/merge-config.sh ini existing.config template.config output.config
```

---

## Archived Scripts

See `archived/README.md` for historical scripts retained for reference.
